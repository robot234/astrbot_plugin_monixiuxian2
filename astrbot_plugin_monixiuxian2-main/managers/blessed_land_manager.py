# managers/blessed_land_manager.py
"""洞天福地系统管理器"""
import time
import json
from typing import Tuple, Optional, Dict
from ..data import DataBase
from ..models import Player

__all__ = ["BlessedLandManager"]

# 洞天配置
BLESSED_LANDS = {
    1: {"name": "小洞天", "price": 10000, "exp_bonus": 0.05, "gold_per_hour": 100, "max_level": 5, "max_exp_per_hour": 5000},
    2: {"name": "中洞天", "price": 30000, "exp_bonus": 0.10, "gold_per_hour": 500, "max_level": 10, "max_exp_per_hour": 15000},
    3: {"name": "大洞天", "price": 80000, "exp_bonus": 0.20, "gold_per_hour": 2000, "max_level": 15, "max_exp_per_hour": 30000},
    4: {"name": "福地", "price": 200000, "exp_bonus": 0.30, "gold_per_hour": 5000, "max_level": 20, "max_exp_per_hour": 50000},
    5: {"name": "洞天福地", "price": 500000, "exp_bonus": 0.50, "gold_per_hour": 10000, "max_level": 30, "max_exp_per_hour": 100000},
}


