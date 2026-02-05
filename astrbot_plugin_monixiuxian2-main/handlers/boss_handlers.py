# handlers/boss_handlers.py
from typing import Tuple, Optional, Dict, Any
from astrbot.api.event import AstrMessageEvent
from ..managers.boss_manager import BossManager
from ..data.data_manager import DataBase

class BossHandlers:
    def __init__(self, db: DataBase, boss_mgr: BossManager):
        self.db = db
        self.boss_mgr = boss_mgr

    async def handle_boss_info(self, event: AstrMessageEvent):
        """查询世界Boss"""
        success, msg, _ = await self.boss_mgr.get_boss_info()
        yield event.plain_result(msg)

    async def handle_boss_fight(self, user_id: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        挑战世界Boss
        
        Args:
            user_id: 用户ID
            
        Returns:
            (成功标志, 消息, 战斗结果字典)
            战斗结果字典包含:
            - winner: 胜利者ID
            - loser: 失败者ID
            - is_draw: 是否平局
            - log: 战斗日志
            - rounds: 回合数
            - p1_final: 玩家最终状态
            - p2_final: Boss最终状态
            - reward: 获得的灵石奖励（仅胜利时）
        """
        success, msg, battle_result = await self.boss_mgr.challenge_boss(user_id)
        return success, msg, battle_result
    
    async def handle_spawn_boss(self) -> Tuple[bool, str, Optional[Any]]:
        """
        生成世界Boss
        
        Returns:
            (成功标志, 消息, Boss对象)
        """
        success, msg, boss = await self.boss_mgr.auto_spawn_boss()
        return success, msg, boss
