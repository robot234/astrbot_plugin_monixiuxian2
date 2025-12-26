# managers/adventure_manager.py
"""
历练系统管理器 - 处理历练任务、奇遇等逻辑
参照NoneBot2插件的xiuxian_work实现
"""

import random
import time
from typing import Tuple, Dict, Optional
from ..data.data_manager import DataBase
from ..models import Player
from ..models_extended import UserStatus


class AdventureManager:
    """历练系统管理器"""
    
    # 历练时长配置（秒）
    ADVENTURE_DURATIONS = {
        "short": 1800,    # 30分钟
        "medium": 3600,   # 1小时
        "long": 7200,     # 2小时
    }
    
    # 历练事件池
    ADVENTURE_EVENTS = {
        "good": [
            {"type": "exp", "desc": "你在历练中有所感悟，修为大增！", "exp_mult": 1.5, "gold_mult": 1.0},
            {"type": "treasure", "desc": "你发现了一处秘宝！", "exp_mult": 1.0, "gold_mult": 2.0},
            {"type": "breakthrough", "desc": "你在生死之间突破瓶颈！", "exp_mult": 2.0, "gold_mult": 1.0},
            {"type": "inheritance", "desc": "你遇到了前辈的传承！", "exp_mult": 1.8, "gold_mult": 1.5},
            {"type": "spirit_herb", "desc": "你采集到了珍贵的灵药！", "exp_mult": 1.2, "gold_mult": 1.8},
        ],
        "normal": [
            {"type": "normal", "desc": "历练顺利，你获得了一些修为。", "exp_mult": 1.0, "gold_mult": 1.0},
            {"type": "fight", "desc": "你击败了拦路的妖兽。", "exp_mult": 1.1, "gold_mult": 1.1},
            {"type": "explore", "desc": "你探索了一片陌生的区域。", "exp_mult": 1.0, "gold_mult": 1.2},
        ],
        "bad": [
            {"type": "ambush", "desc": "你遭遇了埋伏，受了点伤。", "exp_mult": 0.8, "gold_mult": 0.8},
            {"type": "lost", "desc": "你在路上迷失了方向，浪费了一些时间。", "exp_mult": 0.7, "gold_mult": 1.0},
            {"type": "robbed", "desc": "你遇到了劫匪，损失了一些灵石。", "exp_mult": 1.0, "gold_mult": 0.5},
        ]
    }
    
    def __init__(self, db: DataBase):
        self.db = db
    
    async def start_adventure(
        self,
        user_id: str,
        adventure_type: str = "medium"
    ) -> Tuple[bool, str]:
        """
        开始历练
        
        Args:
            user_id: 用户ID
            adventure_type: 历练类型（short/medium/long）
            
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
            current_status = UserStatus.get_name(user_cd.type)
            return False, f"❌ 你当前正{current_status}，无法开始历练！"
        
        # 3. 验证历练类型
        if adventure_type not in self.ADVENTURE_DURATIONS:
            adventure_type = "medium"
        
        duration = self.ADVENTURE_DURATIONS[adventure_type]
        duration_minutes = duration // 60
        
        # 4. 设置历练状态
        scheduled_time = int(time.time()) + duration
        await self.db.ext.set_user_busy(user_id, UserStatus.ADVENTURING, scheduled_time)
        
        type_names = {"short": "短途", "medium": "中途", "long": "长途"}
        type_name = type_names.get(adventure_type, "中途")
        
        return True, f"✨ 你开始了{type_name}历练！预计需要 {duration_minutes} 分钟。\n小心路上的危险！"
    
    async def finish_adventure(self, user_id: str) -> Tuple[bool, str, Optional[Dict]]:
        """
        完成历练
        
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
        if not user_cd or user_cd.type != UserStatus.ADVENTURING:
            return False, "❌ 你当前不在历练中！", None
        
        # 3. 检查时间
        current_time = int(time.time())
        if current_time < user_cd.scheduled_time:
            remaining = user_cd.scheduled_time - current_time
            minutes = remaining // 60
            seconds = remaining % 60
            return False, f"❌ 历练尚未完成！还需要 {minutes}分{seconds}秒。", None
        
        # 4. 计算历练时长（用于奖励计算）
        adventure_duration = current_time - user_cd.create_time
        
        # 5. 随机事件
        event = self._trigger_random_event()
        
        # 6. 计算基础奖励（时长基础 + 修为加成）
        # 基础奖励：每分钟固定获得一些修为和灵石
        duration_minutes = adventure_duration / 60
        base_exp_per_min = 50  # 每分钟基础50修为
        base_gold_per_min = 10  # 每分钟基础10灵石
        
        # 额外加成：根据玩家当前修为额外奖励
        bonus_exp = int(player.experience * 0.03 * (adventure_duration / 3600))  # 每小时3%修为
        bonus_gold = int(player.experience * 0.01 * (adventure_duration / 3600))  # 每小时1%修为转换为灵石
        
        base_exp = int(duration_minutes * base_exp_per_min) + bonus_exp
        base_gold = int(duration_minutes * base_gold_per_min) + bonus_gold
        
        # 7. 应用事件倍数
        final_exp = int(base_exp * event["exp_mult"])
        final_gold = int(base_gold * event["gold_mult"])
        
        # 8. 应用奖励
        player.experience += final_exp
        player.gold += final_gold
        await self.db.update_player(player)
        
        # 9. 清除CD
        await self.db.ext.set_user_free(user_id)
        
        # 10. 构建消息
        msg = f"""
╔══════════════════════╗
║    历练归来    ║
╚══════════════════════╝

{event["desc"]}

历练时长：{adventure_duration // 60}分钟
获得修为：+{final_exp:,}
获得灵石：+{final_gold:,}

当前修为：{player.experience:,}
当前灵石：{player.gold:,}
        """.strip()
        
        reward_data = {
            "event_type": event["type"],
            "event_desc": event["desc"],
            "exp_reward": final_exp,
            "gold_reward": final_gold,
            "duration": adventure_duration
        }
        
        return True, msg, reward_data
    
    async def check_adventure_status(self, user_id: str) -> Tuple[bool, str]:
        """
        查看历练状态
        
        Args:
            user_id: 用户ID
            
        Returns:
            (成功标志, 消息)
        """
        user_cd = await self.db.ext.get_user_cd(user_id)
        if not user_cd or user_cd.type != UserStatus.ADVENTURING:
            return False, "❌ 你当前不在历练中！"
        
        current_time = int(time.time())
        if current_time >= user_cd.scheduled_time:
            return True, "✅ 历练已完成！使用 /完成历练 领取奖励。"
        
        remaining = user_cd.scheduled_time - current_time
        minutes = remaining // 60
        seconds = remaining % 60
        
        elapsed = current_time - user_cd.create_time
        elapsed_minutes = elapsed // 60
        
        msg = f"""
📍 历练进度

已历练：{elapsed_minutes}分钟
剩余时间：{minutes}分{seconds}秒

请耐心等待历练完成...
        """.strip()
        
        return True, msg
    
    def _trigger_random_event(self) -> Dict:
        """
        触发随机事件
        
        Returns:
            事件数据
        """
        # 事件概率：好事30%，普通事件50%，坏事20%
        roll = random.randint(1, 100)
        
        if roll <= 30:
            # 好事
            return random.choice(self.ADVENTURE_EVENTS["good"])
        elif roll <= 80:
            # 普通事件
            return random.choice(self.ADVENTURE_EVENTS["normal"])
        else:
            # 坏事
            return random.choice(self.ADVENTURE_EVENTS["bad"])