class BlessedLandManager:
    """洞天福地管理器"""
    
    def __init__(self, db: DataBase):
        self.db = db
    
    async def get_user_blessed_land(self, user_id: str) -> Optional[Dict]:
        """获取用户洞天信息"""
        async with self.db.conn.execute(
            "SELECT * FROM blessed_lands WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return None
    
    async def purchase_blessed_land(self, player: Player, land_type: int) -> Tuple[bool, str]:
        """购买洞天"""
        # 限制只能购买小洞天
        if land_type != 1:
            return False, "❌ 初始只能购买小洞天，通过进阶系统提升洞天品质。"
        
        if land_type not in BLESSED_LANDS:
            return False, "❌ 无效的洞天类型。"
        
        # 检查是否已有洞天
        existing = await self.get_user_blessed_land(player.user_id)
        if existing:
            return False, f"❌ 你已拥有【{existing['land_name']}】，请先升级而非重新购买。"
        
        land_config = BLESSED_LANDS[land_type]
        price = land_config["price"]
        
        if player.gold < price:
            return False, f"❌ 灵石不足！购买{land_config['name']}需要 {price:,} 灵石。"
        
        # 扣除灵石
        player.gold -= price
        await self.db.update_player(player)
        
        # 创建洞天
        await self.db.conn.execute(
            """
            INSERT INTO blessed_lands (user_id, land_type, land_name, level, exp_bonus, 
                                       gold_per_hour, last_collect_time)
            VALUES (?, ?, ?, 1, ?, ?, ?)
            """,
            (player.user_id, land_type, land_config["name"], land_config["exp_bonus"],
             land_config["gold_per_hour"], int(time.time()))
        )
        await self.db.conn.commit()
        
        return True, (
            f"✨ 恭喜获得【{land_config['name']}】！\n"
            f"━━━━━━━━━━━━━━━\n"
            f"修炼加成：+{land_config['exp_bonus']:.0%}\n"
            f"每小时产出：{land_config['gold_per_hour']} 灵石\n"
            f"━━━━━━━━━━━━━━━\n"
            f"使用 /洞天收取 领取产出\n"
            f"💡 当小洞天达到5级时，可使用 /进阶洞天 2 提升到中洞天"
        )
    
    async def upgrade_blessed_land(self, player: Player) -> Tuple[bool, str]:
        """升级洞天"""
        land = await self.get_user_blessed_land(player.user_id)
        if not land:
            return False, "❌ 你还没有洞天！使用 /购买洞天 <类型> 获取。"
        
        land_type = land["land_type"]
        current_level = land["level"]
        config = BLESSED_LANDS.get(land_type, BLESSED_LANDS[1])
        
        if current_level >= config["max_level"]:
            return False, f"❌ 你的{land['land_name']}已达最高等级 {config['max_level']}！"
        
        # 升级费用：使用固定每级费用，更线性增长
        # 小洞天：每级 1000，中洞天：每级 2000，大洞天：每级 3000，福地：每级 4000，洞天福地：每级 3000
        level_cost_map = {
            1: 1000,  # 小洞天
            2: 2000,  # 中洞天
            3: 3000,  # 大洞天
            4: 5000,  # 福地
            5: 10000   # 洞天福地
        }
        upgrade_cost = level_cost_map.get(land_type, 1000)
        
        if player.gold < upgrade_cost:
            return False, f"❌ 灵石不足！升级需要 {upgrade_cost:,} 灵石。"
        
        # 升级加成
        new_level = current_level + 1
        new_exp_bonus = config["exp_bonus"] * (1 + new_level * 0.1)
        new_gold_per_hour = int(config["gold_per_hour"] * (1 + new_level * 0.15))
        
        player.gold -= upgrade_cost
        await self.db.update_player(player)
        
        await self.db.conn.execute(
            """
            UPDATE blessed_lands SET level = ?, exp_bonus = ?, gold_per_hour = ?
            WHERE user_id = ?
            """,
            (new_level, new_exp_bonus, new_gold_per_hour, player.user_id)
        )
        await self.db.conn.commit()
        
        return True, (
            f"🎉 {land['land_name']}升级到 Lv.{new_level}！\n"
            f"━━━━━━━━━━━━━━━\n"
            f"修炼加成：+{new_exp_bonus:.1%}\n"
            f"每小时产出：{new_gold_per_hour} 灵石\n"
            f"花费：{upgrade_cost:,} 灵石"
        )
    
    async def collect_income(self, player: Player) -> Tuple[bool, str]:
        """收取洞天产出"""
        land = await self.get_user_blessed_land(player.user_id)
        if not land:
            return False, "❌ 你还没有洞天！"
        
        last_collect = land["last_collect_time"]
        now = int(time.time())
        hours_passed = (now - last_collect) / 3600
        
        if hours_passed < 1:
            remaining = int(3600 - (now - last_collect))
            minutes = remaining // 60
            return False, f"❌ 收取冷却中，还需 {minutes} 分钟。"
        
        # 计算产出（最多24小时）
        hours = min(24, int(hours_passed))
        gold_income = land["gold_per_hour"] * hours
        
        # 计算修为收益，并限制上限防止高修为玩家收益无限增长
        land_type = land["land_type"]
        config = BLESSED_LANDS.get(land_type, BLESSED_LANDS[1])
        max_exp_per_hour = config.get("max_exp_per_hour", 5000)
        exp_income = int(player.experience * land["exp_bonus"] * hours * 0.01)
        exp_income = min(exp_income, max_exp_per_hour * hours)
        
        player.gold += gold_income
        player.experience += exp_income
        await self.db.update_player(player)
        
        await self.db.conn.execute(
            "UPDATE blessed_lands SET last_collect_time = ? WHERE user_id = ?",
            (now, player.user_id)
        )
        await self.db.conn.commit()
        
        return True, (
            f"✅ 洞天收取成功！\n"
            f"━━━━━━━━━━━━━━━\n"
            f"累计时长：{hours} 小时\n"
            f"获得灵石：+{gold_income:,}\n"
            f"获得修为：+{exp_income:,}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"当前灵石：{player.gold:,}"
        )
    
    async def advance_blessed_land(self, player: Player, target_type: int) -> Tuple[bool, str]:
        """进阶洞天"""
        # 检查是否有洞天
        existing = await self.get_user_blessed_land(player.user_id)
        if not existing:
            return False, "❌ 你还没有洞天！"
        
        # 检查目标类型是否有效
        if target_type not in BLESSED_LANDS:
            return False, "❌ 无效的洞天类型。"
        
        # 检查是否是下一级类型（只能层层进阶）
        current_type = existing["land_type"]
        if target_type != current_type + 1:
            next_type = current_type + 1
            if next_type in BLESSED_LANDS:
                next_name = BLESSED_LANDS[next_type]["name"]
                return False, f"❌ 只能层层进阶！当前只能进阶到{next_name}。"
            else:
                return False, "❌ 你的洞天已达最高等级，无法继续进阶。"
        
        # 检查现有洞天是否满级
        current_config = BLESSED_LANDS[current_type]
        if existing["level"] < current_config["max_level"]:
            return False, f"❌ 你的{existing['land_name']}需要达到满级 {current_config['max_level']} 才能进阶。"
        
        # 计算进阶成本（新洞天价格 × 0.3）
        target_config = BLESSED_LANDS[target_type]
        advance_cost = int(target_config["price"])
        
        if player.gold < advance_cost:
            return False, f"❌ 灵石不足！进阶需要 {advance_cost:,} 灵石。"
        
        # 扣除灵石
        player.gold -= advance_cost
        await self.db.update_player(player)
        
        # 取消等级保留，每次进阶后从1级开始
        initial_level = 1
        
        # 删除原洞天，创建新洞天
        await self.db.conn.execute(
            "DELETE FROM blessed_lands WHERE user_id = ?",
            (player.user_id,)
        )
        await self.db.conn.execute(
            """
            INSERT INTO blessed_lands (user_id, land_type, land_name, level, exp_bonus, 
                                       gold_per_hour, last_collect_time)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (player.user_id, target_type, target_config["name"], initial_level, 
             target_config["exp_bonus"], target_config["gold_per_hour"], int(time.time()))
        )
        await self.db.conn.commit()
        
        return True, (
            f"✨ 恭喜进阶到【{target_config['name']}】！\n"
            f"━━━━━━━━━━━━━━━\n"
            f"初始等级：Lv.{initial_level}\n"
            f"修炼加成：+{target_config['exp_bonus']:.0%}\n"
            f"每小时产出：{target_config['gold_per_hour']} 灵石\n"
            f"━━━━━━━━━━━━━━━\n"
            f"花费：{advance_cost:,} 灵石"
        )
    
    async def get_blessed_land_info(self, user_id: str) -> str:
        """获取洞天信息展示"""
        land = await self.get_user_blessed_land(user_id)
        if not land:
            return (
                "🏔️ 洞天福地\n"
                "━━━━━━━━━━━━━━━\n"
                "你还没有洞天！\n\n"
                "可购买的洞天：\n"
                "  1. 小洞天 - 10,000灵石\n"
                "  2. 中洞天 - 50,000灵石\n"
                "  3. 大洞天 - 200,000灵石\n"
                "  4. 福地 - 500,000灵石\n"
                "  5. 洞天福地 - 1,000,000灵石\n\n"
                "💡 使用 /购买洞天 <编号>"
            )
        
        now = int(time.time())
        hours_since = (now - land["last_collect_time"]) / 3600
        pending_gold = int(min(24, hours_since) * land["gold_per_hour"])
        
        # 检查是否可以进阶
        current_config = BLESSED_LANDS[land["land_type"]]
        can_advance = land["level"] >= current_config["max_level"] and land["land_type"] < 5
        advance_hint = "\n💡 已达满级，可使用 /进阶洞天 <类型> 提升洞天品质" if can_advance else ""
        
        return (
            f"🏔️ {land['land_name']} (Lv.{land['level']})\n"
            f"━━━━━━━━━━━━━━━\n"
            f"修炼加成：+{land['exp_bonus']:.1%}\n"
            f"每小时产出：{land['gold_per_hour']} 灵石\n"
            f"━━━━━━━━━━━━━━━\n"
            f"待收取：约 {pending_gold:,} 灵石\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💡 /升级洞天 | /洞天收取{advance_hint}"
        )
