"""
奇遇事件管理器 - 复杂版本
支持：机缘、传承、挑战、抉择、连续剧情
"""
import random
import time
import json
from typing import Optional, Tuple, List, Dict, Any
from dataclasses import dataclass, field
from ..data import DataBase
from ..models import Player


@dataclass
class ActiveEvent:
    """进行中的奇遇事件"""
    event_id: str
    event_type: str
    player_id: str
    started_at: int
    current_stage: int = 1
    choices_made: List[str] = field(default_factory=list)
    pending_choice: bool = False
    battle_pending: bool = False
    event_data: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "player_id": self.player_id,
            "started_at": self.started_at,
            "current_stage": self.current_stage,
            "choices_made": self.choices_made,
            "pending_choice": self.pending_choice,
            "battle_pending": self.battle_pending,
            "event_data": self.event_data
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "ActiveEvent":
        return cls(
            event_id=data["event_id"],
            event_type=data["event_type"],
            player_id=data["player_id"],
            started_at=data["started_at"],
            current_stage=data.get("current_stage", 1),
            choices_made=data.get("choices_made", []),
            pending_choice=data.get("pending_choice", False),
            battle_pending=data.get("battle_pending", False),
            event_data=data.get("event_data", {})
        )


class AdventureEventManager:
    """奇遇事件管理器"""
    
    def __init__(self, db: DataBase, config_manager, storage_ring_manager=None, 
                 battle_manager=None, equipment_manager=None, skill_manager=None):
        self.db = db
        self.config_manager = config_manager
        self.storage_ring_mgr = storage_ring_manager
        self.battle_mgr = battle_manager
        self.equipment_mgr = equipment_manager
        self.skill_mgr = skill_manager
        
        self.events_config = self.config_manager.get_adventure_events_config()
        self.active_events: Dict[str, ActiveEvent] = {}
        self.EVENT_STORAGE_PREFIX = "active_adventure_event_"

    def _event_storage_key(self, player_id: str) -> str:
        return f"{self.EVENT_STORAGE_PREFIX}{player_id}"

    async def _load_active_event(self, player_id: str) -> Optional[ActiveEvent]:
        if player_id in self.active_events:
            return self.active_events[player_id]

        raw = await self.db.ext.get_system_config(self._event_storage_key(player_id))
        if not raw:
            return None

        try:
            active_event = ActiveEvent.from_dict(json.loads(raw))
        except Exception:
            await self.db.ext.set_system_config(self._event_storage_key(player_id), "")
            return None

        self.active_events[player_id] = active_event
        return active_event

    async def _save_active_event(self, active_event: ActiveEvent):
        self.active_events[active_event.player_id] = active_event
        await self.db.ext.set_system_config(
            self._event_storage_key(active_event.player_id),
            json.dumps(active_event.to_dict(), ensure_ascii=False)
        )

    async def _clear_active_event(self, player_id: str):
        self.active_events.pop(player_id, None)
        await self.db.ext.set_system_config(self._event_storage_key(player_id), "")
    
    async def try_trigger_event(self, player: Player, trigger_type: str, 
                                 context: dict = None) -> Tuple[bool, str, Optional[dict]]:
        """
        尝试触发奇遇事件
        
        Args:
            player: 玩家对象
            trigger_type: 触发类型 (cultivation_end, adventure_complete, rift_complete, check_in, wander)
            context: 上下文信息（如历练时长、路线等）
            
        Returns:
            (是否触发, 消息, 事件数据)
        """
        context = context or {}
        
        if await self._load_active_event(player.user_id):
            return False, "", None
        
        if trigger_type == "wander":
            cooldown_key = f"adventure_event_cd_{player.user_id}"
            last_wander = await self.db.ext.get_system_config(cooldown_key)
            if last_wander:
                cooldown = self.events_config.get("trigger_settings", {}).get("wander", {}).get("cooldown_minutes", 60) * 60
                if int(time.time()) - int(last_wander) < cooldown:
                    remaining = cooldown - (int(time.time()) - int(last_wander))
                    return False, f"❌ 游历冷却中，还需等待 {remaining // 60} 分钟", None
        
        trigger_chance = self._calculate_trigger_chance(trigger_type, context)
        
        if random.random() > trigger_chance:
            return False, "", None
        
        event = self._select_event(player)
        if not event:
            return False, "", None
        
        if trigger_type == "wander":
            await self.db.ext.set_system_config(f"adventure_event_cd_{player.user_id}", str(int(time.time())))
        
        active_event = ActiveEvent(
            event_id=event["id"],
            event_type=event["type"],
            player_id=player.user_id,
            started_at=int(time.time()),
            event_data=event
        )
        
        return await self._process_event_start(player, active_event, event)
    
    def _calculate_trigger_chance(self, trigger_type: str, context: dict) -> float:
        """计算触发概率"""
        settings = self.events_config.get("trigger_settings", {}).get(trigger_type, {})
        base_chance = settings.get("base_chance", 0.1)
        
        if trigger_type == "cultivation_end":
            duration = context.get("duration_minutes", 0)
            min_duration = settings.get("min_duration_minutes", 30)
            if duration < min_duration:
                return 0
            hours = duration / 60
            bonus = hours * settings.get("chance_per_hour", 0.02)
            return min(base_chance + bonus, 0.5)
        
        elif trigger_type == "adventure_complete":
            route = context.get("route", "")
            route_bonus = settings.get("route_bonus", {}).get(route, 0)
            return base_chance + route_bonus
        
        return base_chance
    
    def _select_event(self, player: Player) -> Optional[dict]:
        """根据玩家状态选择一个奇遇事件"""
        events = self.events_config.get("events", {})
        rarity_weights = self.events_config.get("rarity_weights", {
            "common": 100, "rare": 30, "epic": 8, "legendary": 2
        })
        
        eligible_events = []
        for event_id, event in events.items():
            event_copy = event.copy()
            
            if "id" not in event_copy:
                event_copy["id"] = event_id
                
            if player.level_index < event_copy.get("min_level", 0):
                continue
            if player.level_index > event_copy.get("max_level", 999):
                continue
            
            if "cultivation_type" in event_copy:
                if player.cultivation_type != event_copy["cultivation_type"]:
                    continue
            
            prerequisites = event_copy.get("prerequisites", [])
            if prerequisites:
                pass
            
            rarity = event_copy.get("rarity", "common")
            base_weight = event_copy.get("weight", 50)
            rarity_modifier = rarity_weights.get(rarity, 50) / 100
            final_weight = base_weight * rarity_modifier
            
            eligible_events.append((event_copy, final_weight))
        
        if not eligible_events:
            return None
        
        total_weight = sum(w for _, w in eligible_events)
        if total_weight <= 0:
            return None
            
        roll = random.random() * total_weight
        
        current = 0
        for event, weight in eligible_events:
            current += weight
            if roll <= current:
                return event
        
        return eligible_events[-1][0] if eligible_events else None
    
    async def _process_event_start(self, player: Player, active_event: ActiveEvent, 
                                    event: dict) -> Tuple[bool, str, Optional[dict]]:
        """处理事件开始"""
        event_type = event["type"]
        
        msg = self._build_event_intro(event)
        
        if event_type == "fortune":
            rewards_msg, rewards_data = await self._apply_rewards(player, event.get("rewards", {}))
            if rewards_msg:
                msg += f"\n\n{rewards_msg}"
            if event.get("flavor_text"):
                msg += f"\n\n💭 {event['flavor_text']}"
            await self.db.update_player(player)
            return True, msg, {"type": "fortune", "rewards": rewards_data}
        
        elif event_type == "inheritance":
            rewards_msg, rewards_data = await self._apply_rewards(player, event.get("rewards", {}))
            if rewards_msg:
                msg += f"\n\n{rewards_msg}"
            if event.get("flavor_text"):
                msg += f"\n\n💭 {event['flavor_text']}"
            await self.db.update_player(player)
            return True, msg, {"type": "inheritance", "rewards": rewards_data}
        
        elif event_type == "challenge":
            active_event.battle_pending = True
            await self._save_active_event(active_event)
            
            battle_info = event.get("battle", {})
            msg += f"\n\n⚔️ 即将与【{battle_info.get('enemy_name', '未知敌人')}】战斗！"
            msg += f"\n💡 发送「奇遇战斗」开始战斗，或「放弃奇遇」逃跑"
            
            return True, msg, {"type": "challenge", "pending": True}
        
        elif event_type == "choice":
            active_event.pending_choice = True
            await self._save_active_event(active_event)
            
            choices = event.get("choices", [])
            msg += "\n\n请选择你的行动："
            for i, choice in enumerate(choices, 1):
                cost_str = ""
                if choice.get("cost", {}).get("gold"):
                    cost_str = f"（需要 {choice['cost']['gold']} 灵石）"
                msg += f"\n{i}. {choice['text']}{cost_str}"
            
            msg += f"\n\n💡 发送「奇遇选择 <编号>」进行选择"
            
            return True, msg, {"type": "choice", "pending": True, "choices": len(choices)}
        
        elif event_type == "story":
            active_event.pending_choice = True
            await self._save_active_event(active_event)
            
            stages = event.get("stages", [])
            if stages:
                first_stage = stages[0]
                msg += f"\n\n{first_stage.get('text', '')}"
                
                if first_stage.get("npc"):
                    npc = first_stage["npc"]
                    msg += f"\n\n👤 {npc['name']}：「{npc['dialogue']}」"
                
                choices = first_stage.get("choices", [])
                if choices:
                    msg += "\n\n请选择你的行动："
                    for i, choice in enumerate(choices, 1):
                        msg += f"\n{i}. {choice['text']}"
                    msg += f"\n\n💡 发送「奇遇选择 <编号>」进行选择"
            
            return True, msg, {"type": "story", "pending": True}
        
        return False, "", None
    
    def _build_event_intro(self, event: dict) -> str:
        """构建事件开场白"""
        rarity_icons = {
            "common": "✨",
            "rare": "💫",
            "epic": "🌟",
            "legendary": "⭐"
        }
        rarity = event.get("rarity", "common")
        rarity_names = {
            "common": "普通",
            "rare": "稀有",
            "epic": "史诗",
            "legendary": "传说"
        }
        
        icon = rarity_icons.get(rarity, "✨")
        rarity_name = rarity_names.get(rarity, "普通")
        
        msg = (
            f"{icon} 【{rarity_name}奇遇】{event['name']}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"{event.get('description', '')}"
        )
        
        if event.get("npc"):
            npc = event["npc"]
            msg += f"\n\n👤 {npc['name']}：「{npc['dialogue']}」"
        
        return msg
    
    async def handle_choice(self, player: Player, choice_index: int) -> Tuple[bool, str]:
        """处理玩家的选择"""
        active_event = await self._load_active_event(player.user_id)
        if not active_event:
            return False, "❌ 你当前没有进行中的奇遇事件"
        if not active_event.pending_choice:
            return False, "❌ 当前奇遇不需要选择"
        
        event = active_event.event_data
        
        if event["type"] == "choice":
            return await self._handle_choice_event(player, active_event, choice_index)
        elif event["type"] == "story":
            return await self._handle_story_choice(player, active_event, choice_index)
        
        return False, "❌ 未知的事件类型"
    
    async def _handle_choice_event(self, player: Player, active_event: ActiveEvent, 
                                    choice_index: int) -> Tuple[bool, str]:
        """处理抉择类事件的选择"""
        event = active_event.event_data
        choices = event.get("choices", [])
        
        if choice_index < 1 or choice_index > len(choices):
            return False, f"❌ 无效的选择，请选择 1-{len(choices)}"
        
        choice = choices[choice_index - 1]
        
        cost = choice.get("cost", {})
        if cost.get("gold", 0) > player.gold:
            return False, f"❌ 灵石不足！需要 {cost['gold']} 灵石"
        
        if cost.get("gold"):
            player.gold -= cost["gold"]
        
        outcomes = choice.get("outcomes", [])
        outcome = self._select_outcome(outcomes)
        
        if not outcome:
            await self._clear_active_event(player.user_id)
            await self.db.update_player(player)
            return True, "奇遇结束，但什么也没发生。"
        
        rewards_msg, _ = await self._apply_rewards(player, outcome.get("rewards", {}))
        
        msg = (
            f"📜 {choice['text']}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"{outcome.get('description', '')}"
        )
        
        if rewards_msg:
            msg += f"\n\n{rewards_msg}"
        
        await self._clear_active_event(player.user_id)
        await self.db.update_player(player)
        
        return True, msg
    
    async def _handle_story_choice(self, player: Player, active_event: ActiveEvent, 
                                    choice_index: int) -> Tuple[bool, str]:
        """处理剧情类事件的选择"""
        event = active_event.event_data
        stages = event.get("stages", [])
        
        current_stage = None
        for stage in stages:
            if int(stage["stage_id"]) == int(active_event.current_stage):
                current_stage = stage
                break
        
        if not current_stage:
            await self._clear_active_event(player.user_id)
            return False, "❌ 事件数据异常"
        
        choices = current_stage.get("choices", [])
        if choice_index < 1 or choice_index > len(choices):
            return False, f"❌ 无效的选择，请选择 1-{len(choices)}"
        
        choice = choices[choice_index - 1]
        next_stage_id = choice.get("next_stage", -1)
        
        choice_id = choice.get("id", f"choice_{choice_index}")
        active_event.choices_made.append(choice_id)
        
        if "rewards" in choice:
            rewards_msg, _ = await self._apply_rewards(player, choice["rewards"])
            await self._clear_active_event(player.user_id)
            await self.db.update_player(player)
            if rewards_msg:
                return True, f"你选择了：{choice['text']}\n\n{rewards_msg}"
            return True, f"你选择了：{choice['text']}"
        
        if next_stage_id == -1:
            await self._clear_active_event(player.user_id)
            await self.db.update_player(player)
            return True, f"你选择了：{choice['text']}\n\n奇遇结束。"
        
        next_stage = None
        for stage in stages:
            if int(stage["stage_id"]) == int(next_stage_id):
                next_stage = stage
                break
        
        if not next_stage:
            await self._clear_active_event(player.user_id)
            return False, "❌ 事件数据异常"
        
        active_event.current_stage = int(next_stage_id)
        
        if next_stage.get("is_final"):
            return await self._handle_final_stage(player, active_event, next_stage)
        
        msg = f"你选择了：{choice['text']}\n\n"
        msg += f"━━━━━━━━━━━━━━━\n"
        msg += next_stage.get("text", "")
        
        if next_stage.get("npc"):
            npc = next_stage["npc"]
            msg += f"\n\n👤 {npc['name']}：「{npc['dialogue']}」"
        
        if next_stage.get("battle"):
            active_event.battle_pending = True
            active_event.pending_choice = False
            battle_info = next_stage["battle"]
            msg += f"\n\n⚔️ 即将与【{battle_info.get('enemy_name', '未知敌人')}】战斗！"
            msg += f"\n💡 发送「奇遇战斗」开始战斗"
            await self._save_active_event(active_event)
            return True, msg
        
        next_choices = next_stage.get("choices", [])
        if next_choices:
            msg += "\n\n请选择你的行动："
            for i, c in enumerate(next_choices, 1):
                msg += f"\n{i}. {c['text']}"
            msg += f"\n\n💡 发送「奇遇选择 <编号>」进行选择"

        await self._save_active_event(active_event)
        return True, msg
    
    async def _handle_final_stage(self, player: Player, active_event: ActiveEvent, 
                                   stage: dict) -> Tuple[bool, str]:
        """处理最终阶段"""
        msg = f"━━━━━━━━━━━━━━━\n{stage.get('text', '')}\n"
        
        if stage.get("battle"):
            active_event.battle_pending = True
            active_event.pending_choice = False
            active_event.event_data["final_stage"] = stage
            battle_info = stage["battle"]
            msg += f"\n⚔️ 即将与【{battle_info.get('enemy_name', '未知敌人')}】战斗！"
            msg += f"\n💡 发送「奇遇战斗」开始战斗"
            await self._save_active_event(active_event)
            return True, msg
        
        if stage.get("check"):
            check = stage["check"]
            success = self._perform_check(player, check)

            outcomes = stage.get("outcomes", [])
            condition = "check_success" if success else "check_fail"
            outcome = self._select_outcome(outcomes, condition)
            if outcome:
                rewards_msg, _ = await self._apply_rewards(player, outcome.get("rewards", {}))
                msg += f"\n{outcome.get('description', '')}"
                if rewards_msg:
                    msg += f"\n\n{rewards_msg}"
            else:
                msg += "\n奇遇在此落幕，但未触发任何额外结果。"

            await self._clear_active_event(player.user_id)
            await self.db.update_player(player)
            return True, msg
        
        outcomes = stage.get("outcomes", [])
        outcome = self._select_outcome(outcomes)
        
        if outcome:
            rewards_msg, _ = await self._apply_rewards(player, outcome.get("rewards", {}))
            msg += f"\n{outcome.get('description', '')}"
            if rewards_msg:
                msg += f"\n\n{rewards_msg}"
        
        await self._clear_active_event(player.user_id)
        await self.db.update_player(player)
        return True, msg
    
    def _perform_check(self, player: Player, check: dict) -> bool:
        """执行属性检定"""
        check_type = check.get("type", "mental_power")
        threshold = check.get("threshold", 100)
        base_chance = check.get("success_chance_base", 0.5)
        per_point = check.get("success_chance_per_point", 0.003)
        
        player_value = getattr(player, check_type, 0)
        if player_value is None:
            player_value = 0
        
        bonus = max(0, player_value - threshold) * per_point
        success_chance = min(0.95, base_chance + bonus)
        
        return random.random() < success_chance
    
    async def handle_battle(self, player: Player) -> Tuple[bool, str]:
        """处理奇遇战斗"""
        active_event = await self._load_active_event(player.user_id)
        if not active_event:
            return False, "❌ 你当前没有进行中的奇遇事件"
        if not active_event.battle_pending:
            return False, "❌ 当前奇遇不需要战斗"
        
        event = active_event.event_data
        
        battle_config = None
        if event["type"] == "challenge":
            battle_config = event.get("battle", {})
        elif event["type"] == "story":
            final_stage = event.get("final_stage")
            if final_stage:
                battle_config = final_stage.get("battle", {})
            else:
                stages = event.get("stages", [])
                for stage in stages:
                    if int(stage["stage_id"]) == int(active_event.current_stage):
                        battle_config = stage.get("battle", {})
                        break
        
        if not battle_config:
            await self._clear_active_event(player.user_id)
            return False, "❌ 战斗配置异常"
        
        win, battle_msg = await self._execute_battle(player, battle_config)
        
        if event["type"] == "challenge":
            if win:
                rewards = event.get("rewards_win", {})
                flavor = event.get("flavor_text_win", "")
            else:
                rewards = event.get("rewards_lose", {})
                flavor = event.get("flavor_text_lose", "")
            
            rewards_msg, _ = await self._apply_rewards(player, rewards)
            
            msg = battle_msg
            if flavor:
                msg += f"\n\n💭 {flavor}"
            if rewards_msg:
                msg += f"\n\n{rewards_msg}"
            
            await self._clear_active_event(player.user_id)
            await self.db.update_player(player)
            return True, msg
        
        elif event["type"] == "story":
            final_stage = event.get("final_stage")
            if final_stage:
                outcomes = final_stage.get("outcomes", [])
                condition = "battle_win" if win else "battle_lose"
                outcome = self._select_outcome(outcomes, condition)
                msg = battle_msg
                if outcome:
                    rewards_msg, _ = await self._apply_rewards(player, outcome.get("rewards", {}))
                    msg += f"\n\n{outcome.get('description', '')}"
                    if rewards_msg:
                        msg += f"\n\n{rewards_msg}"
                else:
                    msg += "\n\n奇遇战斗结束，但没有后续结果。"

                await self._clear_active_event(player.user_id)
                await self.db.update_player(player)
                return True, msg
        
        await self._clear_active_event(player.user_id)
        await self.db.update_player(player)
        return True, battle_msg
    
    async def _execute_battle(self, player: Player, battle_config: dict) -> Tuple[bool, str]:
        """执行战斗 - 与其他战斗系统保持一致"""
        enemy_name = battle_config.get("enemy_name", "未知敌人")
        stat_multiplier = battle_config.get("stat_multiplier", 1.0)
        
        if not self.battle_mgr or not self.equipment_mgr or not self.skill_mgr:
            player_power = (player.hp or 100) + (player.atk or 10) * 10
            enemy_power = player_power * stat_multiplier
            
            win_chance = player_power / (player_power + enemy_power)
            win = random.random() < win_chance
            
            if win:
                return True, f"⚔️ 你击败了【{enemy_name}】！"
            else:
                return False, f"⚔️ 你不敌【{enemy_name}】，败退而归。"
        
        player_stats = self.battle_mgr.prepare_combat_stats(
            player, self.equipment_mgr, self.skill_mgr
        )
        
        enemy_stats = self._create_enemy_combat_stats(
            player_stats, enemy_name, stat_multiplier
        )
        
        result = self.battle_mgr.execute_battle(player_stats, enemy_stats, "spar")
        
        winner_id = result.get("winner")
        win = (winner_id == player.user_id)
        
        summary = self._generate_battle_summary(result, player_stats, enemy_stats, win)
        
        return win, summary
    
    def _create_enemy_combat_stats(self, player_stats, enemy_name: str, stat_multiplier: float):
        """创建敌人战斗属性 - 与 BattleManager 的 CombatStats 结构一致"""
        from ..core.battle_manager import CombatStats
        
        enemy_max_hp = int(player_stats.max_hp * stat_multiplier)
        enemy_max_mp = int(player_stats.max_mp * stat_multiplier * 0.5)
        
        enemy_stats = CombatStats(
            user_id=f"enemy_{enemy_name}",
            name=enemy_name,
            max_hp=enemy_max_hp,
            max_mp=enemy_max_mp,
            hp=enemy_max_hp,
            mp=enemy_max_mp,
            physical_attack=int(player_stats.physical_attack * stat_multiplier),
            magic_attack=int(player_stats.magic_attack * stat_multiplier),
            physical_defense=int(player_stats.physical_defense * stat_multiplier),
            magic_defense=int(player_stats.magic_defense * stat_multiplier),
            speed=int(player_stats.speed * stat_multiplier),
            critical_rate=player_stats.critical_rate * 0.8,
            critical_damage=player_stats.critical_damage,
            hit_rate=player_stats.hit_rate,
            dodge_rate=player_stats.dodge_rate * 0.8,
            skills=[],
        )
        
        return enemy_stats
    
    def _generate_battle_summary(self, result: dict, player_stats, enemy_stats, win: bool) -> str:
        """生成战斗摘要"""
        rounds = result.get("rounds", 0)
        p1_final = result.get("p1_final", {})
        p2_final = result.get("p2_final", {})
        
        player_hp = p1_final.get("hp", 0)
        player_max_hp = p1_final.get("max_hp", player_stats.max_hp)
        enemy_hp = p2_final.get("hp", 0)
        enemy_max_hp = p2_final.get("max_hp", enemy_stats.max_hp)
        
        lines = [
            "⚔️ 【奇遇战斗】",
            f"━━━━━━━━━━━━━━━",
            f"🔵 {player_stats.name} VS 🔴 {enemy_stats.name}",
            f"",
            f"战斗回合：{rounds}",
            f"",
            f"🔵 {player_stats.name}",
            f"   HP: {player_hp}/{player_max_hp}",
            f"",
            f"🔴 {enemy_stats.name}",
            f"   HP: {enemy_hp}/{enemy_max_hp}",
            f"",
        ]
        
        if win:
            lines.append(f"🏆 胜利！你击败了【{enemy_stats.name}】！")
        else:
            lines.append(f"💀 失败！你不敌【{enemy_stats.name}】...")
        
        return "\n".join(lines)
    
    def _select_outcome(self, outcomes: List[dict], condition: Optional[str] = None) -> Optional[dict]:
        """根据概率和条件选择结果。"""
        if not outcomes:
            return None

        if condition:
            candidates = [o for o in outcomes if o.get("condition") == condition]
        else:
            candidates = [o for o in outcomes if not o.get("condition")]

        if not candidates:
            return None

        total_chance = sum(max(0, float(o.get("chance", 1.0))) for o in candidates)
        if total_chance <= 0:
            return candidates[-1]

        roll = random.random() * total_chance
        cumulative = 0.0
        for outcome in candidates:
            cumulative += max(0, float(outcome.get("chance", 1.0)))
            if roll <= cumulative:
                return outcome

        return candidates[-1]
    
    async def _apply_rewards(self, player: Player, rewards: dict) -> Tuple[str, dict]:
        """应用奖励"""
        if not rewards:
            return "", {}
        
        msg_parts = []
        applied = {}
        
        # 灵石奖励
        if "gold" in rewards:
            gold_range = rewards["gold"]
            if isinstance(gold_range, dict):
                gold = random.randint(gold_range.get("min", 0), gold_range.get("max", 0))
            else:
                gold = int(gold_range)
            if gold > 0:
                player.gold = (player.gold or 0) + gold
                msg_parts.append(f"💰 灵石 +{gold}")
                applied["gold"] = gold
        
        # 经验奖励
        if "exp" in rewards:
            exp_range = rewards["exp"]
            if isinstance(exp_range, dict):
                exp = random.randint(exp_range.get("min", 0), exp_range.get("max", 0))
            else:
                exp = int(exp_range)
            if exp > 0:
                player.experience = (player.experience or 0) + exp
                msg_parts.append(f"📈 修为 +{exp}")
                applied["exp"] = exp
        
        # 物品奖励
        # 注意：这里必须避免“先由 store_item 写库、随后 update_player(player) 用旧对象覆盖”的情况
        # 因此统一使用 external_transaction=True，让物品直接写入当前 player 对象，最终由调用方 update_player 一次性落库。
        if "items" in rewards and self.storage_ring_mgr:
            items_gained = []
            for item_info in rewards["items"]:
                if random.random() > item_info.get("chance", 1.0):
                    continue
                
                count_range = item_info.get("count", {"min": 1, "max": 1})
                if isinstance(count_range, dict):
                    count = random.randint(count_range.get("min", 1), count_range.get("max", 1))
                else:
                    count = int(count_range)
                
                item_name = item_info["name"]
                success, _ = await self.storage_ring_mgr.store_item(
                    player,
                    item_name,
                    count,
                    silent=True,
                    external_transaction=True
                )
                if success:
                    items_gained.append(f"{item_name} x{count}")
            
            if items_gained:
                msg_parts.append(f"📦 获得物品：{', '.join(items_gained)}")
                applied["items"] = items_gained
        
        # 技能奖励
        if "skills" in rewards and self.skill_mgr:
            for skill_info in rewards["skills"]:
                if random.random() > skill_info.get("chance", 1.0):
                    continue
                
                skill_id = skill_info["id"]
                success, skill_msg = await self.skill_mgr.learn_skill(player, skill_id, cost_gold=False)
                if success:
                    skill_config = self.skill_mgr.get_skill_by_id(skill_id)
                    skill_name = skill_config.get("name", skill_id) if skill_config else skill_id
                    msg_parts.append(f"⚡ 学会技能：{skill_name}")
                    applied.setdefault("skills", []).append(skill_name)
        
        # 属性奖励
        if "attributes" in rewards:
            attr_msgs = []
            for attr, value_range in rewards["attributes"].items():
                if isinstance(value_range, dict):
                    value = random.randint(value_range.get("min", 0), value_range.get("max", 0))
                else:
                    value = value_range
                
                if value > 0 or (isinstance(value, float) and value > 0):
                    if hasattr(player, attr):
                        current = getattr(player, attr)
                        if current is None:
                            current = 0.0 if isinstance(value, float) else 0
                        
                        new_value = current + value
                        setattr(player, attr, new_value)
                        
                        attr_names = {
                            "physical_damage": "物伤",
                            "magic_damage": "法伤",
                            "physical_defense": "物防",
                            "magic_defense": "法防",
                            "mental_power": "精神力",
                            "max_hp": "最大HP",
                            "max_mp": "最大MP",
                            "speed": "速度",
                            "critical_rate": "暴击率",
                            "critical_damage": "暴击伤害"
                        }
                        attr_name = attr_names.get(attr, attr)
                        if attr in ["critical_rate", "critical_damage"]:
                            attr_msgs.append(f"{attr_name} +{value:.1%}")
                        else:
                            attr_msgs.append(f"{attr_name} +{value}")
                        applied.setdefault("attributes", {})[attr] = value
            
            if attr_msgs:
                msg_parts.append(f"📊 属性提升：{', '.join(attr_msgs)}")
        
        # 负面效果：HP损失
        if "hp_loss_percent" in rewards:
            max_hp = player.max_hp or 100
            current_hp = player.hp or max_hp
            loss = int(max_hp * rewards["hp_loss_percent"])
            player.hp = max(1, current_hp - loss)
            msg_parts.append(f"💔 HP -{loss}")
            applied["hp_loss"] = loss
        
        # 负面效果：MP损失
        if "mp_loss_percent" in rewards:
            max_mp = player.max_mp or 50
            current_mp = player.mp or max_mp
            loss = int(max_mp * rewards["mp_loss_percent"])
            player.mp = max(0, current_mp - loss)
            msg_parts.append(f"💙 MP -{loss}")
            applied["mp_loss"] = loss
        
        # 负面效果：灵石损失
        if "gold_loss_percent" in rewards:
            current_gold = player.gold or 0
            loss = int(current_gold * rewards["gold_loss_percent"])
            player.gold = max(0, current_gold - loss)
            msg_parts.append(f"💸 灵石 -{loss}")
            applied["gold_loss"] = loss
        
        # 负面效果：经验损失
        if "exp_loss_percent" in rewards:
            current_exp = player.experience or 0
            loss = int(current_exp * rewards["exp_loss_percent"])
            player.experience = max(0, current_exp - loss)
            msg_parts.append(f"📉 修为 -{loss}")
            applied["exp_loss"] = loss
        
        if msg_parts:
            return "🎁 奖励：\n" + "\n".join(msg_parts), applied
        return "", applied
    
    async def abandon_event(self, player: Player) -> Tuple[bool, str]:
        """放弃当前奇遇"""
        active_event = await self._load_active_event(player.user_id)
        if not active_event:
            return False, "❌ 你当前没有进行中的奇遇事件"
        
        event = active_event.event_data
        await self._clear_active_event(player.user_id)
        
        return True, f"你放弃了奇遇【{event.get('name', '未知')}】，继续赶路。"
    
    async def get_active_event(self, player: Player) -> Optional[ActiveEvent]:
        """获取玩家当前的奇遇事件"""
        return await self._load_active_event(player.user_id)
    
    async def has_active_event(self, player: Player) -> bool:
        """检查玩家是否有进行中的奇遇"""
        return await self._load_active_event(player.user_id) is not None
