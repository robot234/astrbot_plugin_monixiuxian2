# managers/bounty_manager.py
"""悬赏令系统管理器"""
import time
import random
import json
from typing import Tuple, List, Optional, TYPE_CHECKING
from ..data import DataBase
from ..models import Player

if TYPE_CHECKING:
    from ..core import StorageRingManager

__all__ = ["BountyManager"]

# 悬赏任务配置
BOUNTY_TEMPLATES = [
    {"id": 1, "name": "击杀妖兽", "type": "kill", "min_count": 3, "max_count": 10, "base_reward": 500, "cooldown": 3600},
    {"id": 2, "name": "采集灵草", "type": "gather", "min_count": 5, "max_count": 15, "base_reward": 300, "cooldown": 1800},
    {"id": 3, "name": "护送商队", "type": "escort", "min_count": 1, "max_count": 3, "base_reward": 800, "cooldown": 7200},
    {"id": 4, "name": "探索遗迹", "type": "explore", "min_count": 2, "max_count": 5, "base_reward": 600, "cooldown": 5400},
    {"id": 5, "name": "收集灵石", "type": "collect", "min_count": 1000, "max_count": 5000, "base_reward": 200, "cooldown": 900},
]

# 悬赏物品奖励表
BOUNTY_ITEM_REWARDS = {
    "kill": [
        {"name": "灵兽毛皮", "weight": 40, "min": 1, "max": 3},
        {"name": "妖兽精血", "weight": 30, "min": 1, "max": 2},
        {"name": "灵兽内丹", "weight": 20, "min": 1, "max": 1},
        {"name": "玄铁", "weight": 10, "min": 1, "max": 2},
    ],
    "gather": [
        {"name": "灵草", "weight": 50, "min": 2, "max": 5},
        {"name": "精铁", "weight": 30, "min": 1, "max": 3},
        {"name": "灵石碎片", "weight": 20, "min": 3, "max": 8},
    ],
    "escort": [
        {"name": "玄铁", "weight": 35, "min": 2, "max": 4},
        {"name": "星辰石", "weight": 25, "min": 1, "max": 2},
        {"name": "功法残页", "weight": 25, "min": 1, "max": 1},
        {"name": "天材地宝", "weight": 15, "min": 1, "max": 1},
    ],
    "explore": [
        {"name": "灵草", "weight": 30, "min": 2, "max": 4},
        {"name": "玄铁", "weight": 25, "min": 1, "max": 3},
        {"name": "功法残页", "weight": 25, "min": 1, "max": 1},
        {"name": "秘境精华", "weight": 20, "min": 1, "max": 2},
    ],
    "collect": [
        {"name": "灵石碎片", "weight": 50, "min": 5, "max": 10},
        {"name": "精铁", "weight": 30, "min": 2, "max": 4},
        {"name": "灵草", "weight": 20, "min": 1, "max": 3},
    ],
}

