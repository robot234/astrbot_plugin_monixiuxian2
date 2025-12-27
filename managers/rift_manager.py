# managers/rift_manager.py
"""
秘境系统管理器 - 处理秘境探索、奖励等逻辑
"""

import random
import time
from typing import Tuple, List, Optional, Dict, TYPE_CHECKING
from ..data.data_manager import DataBase
from ..models_extended import Rift, UserStatus
from ..models import Player

if TYPE_CHECKING:
    from ..core import StorageRingManager


class RiftManager:
    """秘境系统管理器"""
    
    # 默认秘境探索时长（秒）
    DEFAULT_DURATION = 1800
    
    # 秘境物品掉落表（按秘境等级分组）
    RIFT_DROP_TABLE = {
        1: [  # 低级秘境
            {"name": "灵草", "weight": 40, "min": 2, "max": 5},
            {"name": "精铁", "weight": 30, "min": 1, "max": 3},
            {"name": "灵石碎片", "weight": 30, "min": 3, "max": 8},
        ],
        2: [  # 中级秘境
            {"name": "灵草", "weight": 30, "min": 3, "max": 7},
            {"name": "玄铁", "weight": 25, "min": 2, "max": 4},
            {"name": "灵兽毛皮", "weight": 20, "min": 1, "max": 3},
            {"name": "功法残页", "weight": 15, "min": 1, "max": 1},
            {"name": "秘境精华", "weight": 10, "min": 1, "max": 2},
        ],
        3: [  # 高级秘境
            {"name": "玄铁", "weight": 25, "min": 3, "max": 6},
            {"name": "星辰石", "weight": 20, "min": 2, "max": 4},
            {"name": "灵兽内丹", "weight": 20, "min": 1, "max": 2},
            {"name": "功法残页", "weight": 20, "min": 1, "max": 2},
            {"name": "天材地宝", "weight": 15, "min": 1, "max": 1},
        ],
    }
    
    def __init__(self, db: DataBase, config_manager=None, storage_ring_manager: "StorageRingManager" = None):
        self.db = db
        self.config_manager = config_manager
        self.storage_ring_manager = storage_ring_manager
        self.config = config_manager.rift_config if config_manager else {}
        self.explore_duration = self.config.get("default_duration", self.DEFAULT_DURATION)
    
    def _get_level_name(self, level_index: int) -> str:
        """获取境界名称"""
        if self.config_manager and hasattr(self.config_manager, 'level_data'):
            if 0 <= level_index < len(self.config_manager.level_data):
                return self.config_manager.level_data[level_index].get("level_name", f"境界{level_index}")
        # 默认境界名称
        level_names = ["炼气期一层", "炼气期二层", "炼气期三层", "炼气期四层", "炼气期五层",
                       "炼气期六层", "炼气期七层", "炼气期八层", "炼气期九层", "炼气期十层",
                       "筑基期初期", "筑基期中期", "筑基期后期", "金丹期初期", "金丹期中期", "金丹期后期"]
        if 0 <= level_index < len(level_names):
            return level_names[level_index]
        return f"境界{level_index}"
    
    async def list_rifts(self) -> Tuple[bool, str]:
        """
        列出所有秘境
        
        Returns:
            (成功标志, 消息)
        """
        rifts = await self.db.ext.get_all_rifts()
        
        if not rifts:
            return False, "❌ 当前没有开放的秘境！"
        
        msg = "🌀 秘境列表\n"
        msg += "━━━━━━━━━━━━━━━\n"
        
        for rift in rifts:
            rewards_dict = rift.get_rewards()
            exp_range = rewards_dict.get("exp", [0, 0])
            gold_range = rewards_dict.get("gold", [0, 0])
            level_name = self._get_level_name(rift.required_level)
            
            msg += f"【{rift.rift_name}】(ID:{rift.rift_id})\n"
            if rift.required_level == 0:
                msg += f"  等级要求：无限制\n"
            else:
                msg += f"  等级要求：{level_name} 及以上\n"
            msg += f"  修为奖励：{exp_range[0]:,}-{exp_range[1]:,}\n"
            msg += f"  灵石奖励：{gold_range[0]:,}-{gold_range[1]:,}\n\n"
        
        msg += "💡 使用 /探索秘境 <ID> 进入（如：/探索秘境 1）"
        
        return True, msg
    
    async def enter_rift(
        self,
        user_id: str,
        rift_id: int
    ) -> Tuple[bool, str]:
        """
        进入秘境
        
        Args:
            user_id: 用户ID
            rift_id: 秘境ID
            
        Returns:
            (成功标志, 消息)
        """
        # 1. 检查用户
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！"
        
        # 2. 检查用户状态
        user_cd = await self.db.ext.get_user_cd(user_id)
        if not user_cd:
            await self.db.ext.create_user_cd(user_id)
            user_cd = await self.db.ext.get_user_cd(user_id)
        
        if user_cd.type != UserStatus.IDLE:
            return False, f"❌ 你当前正{UserStatus.get_name(user_cd.type)}，无法探索秘境！"
        
        # 3. 检查秘境
        rift = await self.db.ext.get_rift_by_id(rift_id)
        if not rift:
            return False, "❌ 秘境不存在！使用 /秘境列表 查看可用秘境"
        
        # 4. 检查境界要求
        if player.level_index < rift.required_level:
            level_name = self._get_level_name(rift.required_level)
            return False, f"❌ 探索【{rift.rift_name}】需要达到【{level_name}】！"
        
        # 5. 设置探索状态
        scheduled_time = int(time.time()) + self.explore_duration
        await self.db.ext.set_user_busy(user_id, UserStatus.EXPLORING, scheduled_time)
        
        return True, f"✨ 你进入了『{rift.rift_name}』！探索需要 {self.explore_duration//60} 分钟。\n使用 /完成探索 领取奖励"
    
    async def finish_exploration(
        self,
        user_id: str
    ) -> Tuple[bool, str, Optional[Dict]]:
        """
        完成秘境探索
        
        Args:
            user_id: 用户ID
            
        Returns:
            (成功标志, 消息, 奖励数据)
        """
        # 1. 检查用户
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！", None
        
        # 2. 检查CD状态
        user_cd = await self.db.ext.get_user_cd(user_id)
        if not user_cd or user_cd.type != UserStatus.EXPLORING:
            return False, "❌ 你当前不在探索秘境！", None
        
        # 3. 检查时间
        current_time = int(time.time())
        if current_time < user_cd.scheduled_time:
            remaining = user_cd.scheduled_time - current_time
            minutes = remaining // 60
            return False, f"❌ 探索尚未完成！还需要 {minutes} 分钟。", None
        
        # 4. 随机生成奖励（简化版本，实际应该根据秘境配置）
        exp_reward = random.randint(1000, 5000)
        gold_reward = random.randint(500, 2000)
        
        # 随机事件
        events = [
            {"desc": "你发现了一处灵泉，修为大增！", "item_chance": 70},
            {"desc": "你在秘境中击败了一只妖兽！", "item_chance": 80},
            {"desc": "你找到了一个隐藏的宝箱！", "item_chance": 100},
            {"desc": "你领悟了一些修炼心得。", "item_chance": 40},
            {"desc": "你在秘境中遇到了前辈留下的传承！", "item_chance": 90}
        ]
        event = random.choice(events)
        
        # 5. 物品掉落（根据玩家境界确定秘境等级）
        dropped_items = []
        item_msg = ""
        if self.storage_ring_manager:
            rift_level = self._get_rift_level_by_player(player)
            dropped_items = await self._roll_rift_drops(player, rift_level, event["item_chance"])
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
        
        # 6. 应用奖励
        player.experience += exp_reward
        player.gold += gold_reward
        await self.db.update_player(player)
        
        # 7. 清除CD
        await self.db.ext.set_user_free(user_id)
        
        msg = f"""
🌀 探索完成
━━━━━━━━━━━━━━━

{event["desc"]}

获得修为：+{exp_reward}
获得灵石：+{gold_reward}{item_msg}
        """.strip()
        
        reward_data = {
            "exp": exp_reward,
            "gold": gold_reward,
            "event": event["desc"],
            "items": dropped_items
        }
        
        return True, msg, reward_data
    
    async def exit_rift(self, user_id: str) -> Tuple[bool, str]:
        """
        退出秘境（放弃探索）
        
        Args:
            user_id: 用户ID
            
        Returns:
            (成功标志, 消息)
        """
        # 1. 检查用户
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！"
        
        # 2. 检查CD状态
        user_cd = await self.db.ext.get_user_cd(user_id)
        if not user_cd or user_cd.type != UserStatus.EXPLORING:
            return False, "❌ 你当前不在探索秘境！"
        
        # 3. 清除CD状态
        await self.db.ext.set_user_free(user_id)
        
        return True, "✅ 你已退出秘境，本次探索未获得任何奖励。"
    
    def _get_rift_level_by_player(self, player: Player) -> int:
        """根据玩家境界确定秘境等级"""
        level_index = player.level_index
        if level_index <= 5:
            return 1  # 低级秘境
        elif level_index <= 12:
            return 2  # 中级秘境
        else:
            return 3  # 高级秘境
    
    async def _roll_rift_drops(self, player: Player, rift_level: int, item_chance: int) -> List[Tuple[str, int]]:
        """
        根据秘境等级随机掉落物品
        
        Args:
            player: 玩家对象
            rift_level: 秘境等级 (1-3)
            item_chance: 掉落概率
            
        Returns:
            掉落物品列表 [(物品名, 数量), ...]
        """
        dropped_items = []
        
        # 检查是否触发物品掉落
        if random.randint(1, 100) > item_chance:
            return dropped_items
        
        # 获取对应等级的掉落表
        drop_table = self.RIFT_DROP_TABLE.get(rift_level, self.RIFT_DROP_TABLE[1])
        
        # 加权随机选择物品（秘境保证至少掉落1件）
        total_weight = sum(item["weight"] for item in drop_table)
        roll = random.randint(1, total_weight)
        
        current_weight = 0
        for item in drop_table:
            current_weight += item["weight"]
            if roll <= current_weight:
                count = random.randint(item["min"], item["max"])
                dropped_items.append((item["name"], count))
                break
        
        # 高级秘境有50%概率额外掉落一件
        if rift_level >= 2 and random.randint(1, 100) <= 50:
            roll = random.randint(1, total_weight)
            current_weight = 0
            for item in drop_table:
                current_weight += item["weight"]
                if roll <= current_weight:
                    count = random.randint(item["min"], item["max"])
                    dropped_items.append((item["name"], count))
                    break
        
        return dropped_items
