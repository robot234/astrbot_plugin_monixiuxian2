# managers/impart_pk_manager.py
"""传承PK系统管理器"""
import random
from typing import Tuple
from ..data import DataBase
from ..models import Player
from ..core.battle_manager import BattleManager
from ..core.equipment_manager import EquipmentManager
from ..core.skill_manager import SkillManager
from ..config_manager import ConfigManager

__all__ = ["ImpartPkManager"]


class ImpartPkManager:
    """传承PK管理器 - 玩家间争夺传承的战斗"""
    
    def __init__(self, db: DataBase, battle_mgr: BattleManager, config_manager: ConfigManager, 
                 equipment_mgr: EquipmentManager, skill_mgr: SkillManager):
        self.db = db
        self.battle_mgr = battle_mgr
        self.config_manager = config_manager
        self.equipment_mgr = equipment_mgr
        self.skill_mgr = skill_mgr
    
    async def challenge_impart(self, attacker: Player, defender: Player) -> Tuple[bool, str, dict]:
        """发起传承挑战
        
        Args:
            attacker: 挑战者
            defender: 被挑战者
            
        Returns:
            (attacker_wins, battle_log, rewards)
        """
        # 获取双方传承等级
        attacker_impart = await self.db.ext.get_impart_info(attacker.user_id)
        defender_impart = await self.db.ext.get_impart_info(defender.user_id)
        
        # 使用统一的 BattleManager 准备战斗属性
        atk_stats = self.battle_mgr.prepare_combat_stats(
            attacker, self.equipment_mgr, self.skill_mgr
        )
        def_stats = self.battle_mgr.prepare_combat_stats(
            defender, self.equipment_mgr, self.skill_mgr
        )
        
        # 执行战斗
        battle_result = self.battle_mgr.execute_battle(atk_stats, def_stats, battle_type="impart_pk")
        
        # 判定胜负
        attacker_wins = battle_result.get("winner") == "p1"
        
        # 生成战斗摘要
        battle_log = self.battle_mgr.generate_battle_summary(battle_result, include_full_log=False)
        
        rewards = {}
        if attacker_wins:
            # 胜利奖励：获得传承加成
            impart_gain = random.uniform(0.01, 0.05)  # 1%-5%
            if attacker_impart:
                new_atk_per = min(1.0, attacker_impart.impart_atk_per + impart_gain)
                attacker_impart.impart_atk_per = new_atk_per
                await self.db.ext.update_impart_info(attacker_impart)
                rewards["impart_atk_gain"] = impart_gain
            
            # 失败惩罚
            if defender_impart and defender_impart.impart_atk_per > 0:
                loss = min(impart_gain / 2, defender_impart.impart_atk_per)
                defender_impart.impart_atk_per -= loss
                await self.db.ext.update_impart_info(defender_impart)
                rewards["defender_loss"] = loss
        else:
            # 失败惩罚：损失修为
            exp_loss = int(attacker.experience * 0.01)  # 1%
            attacker.experience = max(0, attacker.experience - exp_loss)
            await self.db.update_player(attacker)
            rewards["exp_loss"] = exp_loss
        
        return attacker_wins, battle_log, rewards
    
    async def get_impart_ranking(self, limit: int = 10) -> list:
        """获取传承排行榜"""
        # 查询所有传承数据，按攻击加成排序
        async with self.db.conn.execute(
            """
            SELECT user_id, impart_hp_per, impart_mp_per, impart_atk_per, 
                   impart_know_per, impart_burst_per
            FROM impart_info 
            ORDER BY impart_atk_per DESC 
            LIMIT ?
            """,
            (limit,)
        ) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                user_id = row[0]
                player = await self.db.get_player_by_id(user_id)
                if player:
                    total_per = row[1] + row[2] + row[3] + row[4] + row[5]
                    results.append({
                        "user_id": user_id,
                        "user_name": player.user_name or user_id[:8],
                        "atk_per": row[3],
                        "total_per": total_per
                    })
            return results