class BountyManager:
    """悬赏令管理器"""
    
    def __init__(self, db: DataBase, storage_ring_manager: "StorageRingManager" = None):
        self.db = db
        self.storage_ring_manager = storage_ring_manager
    
    async def get_bounty_list(self, player: Player) -> List[dict]:
        """获取可接取的悬赏任务列表"""
        # 根据玩家境界生成不同难度的任务
        level_multiplier = 1 + (player.level_index // 5) * 0.5
        
        bounties = []
        for template in BOUNTY_TEMPLATES:
            count = random.randint(template["min_count"], template["max_count"])
            reward = int(template["base_reward"] * level_multiplier * (count / template["min_count"]))
            
            bounties.append({
                "id": template["id"],
                "name": template["name"],
                "type": template["type"],
                "count": count,
                "reward": reward,
                "cooldown": template["cooldown"]
            })
        
        return bounties
    
    async def accept_bounty(self, player: Player, bounty_id: int) -> Tuple[bool, str]:
        """接取悬赏任务"""
        # 检查是否已有进行中的任务
        active = await self.db.ext.get_active_bounty(player.user_id)
        if active:
            return False, f"你已有进行中的悬赏：{active['bounty_name']}，请先完成或放弃。"
        
        # 获取任务模板
        template = next((t for t in BOUNTY_TEMPLATES if t["id"] == bounty_id), None)
        if not template:
            return False, "无效的悬赏编号。"
        
        # 生成任务
        level_multiplier = 1 + (player.level_index // 5) * 0.5
        count = random.randint(template["min_count"], template["max_count"])
        reward = int(template["base_reward"] * level_multiplier * (count / template["min_count"]))
        expire_time = int(time.time()) + template["cooldown"]
        
        rewards_json = json.dumps({"stone": reward, "exp": reward * 10})
        
        await self.db.ext.create_bounty(
            player.user_id, bounty_id, template["name"],
            template["type"], count, rewards_json, expire_time
        )
        
        return True, (
            f"🎯 接取悬赏成功！\n"
            f"任务：{template['name']}\n"
            f"目标：完成 {count} 次\n"
            f"奖励：{reward:,} 灵石 + {reward * 10:,} 修为\n"
            f"时限：{template['cooldown'] // 60} 分钟"
        )
    
    async def check_bounty_status(self, player: Player) -> Tuple[bool, str]:
        """查看悬赏任务状态"""
        active = await self.db.ext.get_active_bounty(player.user_id)
        if not active:
            return False, "你当前没有进行中的悬赏任务。\n使用 /悬赏令 查看可接取的任务。"
        
        progress = active["current_progress"]
        target = active["target_count"]
        expire_time = active["expire_time"]
        remaining = max(0, expire_time - int(time.time()))
        
        rewards = json.loads(active["rewards"])
        
        return True, (
            f"📜 当前悬赏\n"
            f"━━━━━━━━━━━━━━━\n"
            f"任务：{active['bounty_name']}\n"
            f"进度：{progress}/{target}\n"
            f"奖励：{rewards.get('stone', 0):,} 灵石 + {rewards.get('exp', 0):,} 修为\n"
            f"剩余时间：{remaining // 60} 分钟\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💡 使用 /完成悬赏 提交任务"
        )
    
    async def complete_bounty(self, player: Player) -> Tuple[bool, str]:
        """完成悬赏任务"""
        active = await self.db.ext.get_active_bounty(player.user_id)
        if not active:
            return False, "你当前没有进行中的悬赏任务。"
        
        # 检查是否超时
        if int(time.time()) > active["expire_time"]:
            await self.db.ext.cancel_bounty(player.user_id)
            return False, "悬赏任务已超时，自动取消。"
        
        # 简化逻辑：直接完成（实际应检查进度）
        # 这里假设玩家通过其他游戏行为已完成进度
        rewards = json.loads(active["rewards"])
        stone_reward = rewards.get("stone", 0)
        exp_reward = rewards.get("exp", 0)
        
        # 物品奖励
        item_msg = ""
        dropped_items = []
        if self.storage_ring_manager:
            bounty_type = active.get("target_type", "gather")
            dropped_items = await self._roll_bounty_items(player, bounty_type)
            if dropped_items:
                item_lines = []
                for item_name, count in dropped_items:
                    success, _ = await self.storage_ring_manager.store_item(player, item_name, count, silent=True)
                    if success:
                        item_lines.append(f"  · {item_name} x{count}")
                    else:
                        item_lines.append(f"  · {item_name} x{count}（储物戒已满，丢失）")
                if item_lines:
                    item_msg = "\n\n📦 获得物品：\n" + "\n".join(item_lines)
        
        # 发放奖励
        player.gold += stone_reward
        player.experience += exp_reward
        await self.db.update_player(player)
        
        # 标记完成
        await self.db.ext.complete_bounty(player.user_id)
        
        return True, (
            f"✅ 悬赏完成！\n"
            f"任务：{active['bounty_name']}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"获得灵石：+{stone_reward:,}\n"
            f"获得修为：+{exp_reward:,}{item_msg}"
        )
    
    async def abandon_bounty(self, player: Player) -> Tuple[bool, str]:
        """放弃悬赏任务"""
        active = await self.db.ext.get_active_bounty(player.user_id)
        if not active:
            return False, "你当前没有进行中的悬赏任务。"
        
        await self.db.ext.cancel_bounty(player.user_id)
        return True, f"已放弃悬赏：{active['bounty_name']}"
    
    async def _roll_bounty_items(self, player: Player, bounty_type: str) -> List[Tuple[str, int]]:
        """
        根据悬赏类型随机掉落物品
        
        Args:
            player: 玩家对象
            bounty_type: 悬赏类型
            
        Returns:
            掉落物品列表 [(物品名, 数量), ...]
        """
        dropped_items = []
        
        # 获取对应类型的掉落表
        drop_table = BOUNTY_ITEM_REWARDS.get(bounty_type, BOUNTY_ITEM_REWARDS["gather"])
        
        # 悬赏完成70%概率获得物品
        if random.randint(1, 100) > 70:
            return dropped_items
        
        # 加权随机选择物品
        total_weight = sum(item["weight"] for item in drop_table)
        roll = random.randint(1, total_weight)
        
        current_weight = 0
        for item in drop_table:
            current_weight += item["weight"]
            if roll <= current_weight:
                count = random.randint(item["min"], item["max"])
                dropped_items.append((item["name"], count))
                break
        
        return dropped_items
