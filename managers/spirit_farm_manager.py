# managers/spirit_farm_manager.py
"""灵田系统管理器"""

import json
import time
from typing import TYPE_CHECKING, Dict, Optional, Tuple

from ..data import DataBase
from ..models import Player

if TYPE_CHECKING:
    from ..core import StorageRingManager

__all__ = ["SpiritFarmManager", "SPIRIT_HERBS", "FARM_LEVELS"]


SPIRIT_HERBS = {
    "灵草": {"grow_time": 3600, "exp_yield": 500, "gold_yield": 100, "wither_time": 172800},
    "血灵草": {"grow_time": 7200, "exp_yield": 1500, "gold_yield": 300, "wither_time": 172800},
    "冰心草": {"grow_time": 14400, "exp_yield": 4000, "gold_yield": 800, "wither_time": 172800},
    "火焰花": {"grow_time": 28800, "exp_yield": 10000, "gold_yield": 2000, "wither_time": 172800},
    "九叶灵芝": {"grow_time": 86400, "exp_yield": 30000, "gold_yield": 6000, "wither_time": 172800},
}

FARM_LEVELS = {
    1: {"slots": 3, "upgrade_cost": 5000},
    2: {"slots": 5, "upgrade_cost": 15000},
    3: {"slots": 8, "upgrade_cost": 50000},
    4: {"slots": 12, "upgrade_cost": 150000},
    5: {"slots": 20, "upgrade_cost": 0},
}


