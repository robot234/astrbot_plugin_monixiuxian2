# handlers/combat_handlers.py
import re
import time
from astrbot.api.event import AstrMessageEvent
from astrbot.api.all import *
from astrbot.api import logger

from ..core.battle_manager import BattleManager, CombatStats
from ..core.skill_manager import SkillManager
from ..core.equipment_manager import EquipmentManager
from ..data.data_manager import DataBase
from ..config_manager import ConfigManager
from .utils import player_required
from ..models import Player
from ..models_extended import UserStatus

# 战斗冷却配置（秒）
DUEL_COOLDOWN = 300  # 决斗冷却5分钟
SPAR_COOLDOWN = 60   # 切磋冷却1分钟


class CombatHandlers:
    def __init__(self, db: DataBase, config_manager: ConfigManager):
        self.db = db
        self.config_manager = config_manager
        self.battle_manager = BattleManager(config_manager)
        self.skill_manager = SkillManager(db, config_manager)
        self.equipment_manager = EquipmentManager(db, config_manager)
    
    async def _get_combat_cooldown(self, user_id: str) -> dict:
        """获取战斗冷却信息"""
        try:
            async with self.db.conn.execute(
                "SELECT last_duel_time, last_spar_time FROM combat_cooldowns WHERE user_id = ?",
                (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {"last_duel_time": row[0], "last_spar_time": row[1]}
        except Exception as e:
            logger.warning(f"获取战斗冷却失败: {e}")
        return {"last_duel_time": 0, "last_spar_time": 0}
    
    async def _update_combat_cooldown(self, user_id: str, combat_type: str):
        """更新战斗冷却时间"""
        now = int(time.time())
        try:
            if combat_type == "duel":
                await self.db.conn.execute(
                    """
                    INSERT INTO combat_cooldowns (user_id, last_duel_time, last_spar_time)
                    VALUES (?, ?, 0)
                    ON CONFLICT(user_id) DO UPDATE SET last_duel_time = ?
                    """,
                    (user_id, now, now)
                )
            else:
                await self.db.conn.execute(
                    """
                    INSERT INTO combat_cooldowns (user_id, last_duel_time, last_spar_time)
                    VALUES (?, 0, ?)
                    ON CONFLICT(user_id) DO UPDATE SET last_spar_time = ?
                    """,
                    (user_id, now, now)
                )
            await self.db.conn.commit()
        except Exception as e:
            logger.warning(f"更新战斗冷却失败: {e}")

    async def _get_target_id(self, event: AstrMessageEvent, arg: str) -> str:
        """从消息中提取目标用户ID"""
        message_chain = []
        if hasattr(event, "message_obj") and event.message_obj:
            message_chain = getattr(event.message_obj, "message", []) or []

        for component in message_chain:
            if isinstance(component, At):
                candidate = None
                for attr in ("qq", "target", "uin", "user_id"):
                    candidate = getattr(component, attr, None)
                    if candidate:
                        break
                if candidate:
                    return str(candidate).lstrip("@")

        if arg:
            cleaned = arg.strip().lstrip("@")
            if cleaned.isdigit():
                return cleaned

        message_text = ""
        if hasattr(event, "get_message_str"):
            message_text = event.get_message_str() or ""
        match = re.search(r'(\d{5,})', message_text)
        if match:
            return match.group(1)
        return None

    async def _prepare_combat_stats(self, user_id: str) -> CombatStats:
        """准备战斗属性
        
        使用 BattleManager.prepare_combat_stats 整合所有属性加成
        """
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return None
        
        # 使用 BattleManager 准备战斗属性，传入装备管理器
        combat_stats = self.battle_manager.prepare_combat_stats(
            player=player,
            equipment_manager=self.equipment_manager,
            skill_manager=self.skill_manager
        )
        
        return combat_stats

    async def _restore_mp_after_battle(self, user_id: str):
        """战斗后恢复MP"""
        player = await self.db.get_player_by_id(user_id)
        if player:
            player.mp = player.max_mp
            await self.db.update_player(player)

    async def _apply_duel_damage(self, user_id: str, final_hp: int, max_hp: int):
        """应用决斗伤害到玩家实际HP
        
        决斗模式下，战斗结束后的HP会同步到玩家数据
        """
        player = await self.db.get_player_by_id(user_id)
        if player:
            # 按比例计算实际HP损失
            hp_ratio = final_hp / max_hp if max_hp > 0 else 1.0
            player.hp = max(1, int(player.max_hp * hp_ratio))
            player.mp = player.max_mp  # MP恢复满
            await self.db.update_player(player)

    async def handle_duel(self, event: AstrMessageEvent, target: str):
        """决斗 (消耗气血)"""
        user_id = event.get_sender_id()
        target_id = await self._get_target_id(event, target)
        
        if not target_id:
            yield event.plain_result("❌ 请指定决斗目标\n用法：决斗 @对方 或 决斗 <QQ号>")
            return
            
        if user_id == target_id:
            yield event.plain_result("❌ 不能和自己决斗")
            return

        # 检查发起者是否存在
        player1 = await self.db.get_player_by_id(user_id)
        if not player1:
            yield event.plain_result("❌ 你还未踏入修仙之路，请先使用「我要修仙」开始修炼")
            return

        # 检查目标是否存在
        player2 = await self.db.get_player_by_id(target_id)
        if not player2:
            yield event.plain_result("❌ 对方还未踏入修仙之路")
            return

        # 检查发起者状态
        user_cd = await self.db.ext.get_user_cd(user_id)
        if user_cd and user_cd.type != UserStatus.IDLE:
            current_status = UserStatus.get_name(user_cd.type)
            yield event.plain_result(f"❌ 你当前正在{current_status}，无法进行战斗！")
            return
        
        # 检查目标状态
        target_cd = await self.db.ext.get_user_cd(target_id)
        if target_cd and target_cd.type != UserStatus.IDLE:
            target_status = UserStatus.get_name(target_cd.type)
            yield event.plain_result(f"❌ 对方当前正在{target_status}，无法进行战斗！")
            return

        # 检查HP是否足够
        if player1.hp < player1.max_hp * 0.3:
            yield event.plain_result(f"❌ 你的HP过低（{player1.hp}/{player1.max_hp}），无法发起决斗！\n请先恢复HP后再战")
            return
        
        if player2.hp < player2.max_hp * 0.3:
            yield event.plain_result(f"❌ 对方HP过低，无法进行决斗")
            return

        # 检查冷却
        now = int(time.time())
        cooldown = await self._get_combat_cooldown(user_id)
        last_duel = cooldown.get("last_duel_time", 0)
        if last_duel and (now - last_duel) < DUEL_COOLDOWN:
            remaining = DUEL_COOLDOWN - (now - last_duel)
            yield event.plain_result(f"❌ 决斗冷却中，还需 {remaining // 60} 分 {remaining % 60} 秒")
            return

        # 获取双方战斗属性
        p1_stats = await self._prepare_combat_stats(user_id)
        p2_stats = await self._prepare_combat_stats(target_id)
        
        if not p1_stats or not p2_stats:
            yield event.plain_result("❌ 获取战斗数据失败，请稍后再试")
            return

        # 执行战斗
        result = self.battle_manager.execute_battle(p1_stats, p2_stats, battle_type="duel")
        
        # 应用决斗伤害（决斗模式下HP会实际扣除）
        await self._apply_duel_damage(
            user_id, 
            result["p1_final"]["hp"], 
            result["p1_final"]["max_hp"]
        )
        await self._apply_duel_damage(
            target_id, 
            result["p2_final"]["hp"], 
            result["p2_final"]["max_hp"]
        )
        
        # 更新冷却
        await self._update_combat_cooldown(user_id, "duel")
        
        # 生成战报
        summary = self.battle_manager.generate_battle_summary(result, include_full_log=False)
        
        # 添加决斗特殊信息
        lines = [
            "⚔️ 【决斗】",
            "━━━━━━━━━━━━━━━",
            summary,
            "",
            "━━━━━━━━━━━━━━━",
            "⚠️ 决斗模式：HP已实际扣除",
            "💙 MP已恢复满"
        ]
        
        yield event.plain_result("\n".join(lines))

    async def handle_spar(self, event: AstrMessageEvent, target: str):
        """切磋 (不消耗气血)"""
        user_id = event.get_sender_id()
        target_id = await self._get_target_id(event, target)
        
        if not target_id:
            yield event.plain_result("❌ 请指定切磋目标\n用法：切磋 @对方 或 切磋 <QQ号>")
            return

        if user_id == target_id:
            yield event.plain_result("❌ 不能和自己切磋")
            return

        # 检查发起者是否存在
        player1 = await self.db.get_player_by_id(user_id)
        if not player1:
            yield event.plain_result("❌ 你还未踏入修仙之路，请先使用「我要修仙」开始修炼")
            return

        # 检查目标是否存在
        player2 = await self.db.get_player_by_id(target_id)
        if not player2:
            yield event.plain_result("❌ 对方还未踏入修仙之路")
            return

        # 检查发起者状态
        user_cd = await self.db.ext.get_user_cd(user_id)
        if user_cd and user_cd.type != UserStatus.IDLE:
            current_status = UserStatus.get_name(user_cd.type)
            yield event.plain_result(f"❌ 你当前正在{current_status}，无法进行战斗！")
            return
        
        # 检查目标状态
        target_cd = await self.db.ext.get_user_cd(target_id)
        if target_cd and target_cd.type != UserStatus.IDLE:
            target_status = UserStatus.get_name(target_cd.type)
            yield event.plain_result(f"❌ 对方当前正在{target_status}，无法进行战斗！")
            return

        # 检查冷却
        now = int(time.time())
        cooldown = await self._get_combat_cooldown(user_id)
        last_spar = cooldown.get("last_spar_time", 0)
        if last_spar and (now - last_spar) < SPAR_COOLDOWN:
            remaining = SPAR_COOLDOWN - (now - last_spar)
            yield event.plain_result(f"❌ 切磋冷却中，还需 {remaining} 秒")
            return

        # 获取双方战斗属性
        p1_stats = await self._prepare_combat_stats(user_id)
        p2_stats = await self._prepare_combat_stats(target_id)
        
        if not p1_stats or not p2_stats:
            yield event.plain_result("❌ 获取战斗数据失败，请稍后再试")
            return

        # 执行战斗
        result = self.battle_manager.execute_battle(p1_stats, p2_stats, battle_type="spar")
        
        # 切磋模式下只恢复MP，不扣除HP
        await self._restore_mp_after_battle(user_id)
        await self._restore_mp_after_battle(target_id)
        
        # 更新冷却
        await self._update_combat_cooldown(user_id, "spar")
        
        # 生成战报
        summary = self.battle_manager.generate_battle_summary(result, include_full_log=False)
        
        # 添加切磋特殊信息
        lines = [
            "🤝 【切磋】",
            "━━━━━━━━━━━━━━━",
            summary,
            "",
            "━━━━━━━━━━━━━━━",
            "✨ 切磋模式：HP不会实际扣除",
            "💙 MP已恢复满"
        ]
        
        yield event.plain_result("\n".join(lines))

    async def handle_battle_log(self, event: AstrMessageEvent, target: str):
        """查看详细战斗日志（模拟战斗）"""
        user_id = event.get_sender_id()
        target_id = await self._get_target_id(event, target)
        
        if not target_id:
            yield event.plain_result("❌ 请指定目标\n用法：战斗日志 @对方 或 战斗日志 <QQ号>")
            return

        if user_id == target_id:
            yield event.plain_result("❌ 不能和自己战斗")
            return

        # 检查双方是否存在
        player1 = await self.db.get_player_by_id(user_id)
        player2 = await self.db.get_player_by_id(target_id)
        
        if not player1:
            yield event.plain_result("❌ 你还未踏入修仙之路")
            return
        if not player2:
            yield event.plain_result("❌ 对方还未踏入修仙之路")
            return

        # 获取双方战斗属性
        p1_stats = await self._prepare_combat_stats(user_id)
        p2_stats = await self._prepare_combat_stats(target_id)
        
        if not p1_stats or not p2_stats:
            yield event.plain_result("❌ 获取战斗数据失败")
            return

        # 执行模拟战斗（不影响实际数据）
        result = self.battle_manager.execute_battle(p1_stats, p2_stats, battle_type="spar")
        
        # 生成完整战斗日志
        summary = self.battle_manager.generate_battle_summary(result, include_full_log=True)
        
        lines = [
            "📜 【模拟战斗日志】",
            "━━━━━━━━━━━━━━━",
            "⚠️ 这是模拟战斗，不会影响实际数据",
            "",
            summary
        ]
        
        yield event.plain_result("\n".join(lines))

    async def handle_combat_stats(self, event: AstrMessageEvent):
        """查看自己的战斗属性"""
        user_id = event.get_sender_id()
        
        player = await self.db.get_player_by_id(user_id)
        if not player:
            yield event.plain_result("❌ 你还未踏入修仙之路，请先使用「我要修仙」开始修炼")
            return
        
        # 获取战斗属性
        stats = await self._prepare_combat_stats(user_id)
        if not stats:
            yield event.plain_result("❌ 获取战斗数据失败")
            return
        
        # 获取已装备技能
        equipped_skills = self.skill_manager.get_equipped_skill_configs(player)
        skill_names = [s.get("name", "未知") for s in equipped_skills]
        
        lines = [
            f"⚔️ 【{stats.name}的战斗属性】",
            "━━━━━━━━━━━━━━━",
            "",
            "💖 生命值",
            f"  HP: {player.hp}/{stats.max_hp}",
            f"  MP: {player.mp}/{stats.max_mp}",
            "",
            "⚔️ 攻击属性",
            f"  物理攻击: {stats.physical_attack}",
            f"  法术攻击: {stats.magic_attack}",
            "",
            "🛡️ 防御属性",
            f"  物理防御: {stats.physical_defense}",
            f"  法术防御: {stats.magic_defense}",
            "",
            "⚡ 战斗属性",
            f"  速度: {stats.speed}",
            f"  暴击率: {stats.critical_rate:.1%}",
            f"  暴击伤害: {stats.critical_damage:.1f}x",
            f"  命中率: {stats.hit_rate:.1%}",
            f"  闪避率: {stats.dodge_rate:.1%}",
            "",
            "📚 已装备技能",
            f"  {' | '.join(skill_names) if skill_names else '(无)'}",
            "━━━━━━━━━━━━━━━"
        ]
        
        yield event.plain_result("\n".join(lines))
