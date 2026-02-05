"""
战斗管理器 - 处理回合制战斗逻辑
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, TYPE_CHECKING
import random

if TYPE_CHECKING:
    from models import Player
    from config_manager import ConfigManager


@dataclass
class CombatStats:
    """战斗属性"""
    user_id: str
    name: str
    hp: int
    max_hp: int
    mp: int
    max_mp: int
    physical_attack: int
    magic_attack: int
    physical_defense: int
    magic_defense: int
    speed: int
    critical_rate: float = 0.05
    critical_damage: float = 1.5
    hit_rate: float = 0.95
    dodge_rate: float = 0.05
    skills: List[dict] = field(default_factory=list)
    skill_cooldowns: Dict[str, int] = field(default_factory=dict)
    shield: int = 0
    buffs: List[dict] = field(default_factory=list)
    debuffs: List[dict] = field(default_factory=list)
    
    def is_alive(self) -> bool:
        """检查是否存活"""
        return self.hp > 0
    
    def get_effective_physical_attack(self) -> int:
        """获取有效物理攻击（含buff/debuff）"""
        base = self.physical_attack
        multiplier = 1.0
        flat_bonus = 0
        
        for buff in self.buffs:
            if buff.get("type") == "attack_boost":
                multiplier += buff.get("value", 0)
            elif buff.get("type") == "physical_attack_flat":
                flat_bonus += buff.get("value", 0)
        
        for debuff in self.debuffs:
            if debuff.get("type") == "armor_break":
                # 破甲效果降低物攻
                multiplier -= debuff.get("value", 0)
        
        return max(1, int(base * multiplier + flat_bonus))
    
    def get_effective_magic_attack(self) -> int:
        """获取有效法术攻击（含buff/debuff）"""
        base = self.magic_attack
        multiplier = 1.0
        flat_bonus = 0
        
        for buff in self.buffs:
            if buff.get("type") == "attack_boost":
                multiplier += buff.get("value", 0)
            elif buff.get("type") == "magic_attack_flat":
                flat_bonus += buff.get("value", 0)
        
        for debuff in self.debuffs:
            if debuff.get("type") == "magic_break":
                multiplier -= debuff.get("value", 0)
        
        return max(1, int(base * multiplier + flat_bonus))
    
    def get_effective_physical_defense(self) -> int:
        """获取有效物理防御（含buff/debuff）"""
        base = self.physical_defense
        multiplier = 1.0
        flat_bonus = 0
        
        for buff in self.buffs:
            if buff.get("type") == "defense_boost":
                multiplier += buff.get("value", 0)
            elif buff.get("type") == "physical_defense_flat":
                flat_bonus += buff.get("value", 0)
        
        for debuff in self.debuffs:
            if debuff.get("type") == "armor_break":
                multiplier -= debuff.get("value", 0)
        
        return max(0, int(base * multiplier + flat_bonus))
    
    def get_effective_magic_defense(self) -> int:
        """获取有效法术防御（含buff/debuff）"""
        base = self.magic_defense
        multiplier = 1.0
        flat_bonus = 0
        
        for buff in self.buffs:
            if buff.get("type") == "defense_boost":
                multiplier += buff.get("value", 0)
            elif buff.get("type") == "magic_defense_flat":
                flat_bonus += buff.get("value", 0)
        
        for debuff in self.debuffs:
            if debuff.get("type") == "magic_break":
                multiplier -= debuff.get("value", 0)
        
        return max(0, int(base * multiplier + flat_bonus))
    
    def get_effective_speed(self) -> int:
        """获取有效速度（含buff/debuff）"""
        base = self.speed
        multiplier = 1.0
        
        for buff in self.buffs:
            if buff.get("type") == "speed_boost":
                multiplier += buff.get("value", 0)
        
        for debuff in self.debuffs:
            if debuff.get("type") == "slow":
                multiplier -= debuff.get("value", 0)
        
        return max(1, int(base * multiplier))
    
    def get_effective_dodge_rate(self) -> float:
        """获取有效闪避率（含buff/debuff）"""
        base = self.dodge_rate
        bonus = 0.0
        
        for buff in self.buffs:
            if buff.get("type") == "dodge_boost":
                bonus += buff.get("value", 0)
        
        for debuff in self.debuffs:
            if debuff.get("type") == "slow":
                # 减速也降低闪避
                bonus -= debuff.get("value", 0) * 0.5
        
        return min(0.8, max(0, base + bonus))
    
    def get_effective_critical_rate(self) -> float:
        """获取有效暴击率（含buff/debuff）"""
        base = self.critical_rate
        bonus = 0.0
        
        for buff in self.buffs:
            if buff.get("type") == "critical_boost":
                bonus += buff.get("value", 0)
        
        return min(1.0, max(0, base + bonus))
    
    def is_stunned(self) -> bool:
        """检查是否被眩晕"""
        for debuff in self.debuffs:
            if debuff.get("type") in ["stun", "freeze", "paralysis"]:
                return True
        return False
    
    def is_confused(self) -> bool:
        """检查是否被混乱"""
        for debuff in self.debuffs:
            if debuff.get("type") == "confusion":
                return True
        return False


class BattleManager:
    """战斗管理器 - 处理回合制战斗逻辑"""
    
    MAX_ROUNDS = 50  # 最大回合数，防止无限战斗
    
    def __init__(self, config_manager: "ConfigManager"):
        self.config_manager = config_manager
    
    def _apply_technique_passive_effects(self, tech_config: dict, 
                                          base_stats: dict,
                                          percent_bonuses: dict) -> None:
        """应用功法被动效果
        
        Args:
            tech_config: 功法配置
            base_stats: 基础属性字典（会被修改）
            percent_bonuses: 百分比加成字典（会被修改）
        """
        passive_effects = tech_config.get("passive_effects", {})
        
        for effect_type, value in passive_effects.items():
            # 固定值加成
            if effect_type == "critical_rate":
                base_stats["critical_rate"] += value
            elif effect_type == "critical_damage":
                base_stats["critical_damage"] += value
            elif effect_type == "dodge_rate":
                base_stats["dodge_rate"] += value
            elif effect_type == "hit_rate":
                base_stats["hit_rate"] += value
            elif effect_type == "speed":
                base_stats["speed"] += value
            elif effect_type == "lifesteal":
                base_stats["lifesteal"] = base_stats.get("lifesteal", 0) + value
            elif effect_type == "damage_reduction":
                base_stats["damage_reduction"] = base_stats.get("damage_reduction", 0) + value
            elif effect_type == "regeneration":
                base_stats["regeneration"] = base_stats.get("regeneration", 0) + value
            elif effect_type == "stun_resist":
                base_stats["stun_resist"] = base_stats.get("stun_resist", 0) + value
            elif effect_type == "mp_regen":
                base_stats["mp_regen"] = base_stats.get("mp_regen", 0) + value
            elif effect_type == "burn_chance":
                base_stats["burn_chance"] = base_stats.get("burn_chance", 0) + value
            elif effect_type == "slow_effect":
                base_stats["slow_effect"] = base_stats.get("slow_effect", 0) + value
            
            # 百分比加成（累积后统一应用）
            elif effect_type == "physical_attack_percent":
                percent_bonuses["physical_attack"] += value
            elif effect_type == "magic_attack_percent":
                percent_bonuses["magic_attack"] += value
            elif effect_type == "physical_defense_percent":
                percent_bonuses["physical_defense"] += value
            elif effect_type == "magic_defense_percent":
                percent_bonuses["magic_defense"] += value
            elif effect_type == "hp_percent":
                percent_bonuses["hp"] += value
            elif effect_type == "mp_percent":
                percent_bonuses["mp"] += value
            elif effect_type == "speed_percent":
                percent_bonuses["speed"] += value
            elif effect_type == "all_damage_percent":
                percent_bonuses["physical_attack"] += value
                percent_bonuses["magic_attack"] += value
            elif effect_type == "all_defense_percent":
                percent_bonuses["physical_defense"] += value
                percent_bonuses["magic_defense"] += value
    
    def prepare_combat_stats(self, player: "Player", 
                             equipment_manager=None,
                             skill_manager=None) -> CombatStats:
        """准备战斗属性（整合基础、丹药、装备、功法）
        
        Args:
            player: 玩家对象
            equipment_manager: 装备管理器（可选）
            skill_manager: 技能管理器（可选）
        
        Returns:
            CombatStats: 战斗属性对象
        """
        # 1. 获取境界基础属性
        if player.cultivation_type == "体修":
            level_config = self.config_manager.get_body_level_config()
        else:
            level_config = self.config_manager.get_level_config()
        
        current_level = level_config.get(str(player.level_index), {})
        
        base_hp = current_level.get("base_hp", 100)
        base_mp = current_level.get("base_mp", 50)
        base_speed = current_level.get("base_speed", 10)
        
        # 基础攻防（根据境界和修炼类型）
        level_multiplier = 1 + player.level_index * 0.1
        
        if player.cultivation_type == "体修":
            base_physical_attack = int(20 * level_multiplier)
            base_magic_attack = int(10 * level_multiplier)
            base_physical_defense = int(15 * level_multiplier)
            base_magic_defense = int(8 * level_multiplier)
        else:
            base_physical_attack = int(12 * level_multiplier)
            base_magic_attack = int(18 * level_multiplier)
            base_physical_defense = int(10 * level_multiplier)
            base_magic_defense = int(12 * level_multiplier)
        
        # 2. 应用永久丹药加成（百分比，只对基础）
        permanent_gains = player.get_permanent_pill_gains()
        
        hp_percent_bonus = permanent_gains.get("max_hp_percent", 0)
        mp_percent_bonus = permanent_gains.get("max_mp_percent", 0)
        atk_percent_bonus = permanent_gains.get("atk_percent", 0)
        def_percent_bonus = permanent_gains.get("def_percent", 0)
        
        base_hp = int(base_hp * (1 + hp_percent_bonus))
        base_mp = int(base_mp * (1 + mp_percent_bonus))
        base_physical_attack = int(base_physical_attack * (1 + atk_percent_bonus))
        base_magic_attack = int(base_magic_attack * (1 + atk_percent_bonus))
        base_physical_defense = int(base_physical_defense * (1 + def_percent_bonus))
        base_magic_defense = int(base_magic_defense * (1 + def_percent_bonus))
        
        # 永久丹药固定加成
        base_hp += permanent_gains.get("max_hp", 0)
        base_mp += permanent_gains.get("max_mp", 0)
        base_physical_attack += permanent_gains.get("physical_attack", 0)
        base_magic_attack += permanent_gains.get("magic_attack", 0)
        base_physical_defense += permanent_gains.get("physical_defense", 0)
        base_magic_defense += permanent_gains.get("magic_defense", 0)
        base_speed += permanent_gains.get("speed", 0)
        
        critical_rate = 0.05 + permanent_gains.get("critical_rate", 0)
        critical_damage = 1.5 + permanent_gains.get("critical_damage", 0)
        hit_rate = 0.95 + permanent_gains.get("hit_rate", 0)
        dodge_rate = 0.05 + permanent_gains.get("dodge_rate", 0)
        
        # 3. 叠加装备加成
        if equipment_manager:
            # 获取物品和武器配置数据
            items_data = self.config_manager.get_items_config()
            weapons_data = self.config_manager.get_weapons_config()
            
            # 获取已装备物品列表
            equipped_items = equipment_manager.get_equipped_items(player, items_data, weapons_data)
            
            # 累加装备属性
            for item in equipped_items:
                base_physical_attack += item.physical_damage
                base_magic_attack += item.magic_damage
                base_physical_defense += item.physical_defense
                base_magic_defense += item.magic_defense
                base_speed += item.speed
                critical_rate += item.critical_rate
                critical_damage += item.critical_damage
                base_hp += item.hp_bonus
                base_mp += item.mp_bonus
        
        # 4. 叠加功法属性和被动效果
        techniques_list = player.get_techniques_list()
        techniques_config = self.config_manager.get_techniques_config()
        
        # 用于收集百分比加成（最后统一应用）
        percent_bonuses = {
            "physical_attack": 0.0,
            "magic_attack": 0.0,
            "physical_defense": 0.0,
            "magic_defense": 0.0,
            "hp": 0.0,
            "mp": 0.0,
            "speed": 0.0,
        }
        
        # 用于收集固定值加成
        base_stats = {
            "critical_rate": critical_rate,
            "critical_damage": critical_damage,
            "hit_rate": hit_rate,
            "dodge_rate": dodge_rate,
            "speed": base_speed,
            "lifesteal": 0.0,
            "damage_reduction": 0.0,
            "regeneration": 0.0,
            "stun_resist": 0.0,
            "mp_regen": 0.0,
            "burn_chance": 0.0,
            "slow_effect": 0.0,
        }
        
        # 主修心法
        if player.main_technique:
            main_tech = techniques_config.get(player.main_technique, {})
            
            # 基础属性加成
            base_hp += main_tech.get("hp_bonus", 0)
            base_mp += main_tech.get("mp_bonus", 0)
            base_physical_attack += main_tech.get("physical_damage", 0)
            base_magic_attack += main_tech.get("magic_damage", 0)
            base_physical_defense += main_tech.get("physical_defense", 0)
            base_magic_defense += main_tech.get("magic_defense", 0)
            base_stats["speed"] += main_tech.get("speed", 0)
            base_stats["critical_rate"] += main_tech.get("critical_rate", 0)
            base_stats["critical_damage"] += main_tech.get("critical_damage", 0)
            
            # 应用被动效果
            self._apply_technique_passive_effects(main_tech, base_stats, percent_bonuses)
        
        # 辅修功法
        for tech_id in techniques_list:
            tech = techniques_config.get(tech_id, {})
            
            # 基础属性加成
            base_hp += tech.get("hp_bonus", 0)
            base_mp += tech.get("mp_bonus", 0)
            base_physical_attack += tech.get("physical_damage", 0)
            base_magic_attack += tech.get("magic_damage", 0)
            base_physical_defense += tech.get("physical_defense", 0)
            base_magic_defense += tech.get("magic_defense", 0)
            base_stats["speed"] += tech.get("speed", 0)
            base_stats["critical_rate"] += tech.get("critical_rate", 0)
            base_stats["critical_damage"] += tech.get("critical_damage", 0)
            
            # 应用被动效果
            self._apply_technique_passive_effects(tech, base_stats, percent_bonuses)
        
        # 5. 应用百分比加成（在所有固定值加成之后）
        base_physical_attack = int(base_physical_attack * (1 + percent_bonuses["physical_attack"]))
        base_magic_attack = int(base_magic_attack * (1 + percent_bonuses["magic_attack"]))
        base_physical_defense = int(base_physical_defense * (1 + percent_bonuses["physical_defense"]))
        base_magic_defense = int(base_magic_defense * (1 + percent_bonuses["magic_defense"]))
        base_hp = int(base_hp * (1 + percent_bonuses["hp"]))
        base_mp = int(base_mp * (1 + percent_bonuses["mp"]))
        base_stats["speed"] = int(base_stats["speed"] * (1 + percent_bonuses["speed"]))
        
        # 6. 应用临时丹药倍率
        active_effects = player.get_active_pill_effects()
        
        for effect in active_effects:
            effect_type = effect.get("type", "")
            value = effect.get("value", 0)
            
            if effect_type == "hp_multiplier":
                base_hp = int(base_hp * (1 + value))
            elif effect_type == "mp_multiplier":
                base_mp = int(base_mp * (1 + value))
            elif effect_type == "atk_multiplier":
                base_physical_attack = int(base_physical_attack * (1 + value))
                base_magic_attack = int(base_magic_attack * (1 + value))
            elif effect_type == "def_multiplier":
                base_physical_defense = int(base_physical_defense * (1 + value))
                base_magic_defense = int(base_magic_defense * (1 + value))
            elif effect_type == "speed_multiplier":
                base_stats["speed"] = int(base_stats["speed"] * (1 + value))
            elif effect_type == "critical_rate_bonus":
                base_stats["critical_rate"] += value
            elif effect_type == "dodge_rate_bonus":
                base_stats["dodge_rate"] += value
        
        # 获取已装备技能
        equipped_skills = []
        if skill_manager:
            equipped_skills = skill_manager.get_equipped_skill_configs(player)
        
        # 限制属性范围
        final_critical_rate = min(0.8, max(0, base_stats["critical_rate"]))
        final_critical_damage = max(1.0, base_stats["critical_damage"])
        final_hit_rate = min(1.0, max(0.5, base_stats["hit_rate"]))
        final_dodge_rate = min(0.8, max(0, base_stats["dodge_rate"]))
        final_speed = max(1, base_stats["speed"])
        
        return CombatStats(
            user_id=player.user_id,
            name=player.user_name,
            hp=base_hp,
            max_hp=base_hp,
            mp=base_mp,
            max_mp=base_mp,
            physical_attack=base_physical_attack,
            magic_attack=base_magic_attack,
            physical_defense=base_physical_defense,
            magic_defense=base_magic_defense,
            speed=final_speed,
            critical_rate=final_critical_rate,
            critical_damage=final_critical_damage,
            hit_rate=final_hit_rate,
            dodge_rate=final_dodge_rate,
            skills=equipped_skills,
            skill_cooldowns={},
            shield=0,
            buffs=[],
            debuffs=[]
        )
    
    def execute_battle(self, p1: CombatStats, p2: CombatStats,
                       battle_type: str = "spar") -> dict:
        """执行战斗
        
        Args:
            p1, p2: 双方战斗属性
            battle_type: "spar"(切磋) 或 "duel"(决斗)
        
        Returns:
            {
                "winner": user_id or None,
                "loser": user_id or None,
                "is_draw": bool,
                "log": [...],
                "rounds": int,
                "p1_final": {...},
                "p2_final": {...}
            }
        """
        battle_log = []
        round_num = 0
        
        # 切磋模式下，HP低于20%时认输
        spar_threshold = 0.2 if battle_type == "spar" else 0
        
        battle_log.append(f"⚔️ 【{battle_type == 'spar' and '切磋' or '决斗'}开始】")
        battle_log.append(f"🔵 {p1.name} HP:{p1.hp}/{p1.max_hp} MP:{p1.mp}/{p1.max_mp}")
        battle_log.append(f"🔴 {p2.name} HP:{p2.hp}/{p2.max_hp} MP:{p2.mp}/{p2.max_mp}")
        battle_log.append("")
        
        while round_num < self.MAX_ROUNDS:
            round_num += 1
            battle_log.append(f"━━━ 第{round_num}回合 ━━━")
            
            # 回合开始：处理持续效果
            p1_dot_logs = self._process_dot_effects(p1)
            p2_dot_logs = self._process_dot_effects(p2)
            
            for log in p1_dot_logs:
                battle_log.append(f"🔵 {log}")
            for log in p2_dot_logs:
                battle_log.append(f"🔴 {log}")
            
            # 检查DOT是否致死
            if not p1.is_alive():
                battle_log.append(f"💀 {p1.name} 被持续伤害击败！")
                break
            if not p2.is_alive():
                battle_log.append(f"💀 {p2.name} 被持续伤害击败！")
                break
            
            # 更新buff/debuff持续时间
            self._update_effects_duration(p1)
            self._update_effects_duration(p2)
            
            # 决定行动顺序（速度高者先手）
            p1_speed = p1.get_effective_speed()
            p2_speed = p2.get_effective_speed()
            
            if p1_speed > p2_speed:
                first, second = p1, p2
                first_tag, second_tag = "🔵", "🔴"
            elif p2_speed > p1_speed:
                first, second = p2, p1
                first_tag, second_tag = "🔴", "🔵"
            else:
                # 速度相同，随机决定
                if random.random() < 0.5:
                    first, second = p1, p2
                    first_tag, second_tag = "🔵", "🔴"
                else:
                    first, second = p2, p1
                    first_tag, second_tag = "🔴", "🔵"
            
            # 先手行动
            if first.is_alive() and second.is_alive():
                action_logs = self._execute_action(first, second, first_tag)
                battle_log.extend(action_logs)
            
            # 检查切磋认输
            if battle_type == "spar":
                if second.hp <= second.max_hp * spar_threshold:
                    battle_log.append(f"🏳️ {second.name} HP过低，主动认输！")
                    second.hp = 0
                    break
            
            # 检查是否击败
            if not second.is_alive():
                battle_log.append(f"💀 {second.name} 被击败！")
                break
            
            # 后手行动
            if second.is_alive() and first.is_alive():
                action_logs = self._execute_action(second, first, second_tag)
                battle_log.extend(action_logs)
            
            # 检查切磋认输
            if battle_type == "spar":
                if first.hp <= first.max_hp * spar_threshold:
                    battle_log.append(f"🏳️ {first.name} HP过低，主动认输！")
                    first.hp = 0
                    break
            
            # 检查是否击败
            if not first.is_alive():
                battle_log.append(f"💀 {first.name} 被击败！")
                break
            
            # 更新技能冷却
            self._update_cooldowns(p1)
            self._update_cooldowns(p2)
            
            # 回合结束状态
            battle_log.append(f"🔵 {p1.name}: HP {p1.hp}/{p1.max_hp} MP {p1.mp}/{p1.max_mp}")
            battle_log.append(f"🔴 {p2.name}: HP {p2.hp}/{p2.max_hp} MP {p2.mp}/{p2.max_mp}")
            battle_log.append("")
        
        # 判定胜负
        winner = None
        loser = None
        is_draw = False
        
        if not p1.is_alive() and not p2.is_alive():
            is_draw = True
            battle_log.append("⚖️ 双方同归于尽，平局！")
        elif not p1.is_alive():
            winner = p2.user_id
            loser = p1.user_id
            battle_log.append(f"🏆 {p2.name} 获胜！")
        elif not p2.is_alive():
            winner = p1.user_id
            loser = p2.user_id
            battle_log.append(f"🏆 {p1.name} 获胜！")
        elif round_num >= self.MAX_ROUNDS:
            # 超过最大回合数，按剩余HP百分比判定
            p1_hp_percent = p1.hp / p1.max_hp
            p2_hp_percent = p2.hp / p2.max_hp
            
            if p1_hp_percent > p2_hp_percent:
                winner = p1.user_id
                loser = p2.user_id
                battle_log.append(f"⏰ 回合耗尽，{p1.name} 以HP优势获胜！")
            elif p2_hp_percent > p1_hp_percent:
                winner = p2.user_id
                loser = p1.user_id
                battle_log.append(f"⏰ 回合耗尽，{p2.name} 以HP优势获胜！")
            else:
                is_draw = True
                battle_log.append("⏰ 回合耗尽，双方HP相当，平局！")
        
        return {
            "winner": winner,
            "loser": loser,
            "is_draw": is_draw,
            "log": battle_log,
            "rounds": round_num,
            "p1_final": {
                "user_id": p1.user_id,
                "name": p1.name,
                "hp": p1.hp,
                "max_hp": p1.max_hp,
                "mp": p1.mp,
                "max_mp": p1.max_mp
            },
            "p2_final": {
                "user_id": p2.user_id,
                "name": p2.name,
                "hp": p2.hp,
                "max_hp": p2.max_hp,
                "mp": p2.mp,
                "max_mp": p2.max_mp
            }
        }
    
    def _execute_action(self, attacker: CombatStats, defender: CombatStats,
                        tag: str) -> List[str]:
        """执行一次行动
        
        Args:
            attacker: 攻击方
            defender: 防守方
            tag: 标签（🔵或🔴）
        
        Returns:
            行动日志列表
        """
        logs = []
        
        # 检查是否被控制
        if attacker.is_stunned():
            logs.append(f"{tag} {attacker.name} 处于控制状态，无法行动！")
            return logs
        
        # 检查混乱状态
        if attacker.is_confused():
            if random.random() < 0.5:
                # 混乱导致攻击自己
                logs.append(f"{tag} {attacker.name} 陷入混乱，攻击了自己！")
                damage = int(attacker.get_effective_physical_attack() * 0.3)
                self._apply_damage(attacker, damage)
                logs.append(f"{tag} {attacker.name} 对自己造成 {damage} 点伤害！")
                return logs
        
        # 选择行动
        action_type, skill = self._select_action(attacker)
        
        if action_type == "skill" and skill:
            logs.extend(self._execute_skill(attacker, defender, skill, tag))
        else:
            logs.extend(self._execute_normal_attack(attacker, defender, tag))
        
        return logs
    
    def _select_action(self, attacker: CombatStats) -> Tuple[str, Optional[dict]]:
        """选择行动（优先威力高的可用技能）
        
        Returns:
            ("skill", skill_config) 或 ("normal", None)
        """
        available_skills = []
        
        for skill in attacker.skills:
            skill_id = skill.get("id", "")
            mp_cost = skill.get("mp_cost", 0)
            cooldown = attacker.skill_cooldowns.get(skill_id, 0)
            
            # 检查冷却和MP
            if cooldown <= 0 and attacker.mp >= mp_cost:
                # 计算技能威力评分
                damage_config = skill.get("damage", {})
                base_damage = damage_config.get("base", 0)
                attack_ratio = damage_config.get("attack_ratio", 1.0)
                
                # 根据技能类型选择攻击力
                damage_type = skill.get("damage_type", "physical")
                if damage_type == "magic":
                    atk = attacker.get_effective_magic_attack()
                else:
                    atk = attacker.get_effective_physical_attack()
                
                power_score = base_damage + atk * attack_ratio
                
                # 有效果的技能加分
                if skill.get("effects"):
                    power_score *= 1.2
                
                available_skills.append((skill, power_score))
        
        if available_skills:
            # 按威力排序，选择最强的技能
            available_skills.sort(key=lambda x: x[1], reverse=True)
            
            # 80%概率使用最强技能，20%概率随机选择
            if random.random() < 0.8:
                return ("skill", available_skills[0][0])
            else:
                return ("skill", random.choice(available_skills)[0])
        
        return ("normal", None)
    
    def _execute_skill(self, attacker: CombatStats, defender: CombatStats,
                       skill: dict, tag: str) -> List[str]:
        """执行技能攻击"""
        logs = []
        skill_name = skill.get("name", "未知技能")
        skill_id = skill.get("id", "")
        mp_cost = skill.get("mp_cost", 0)
        cooldown = skill.get("cooldown", 0)
        
        # 消耗MP
        attacker.mp -= mp_cost
        
        # 设置冷却
        if cooldown > 0:
            attacker.skill_cooldowns[skill_id] = cooldown
        
        logs.append(f"{tag} {attacker.name} 使用【{skill_name}】！(消耗 {mp_cost} MP)")
        
        # 计算伤害
        damage, is_crit, is_miss = self._calculate_skill_damage(attacker, defender, skill)
        
        if is_miss:
            logs.append(f"{tag} {defender.name} 闪避了攻击！")
        else:
            # 应用伤害
            actual_damage = self._apply_damage(defender, damage)
            
            crit_text = "💥暴击！" if is_crit else ""
            logs.append(f"{tag} {crit_text}对 {defender.name} 造成 {actual_damage} 点伤害！")
            
            # 处理技能效果
            effects = skill.get("effects", [])
            for effect in effects:
                effect_logs = self._apply_skill_effect(attacker, defender, effect, tag)
                logs.extend(effect_logs)
            
            # 生命偷取
            lifesteal = skill.get("lifesteal", 0)
            if lifesteal > 0:
                heal_amount = int(actual_damage * lifesteal)
                attacker.hp = min(attacker.max_hp, attacker.hp + heal_amount)
                logs.append(f"{tag} {attacker.name} 吸取了 {heal_amount} 点生命！")
        
        # MP耗尽惩罚
        if attacker.mp <= 0:
            penalty = skill.get("mp_exhausted_penalty", 0.5)
            if penalty > 0:
                penalty_damage = int(attacker.max_hp * penalty * 0.1)
                self._apply_damage(attacker, penalty_damage)
                logs.append(f"{tag} {attacker.name} 真元耗尽，受到 {penalty_damage} 点反噬伤害！")
        
        return logs
    
    def _execute_normal_attack(self, attacker: CombatStats, defender: CombatStats,
                               tag: str) -> List[str]:
        """执行普通攻击"""
        logs = []
        
        damage, is_crit, damage_type = self._calculate_normal_attack(attacker, defender)
        
        # 命中判定
        hit_roll = random.random()
        effective_hit_rate = attacker.hit_rate - defender.get_effective_dodge_rate()
        effective_hit_rate = max(0.3, min(0.95, effective_hit_rate))
        
        if hit_roll > effective_hit_rate:
            logs.append(f"{tag} {attacker.name} 的攻击被 {defender.name} 闪避了！")
            return logs
        
        # 应用伤害
        actual_damage = self._apply_damage(defender, damage)
        
        type_text = "物理" if damage_type == "physical" else "法术"
        crit_text = "💥暴击！" if is_crit else ""
        logs.append(f"{tag} {attacker.name} 发动{type_text}攻击！{crit_text}对 {defender.name} 造成 {actual_damage} 点伤害！")
        
        return logs
    
    def _calculate_skill_damage(self, attacker: CombatStats, defender: CombatStats,
                                skill: dict) -> Tuple[int, bool, bool]:
        """计算技能伤害
        
        Returns:
            (damage, is_crit, is_miss)
        """
        damage_config = skill.get("damage", {})
        base_damage = damage_config.get("base", 0)
        attack_ratio = damage_config.get("attack_ratio", 1.0)
        damage_type = skill.get("damage_type", "physical")
        
        # 选择攻击力和防御力
        if damage_type == "magic":
            atk = attacker.get_effective_magic_attack()
            defense = defender.get_effective_magic_defense()
        else:
            atk = attacker.get_effective_physical_attack()
            defense = defender.get_effective_physical_defense()
        
        # 命中判定
        hit_roll = random.random()
        effective_hit_rate = attacker.hit_rate - defender.get_effective_dodge_rate()
        effective_hit_rate = max(0.3, min(0.95, effective_hit_rate))
        
        if hit_roll > effective_hit_rate:
            return (0, False, True)  # 未命中
        
        # 基础伤害计算
        raw_damage = base_damage + int(atk * attack_ratio)
        
        # 防御减伤（防御值越高，减伤越多，但有上限）
        damage_reduction = defense / (defense + 100)
        damage_reduction = min(0.75, damage_reduction)  # 最多减伤75%
        
        final_damage = int(raw_damage * (1 - damage_reduction))
        
        # 暴击判定
        is_crit = random.random() < attacker.get_effective_critical_rate()
        if is_crit:
            final_damage = int(final_damage * attacker.critical_damage)
        
        # 伤害浮动（±10%）
        damage_variance = random.uniform(0.9, 1.1)
        final_damage = int(final_damage * damage_variance)
        
        # 最小伤害保证
        final_damage = max(1, final_damage)
        
        return (final_damage, is_crit, False)
    
    def _calculate_normal_attack(self, attacker: CombatStats,
                                 defender: CombatStats) -> Tuple[int, bool, str]:
        """计算普通攻击伤害
        
        Returns:
            (damage, is_crit, damage_type)
        """
        # 根据攻击力高低决定伤害类型
        phys_atk = attacker.get_effective_physical_attack()
        magic_atk = attacker.get_effective_magic_attack()
        
        if phys_atk >= magic_atk:
            damage_type = "physical"
            atk = phys_atk
            defense = defender.get_effective_physical_defense()
        else:
            damage_type = "magic"
            atk = magic_atk
            defense = defender.get_effective_magic_defense()
        
        # 基础伤害
        raw_damage = atk
        
        # 防御减伤
        damage_reduction = defense / (defense + 100)
        damage_reduction = min(0.75, damage_reduction)
        
        final_damage = int(raw_damage * (1 - damage_reduction))
        
        # 暴击判定
        is_crit = random.random() < attacker.get_effective_critical_rate()
        if is_crit:
            final_damage = int(final_damage * attacker.critical_damage)
        
        # 伤害浮动
        damage_variance = random.uniform(0.9, 1.1)
        final_damage = int(final_damage * damage_variance)
        
        # 最小伤害
        final_damage = max(1, final_damage)
        
        return (final_damage, is_crit, damage_type)
    
    def _apply_damage(self, target: CombatStats, damage: int) -> int:
        """应用伤害（优先扣护盾）
        
        Returns:
            实际造成的伤害
        """
        actual_damage = damage
        
        # 优先扣护盾
        if target.shield > 0:
            if target.shield >= damage:
                target.shield -= damage
                return 0  # 护盾完全吸收
            else:
                actual_damage = damage - target.shield
                target.shield = 0
        
        # 扣除HP
        target.hp = max(0, target.hp - actual_damage)
        
        return actual_damage
    
    def _apply_skill_effect(self, attacker: CombatStats, defender: CombatStats,
                            effect: dict, tag: str) -> List[str]:
        """应用技能效果"""
        logs = []
        effect_type = effect.get("type", "")
        value = effect.get("value", 0)
        duration = effect.get("duration", 1)
        chance = effect.get("chance", 1.0)
        
        # 概率判定
        if random.random() > chance:
            return logs
        
        # 控制效果
        if effect_type in ["stun", "freeze", "paralysis"]:
            defender.debuffs.append({
                "type": effect_type,
                "duration": duration,
                "value": value
            })
            effect_names = {
                "stun": "眩晕",
                "freeze": "冰冻",
                "paralysis": "麻痹"
            }
            logs.append(f"{tag} {defender.name} 陷入{effect_names[effect_type]}状态！({duration}回合)")
        
        # 混乱
        elif effect_type == "confusion":
            defender.debuffs.append({
                "type": "confusion",
                "duration": duration,
                "value": value
            })
            logs.append(f"{tag} {defender.name} 陷入混乱状态！({duration}回合)")
        
        # 持续伤害
        elif effect_type in ["bleed", "burn", "poison"]:
            defender.debuffs.append({
                "type": effect_type,
                "duration": duration,
                "value": value,
                "source": attacker.name
            })
            effect_names = {
                "bleed": "流血",
                "burn": "灼烧",
                "poison": "中毒"
            }
            logs.append(f"{tag} {defender.name} 进入{effect_names[effect_type]}状态！({duration}回合)")
        
        # 减速
        elif effect_type == "slow":
            defender.debuffs.append({
                "type": "slow",
                "duration": duration,
                "value": value
            })
            logs.append(f"{tag} {defender.name} 被减速！({duration}回合)")
        
        # 破甲/破法
        elif effect_type in ["armor_break", "magic_break"]:
            defender.debuffs.append({
                "type": effect_type,
                "duration": duration,
                "value": value
            })
            effect_names = {
                "armor_break": "破甲",
                "magic_break": "破法"
            }
            logs.append(f"{tag} {defender.name} 被{effect_names[effect_type]}！({duration}回合)")
        
        # 增益效果（给自己）
        elif effect_type in ["defense_boost", "attack_boost", "dodge_boost", "critical_boost", "speed_boost"]:
            attacker.buffs.append({
                "type": effect_type,
                "duration": duration,
                "value": value
            })
            effect_names = {
                "defense_boost": "防御提升",
                "attack_boost": "攻击提升",
                "dodge_boost": "闪避提升",
                "critical_boost": "暴击提升",
                "speed_boost": "速度提升"
            }
            logs.append(f"{tag} {attacker.name} 获得{effect_names[effect_type]}！({duration}回合)")
        
        # 护盾
        elif effect_type == "shield":
            shield_amount = int(attacker.max_hp * value) if value < 1 else int(value)
            attacker.shield += shield_amount
            logs.append(f"{tag} {attacker.name} 获得 {shield_amount} 点护盾！")
        
        # 治疗
        elif effect_type == "heal":
            heal_amount = int(attacker.max_hp * value) if value < 1 else int(value)
            attacker.hp = min(attacker.max_hp, attacker.hp + heal_amount)
            logs.append(f"{tag} {attacker.name} 恢复了 {heal_amount} 点生命！")
        
        # 自伤
        elif effect_type == "self_damage":
            self_damage = int(attacker.max_hp * value) if value < 1 else int(value)
            self._apply_damage(attacker, self_damage)
            logs.append(f"{tag} {attacker.name} 受到 {self_damage} 点反噬伤害！")
        
        # 真元燃烧
        elif effect_type == "mp_burn":
            mp_burn = int(defender.max_mp * value) if value < 1 else int(value)
            defender.mp = max(0, defender.mp - mp_burn)
            logs.append(f"{tag} {defender.name} 损失了 {mp_burn} 点真元！")
        
        # 净化（移除debuff）
        elif effect_type == "purify":
            if attacker.debuffs:
                removed = attacker.debuffs.pop(0)
                logs.append(f"{tag} {attacker.name} 净化了一个负面效果！")
        
        return logs
    
    def _process_dot_effects(self, target: CombatStats) -> List[str]:
        """处理持续效果（回合开始时）"""
        logs = []
        
        for debuff in target.debuffs:
            effect_type = debuff.get("type", "")
            value = debuff.get("value", 0)
            
            if effect_type == "bleed":
                damage = int(target.max_hp * value) if value < 1 else int(value)
                self._apply_damage(target, damage)
                logs.append(f"{target.name} 流血造成 {damage} 点伤害！")
            
            elif effect_type == "burn":
                damage = int(target.max_hp * value) if value < 1 else int(value)
                self._apply_damage(target, damage)
                logs.append(f"{target.name} 灼烧造成 {damage} 点伤害！")
            
            elif effect_type == "poison":
                damage = int(target.max_hp * value) if value < 1 else int(value)
                self._apply_damage(target, damage)
                logs.append(f"{target.name} 中毒造成 {damage} 点伤害！")
        
        return logs
    
    def _update_effects_duration(self, stats: CombatStats):
        """更新buff/debuff持续时间"""
        # 更新buff
        remaining_buffs = []
        for buff in stats.buffs:
            buff["duration"] -= 1
            if buff["duration"] > 0:
                remaining_buffs.append(buff)
        stats.buffs = remaining_buffs
        
        # 更新debuff
        remaining_debuffs = []
        for debuff in stats.debuffs:
            debuff["duration"] -= 1
            if debuff["duration"] > 0:
                remaining_debuffs.append(debuff)
        stats.debuffs = remaining_debuffs
    
    def _update_cooldowns(self, stats: CombatStats):
        """更新技能冷却"""
        for skill_id in list(stats.skill_cooldowns.keys()):
            stats.skill_cooldowns[skill_id] -= 1
            if stats.skill_cooldowns[skill_id] <= 0:
                del stats.skill_cooldowns[skill_id]
    
    def generate_battle_summary(self, battle_result: dict, 
                                include_full_log: bool = False) -> str:
        """生成战斗摘要
        
        Args:
            battle_result: execute_battle的返回结果
            include_full_log: 是否包含完整战斗日志
        
        Returns:
            格式化的战斗摘要文本
        """
        lines = []
        
        p1 = battle_result["p1_final"]
        p2 = battle_result["p2_final"]
        rounds = battle_result["rounds"]
        
        lines.append("═══════════════════════")
        lines.append("       ⚔️ 战斗结果 ⚔️")
        lines.append("═══════════════════════")
        lines.append("")
        
        if battle_result["is_draw"]:
            lines.append("🤝 结果：平局")
        else:
            winner_name = p1["name"] if battle_result["winner"] == p1["user_id"] else p2["name"]
            lines.append(f"🏆 胜者：{winner_name}")
        
        lines.append(f"⏱️ 回合数：{rounds}")
        lines.append("")
        lines.append("━━━ 最终状态 ━━━")
        lines.append(f"🔵 {p1['name']}: HP {p1['hp']}/{p1['max_hp']}")
        lines.append(f"🔴 {p2['name']}: HP {p2['hp']}/{p2['max_hp']}")
        
        if include_full_log:
            lines.append("")
            lines.append("━━━ 战斗日志 ━━━")
            lines.extend(battle_result["log"])
        
        return "\n".join(lines)