class SpiritFarmManager:
    """灵田管理器"""

    def __init__(self, db: DataBase, storage_ring_manager: "StorageRingManager" = None):
        self.db = db
        self.storage_ring_manager = storage_ring_manager

    async def get_user_farm(self, user_id: str) -> Optional[Dict]:
        """获取用户灵田信息。"""
        async with self.db.conn.execute(
            "SELECT * FROM spirit_farms WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None

            data = dict(row)
            data["crops"] = json.loads(data.get("crops", "[]"))
            return data

    async def create_farm(self, player: Player) -> Tuple[bool, str]:
        """开垦灵田。"""
        existing = await self.get_user_farm(player.user_id)
        if existing:
            return False, "❌ 你已经拥有灵田了！"

        cost = 10000
        if player.gold < cost:
            return False, f"❌ 开垦灵田需要 {cost:,} 灵石。"

        player.gold -= cost
        await self.db.update_player(player)

        await self.db.conn.execute(
            """
            INSERT INTO spirit_farms (user_id, level, crops)
            VALUES (?, 1, '[]')
            """,
            (player.user_id,),
        )
        await self.db.conn.commit()

        return True, (
            "🌱 灵田开垦成功！\n"
            "━━━━━━━━━━━━━━━\n"
            "灵田等级：Lv.1\n"
            "种植格数：3\n"
            "━━━━━━━━━━━━━━━\n"
            "可种植：灵草、血灵草、冰心草、火焰花、九叶灵芝"
        )

    async def plant_herb(self, player: Player, herb_name: str, count: int = 1) -> Tuple[bool, str]:
        """种植灵草，支持批量种植。"""
        herb_name = (herb_name or "").strip()
        count = int(count or 0)

        if herb_name not in SPIRIT_HERBS:
            herbs_list = "、".join(SPIRIT_HERBS.keys())
            return False, f"❌ 未知的灵草。可种植：{herbs_list}"

        farm = await self.get_user_farm(player.user_id)
        if not farm:
            return False, "❌ 你还没有灵田！请先使用 /开垦灵田"

        level_config = FARM_LEVELS.get(farm["level"], FARM_LEVELS[1])
        max_slots = level_config["slots"]
        crops = farm["crops"]
        available_slots = max_slots - len(crops)

        if available_slots <= 0:
            return False, f"❌ 灵田已满！最多只能种植 {max_slots} 株。"

        if count <= 0:
            return False, "❌ 种植数量必须大于 0。"

        requested_count = count
        plant_count = min(requested_count, available_slots)
        herb_config = SPIRIT_HERBS[herb_name]
        plant_time = int(time.time())
        mature_time = plant_time + herb_config["grow_time"]

        for _ in range(plant_count):
            crops.append(
                {
                    "name": herb_name,
                    "plant_time": plant_time,
                    "mature_time": mature_time,
                }
            )

        await self.db.conn.execute(
            "UPDATE spirit_farms SET crops = ? WHERE user_id = ?",
            (json.dumps(crops), player.user_id),
        )
        await self.db.conn.commit()

        grow_hours = herb_config["grow_time"] // 3600
        msg_lines = [
            f"🌱 成功种植【{herb_name}】x{plant_count}",
            f"成熟时间：约 {grow_hours} 小时",
            f"当前种植：{len(crops)}/{max_slots}",
        ]
        if requested_count > plant_count:
            msg_lines.append(f"⚠️ 灵田空位不足，请求 {requested_count} 株，实际种植 {plant_count} 株。")
        return True, "\n".join(msg_lines)

    async def harvest(self, player: Player) -> Tuple[bool, str]:
        """收获灵草。"""
        farm = await self.get_user_farm(player.user_id)
        if not farm:
            return False, "❌ 你还没有灵田！"

        crops = farm["crops"]
        if not crops:
            return False, "❌ 灵田里没有种植任何灵草。"

        now = int(time.time())
        mature_crops = []
        withered_crops = []
        remaining_crops = []

        for crop in crops:
            herb_config = SPIRIT_HERBS.get(crop["name"], SPIRIT_HERBS["灵草"])
            if now < crop["mature_time"]:
                remaining_crops.append(crop)
                continue

            wither_deadline = crop["mature_time"] + herb_config.get("wither_time", 172800)
            if now >= wither_deadline:
                withered_crops.append(crop)
            else:
                mature_crops.append(crop)

        if not mature_crops and not withered_crops:
            return False, "❌ 目前没有成熟的灵草可以收获。"

        total_exp = 0
        total_gold = 0
        herb_counts: Dict[str, int] = {}

        for crop in mature_crops:
            herb_name = crop["name"]
            herb_config = SPIRIT_HERBS.get(herb_name, SPIRIT_HERBS["灵草"])
            total_exp += herb_config["exp_yield"]
            total_gold += herb_config["gold_yield"]
            herb_counts[herb_name] = herb_counts.get(herb_name, 0) + 1

        if total_exp > 0 or total_gold > 0:
            player.experience += total_exp
            player.gold += total_gold
            await self.db.update_player(player)

        stored_items = []
        if self.storage_ring_manager:
            for herb_name, count in herb_counts.items():
                success, _ = await self.storage_ring_manager.store_item(player, herb_name, count, silent=True)
                if success:
                    stored_items.append(f"{herb_name}x{count}")
                else:
                    stored_items.append(f"{herb_name}x{count}（储物戒已满，掉落丢失）")

        await self.db.conn.execute(
            "UPDATE spirit_farms SET crops = ? WHERE user_id = ?",
            (json.dumps(remaining_crops), player.user_id),
        )
        await self.db.conn.commit()

        msg_lines = [
            "🌾 收获结果",
            "━━━━━━━━━━━━━━━",
        ]

        if herb_counts:
            harvested = "、".join(f"{name}x{count}" for name, count in herb_counts.items())
            msg_lines.append(f"收获：{harvested}")
            msg_lines.append(f"获得修为：{total_exp:,}")
            msg_lines.append(f"获得灵石：{total_gold:,}")
            if stored_items:
                msg_lines.append("📦 存入储物戒：")
                msg_lines.extend(f"  {item}" for item in stored_items)

        if withered_crops:
            withered_counts: Dict[str, int] = {}
            for crop in withered_crops:
                withered_counts[crop["name"]] = withered_counts.get(crop["name"], 0) + 1
            withered_text = "、".join(f"{name}x{count}" for name, count in withered_counts.items())
            msg_lines.append(f"🥀 枯萎清除：{withered_text}")

        msg_lines.append("━━━━━━━━━━━━━━━")
        msg_lines.append(f"剩余种植：{len(remaining_crops)} 株")
        return True, "\n".join(msg_lines)

    async def upgrade_farm(self, player: Player) -> Tuple[bool, str]:
        """升级灵田。"""
        farm = await self.get_user_farm(player.user_id)
        if not farm:
            return False, "❌ 你还没有灵田！"

        current_level = farm["level"]
        if current_level >= 5:
            return False, "❌ 灵田已达最高等级！"

        level_config = FARM_LEVELS.get(current_level, FARM_LEVELS[1])
        cost = level_config["upgrade_cost"]

        if player.gold < cost:
            return False, f"❌ 升级需要 {cost:,} 灵石。"

        player.gold -= cost
        await self.db.update_player(player)

        new_level = current_level + 1
        await self.db.conn.execute(
            "UPDATE spirit_farms SET level = ? WHERE user_id = ?",
            (new_level, player.user_id),
        )
        await self.db.conn.commit()

        new_slots = FARM_LEVELS[new_level]["slots"]
        return True, f"🎉 灵田升级到 Lv.{new_level}！格数增加到 {new_slots}"

    async def get_farm_info(self, user_id: str) -> str:
        """获取灵田信息展示。"""
        farm = await self.get_user_farm(user_id)
        if not farm:
            return (
                "🌾 灵田系统\n"
                "━━━━━━━━━━━━━━━\n"
                "你还没有灵田！\n"
                "开垦费用：10,000 灵石\n\n"
                "📌 使用 /开垦灵田"
            )

        level_config = FARM_LEVELS.get(farm["level"], FARM_LEVELS[1])
        crops = farm["crops"]
        now = int(time.time())

        lines = [
            f"🌾 我的灵田 (Lv.{farm['level']})",
            "━━━━━━━━━━━━━━━",
            f"种植格数：{len(crops)}/{level_config['slots']}",
            "",
        ]

        if not crops:
            lines.append("（空）")
        else:
            lines.append("【种植中】")
            for index, crop in enumerate(crops, 1):
                herb_config = SPIRIT_HERBS.get(crop["name"], SPIRIT_HERBS["灵草"])
                remaining = max(0, crop["mature_time"] - now)
                if remaining > 0:
                    hours = remaining // 3600
                    minutes = (remaining % 3600) // 60
                    status = f"成熟还需 {hours}小时{minutes}分钟"
                else:
                    wither_deadline = crop["mature_time"] + herb_config.get("wither_time", 172800)
                    wither_remaining = wither_deadline - now
                    if wither_remaining <= 0:
                        status = "已枯萎"
                    elif wither_remaining <= 3600:
                        status = f"即将枯萎（{max(1, wither_remaining // 60)} 分钟）"
                    else:
                        status = f"已成熟（约 {wither_remaining // 3600} 小时后枯萎）"
                lines.append(f"  {index}. {crop['name']} - {status}")

        lines.append("")
        lines.append("📌 /种植 <灵草名> [数量/全部]")
        lines.append("📌 /批量种植 <灵草名> <数量>")
        lines.append("📌 /收获")
        return "\n".join(lines)
