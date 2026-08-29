# core/breakthrough_manager.py

import random
from typing import Optional, Tuple
from astrbot.api import logger

from ..models import Player
from ..data import DataBase
from ..config_manager import ConfigManager
from .battle_manager import BattleManager, CombatStats
from .cultivation_manager import CultivationManager


BREAKTHROUGH_PILL_REDUCTION_RATIO = 0.58
TEMP_BONUS_REDUCTION_RATIO = 0.38
MIN_DEMON_DIFFICULTY = 0.70
MAX_DEMON_DIFFICULTY = 2.30
DANGER_TIER_LABELS = (
    (0.95, "简单", "🟢"),
    (1.20, "普通", "🟡"),
    (1.50, "困难", "🟠"),
    (1.85, "极难", "🔴"),
    (999, "地狱", "💀"),
)


class BreakthroughManager:
    """突破管理器 - 处理境界突破相关逻辑"""

    def __init__(self, db: DataBase, config_manager: ConfigManager, config: dict):
        self.db = db
        self.config_manager = config_manager
        self.config = config
        self.battle_manager = BattleManager(config_manager)
        self.cultivation_manager = CultivationManager(config, config_manager)

    def _get_pill_data(self, pill_name: str) -> Optional[dict]:
        """获取丹药配置数据（从多个数据源查找）
        
        Args:
            pill_name: 丹药名称
            
        Returns:
            丹药配置字典，如果找不到返回None
        """
        # 优先从 pills_data 查找（专门的破境丹配置）
        pill_data = self.config_manager.pills_data.get(pill_name)
        if pill_data:
            return pill_data
        
        # 从 items_data 查找（items.json 中的丹药）
        item_data = self.config_manager.items_data.get(pill_name)
        if item_data and item_data.get("type") == "丹药":
            return item_data
        
        # 从 exp_pills_data 查找
        exp_pill = self.config_manager.exp_pills_data.get(pill_name)
        if exp_pill:
            return exp_pill
        
        # 从 utility_pills_data 查找
        utility_pill = self.config_manager.utility_pills_data.get(pill_name)
        if utility_pill:
            return utility_pill
        
        return None

    def _is_breakthrough_pill(self, pill_data: dict) -> bool:
        """判断是否为破境丹
        
        Args:
            pill_data: 丹药配置数据
            
        Returns:
            是否为破境丹
        """
        subtype = pill_data.get("subtype", "")
        # 支持多种破境丹类型标识
        return subtype in {"breakthrough", "breakthrough_boost", "breakthrough_debuff"}

    def _get_breakthrough_bonus(self, pill_data: dict) -> float:
        """获取破境丹的突破加成值
        
        Args:
            pill_data: 丹药配置数据
            
        Returns:
            突破加成值（0.0 ~ 1.0）
        """
        # 优先从顶层 breakthrough_bonus 获取
        bonus = pill_data.get("breakthrough_bonus", 0)
        if bonus > 0:
            return bonus
        
        # 从 effect.add_breakthrough_bonus 获取（items.json 格式）
        effect = pill_data.get("effect", {})
        if isinstance(effect, dict):
            bonus = effect.get("add_breakthrough_bonus", 0)
            if bonus > 0:
                return bonus
        
        return 0.0

    def get_cultivation_speed(self, player: Player) -> float:
        """获取玩家的基础修炼速度
        
        Args:
            player: 玩家对象
            
        Returns:
            修炼速度倍率 (0.5 ~ 2.0)
        """
        speed = self.cultivation_manager.get_spiritual_root_speed(player)
        return max(0.5, min(2.0, speed))

    def _get_level_difficulty_base(self, level_index: int) -> float:
        """按境界返回心魔基础难度阶梯。"""
        if level_index <= 2:
            return 0.80 + level_index * 0.035
        if level_index <= 6:
            return 0.90 + (level_index - 3) * 0.045
        if level_index <= 10:
            return 1.05 + (level_index - 7) * 0.05
        if level_index <= 15:
            return 1.20 + (level_index - 11) * 0.05
        if level_index <= 20:
            return 1.43 + (level_index - 16) * 0.05
        return min(1.88, 1.68 + (level_index - 21) * 0.035)

    def _get_speed_difficulty_modifier(self, cultivation_speed: float) -> float:
        """根据资质/体质倍率给心魔难度附加偏移。"""
        delta = cultivation_speed - 1.0
        if delta < 0:
            modifier = abs(delta) * 0.30
            if cultivation_speed < 0.8:
                modifier += 0.02
        else:
            modifier = delta * 0.16
            if cultivation_speed > 1.5:
                modifier += min(0.03, (cultivation_speed - 1.5) * 0.06)

        return modifier

    def calculate_demon_difficulty(self, cultivation_speed: float, level_index: int) -> float:
        """计算心魔难度系数
        
        Args:
            cultivation_speed: 修炼速度 (0.5 ~ 2.0)
            level_index: 当前境界索引
            
        Returns:
            难度系数 (越高越难)
        """
        level_base = self._get_level_difficulty_base(level_index)
        speed_modifier = self._get_speed_difficulty_modifier(cultivation_speed)
        difficulty = level_base + speed_modifier
        return max(MIN_DEMON_DIFFICULTY, min(MAX_DEMON_DIFFICULTY, difficulty))

    def _get_difficulty_rating(self, difficulty: float) -> Tuple[str, str]:
        for threshold, rating, color in DANGER_TIER_LABELS:
            if difficulty < threshold:
                return rating, color
        return "地狱", "💀"

    def _calculate_difficulty_reduction(
        self,
        pill_name: Optional[str] = None,
        temp_bonus: float = 0.0
    ) -> Tuple[float, str, float]:
        """统一计算突破时的减难值与说明。"""
        difficulty_reduction = 0.0
        pill_info = ""
        breakthrough_bonus = 0.0

        if pill_name:
            pill_data = self._get_pill_data(pill_name)
            if pill_data and self._is_breakthrough_pill(pill_data):
                breakthrough_bonus = self._get_breakthrough_bonus(pill_data)
                if breakthrough_bonus > 0:
                    difficulty_reduction += breakthrough_bonus * BREAKTHROUGH_PILL_REDUCTION_RATIO
                    pill_info = (
                        f"\n💊 使用【{pill_name}】，心魔力量被压制！"
                        f"(突破加成+{breakthrough_bonus:.0%})"
                    )

        if temp_bonus > 0:
            difficulty_reduction += temp_bonus * TEMP_BONUS_REDUCTION_RATIO

        return difficulty_reduction, pill_info, breakthrough_bonus

    def _build_difficulty_info(
        self,
        player: Player,
        pill_name: Optional[str] = None,
        temp_bonus: float = 0.0
    ) -> dict:
        """生成统一的心魔难度信息，供展示与实战复用。"""
        cultivation_speed = self.get_cultivation_speed(player)
        base_difficulty = self.calculate_demon_difficulty(cultivation_speed, player.level_index)
        difficulty_reduction, pill_info, breakthrough_bonus = self._calculate_difficulty_reduction(
            pill_name, temp_bonus
        )
        final_difficulty = max(MIN_DEMON_DIFFICULTY, base_difficulty - difficulty_reduction)
        difficulty_rating, difficulty_color = self._get_difficulty_rating(final_difficulty)

        return {
            "cultivation_speed": cultivation_speed,
            "base_difficulty": base_difficulty,
            "difficulty_reduction": difficulty_reduction,
            "final_difficulty": final_difficulty,
            "difficulty_rating": difficulty_rating,
            "difficulty_color": difficulty_color,
            "pill_info": pill_info,
            "breakthrough_bonus": breakthrough_bonus,
        }

    def create_demon_stats(
        self,
        player: Player,
        difficulty: float,
        player_stats: Optional[CombatStats] = None
    ) -> CombatStats:
        """创建心魔的战斗属性
        
        心魔的属性基于玩家属性和难度系数计算（已降低整体属性）
        
        Args:
            player: 玩家对象
            difficulty: 难度系数
            
        Returns:
            心魔的战斗属性
        """
        if player_stats is None:
            player_stats = self.battle_manager.prepare_combat_stats(player)

        level_stage = min(0.22, player.level_index * 0.0085)
        difficulty_offset = max(0.0, difficulty - 1.0)

        hp_scale = min(1.16, 0.80 + level_stage + difficulty_offset * 0.26)
        mp_scale = min(1.02, 0.70 + level_stage * 0.65 + difficulty_offset * 0.18)
        atk_scale = min(1.08, 0.74 + level_stage * 0.75 + difficulty_offset * 0.30)
        def_scale = min(0.97, 0.66 + level_stage * 0.58 + difficulty_offset * 0.20)
        speed_scale = min(0.97, 0.86 + level_stage * 0.15 + difficulty_offset * 0.07)

        physical_attack_scale = atk_scale
        magic_attack_scale = atk_scale
        physical_defense_scale = def_scale
        magic_defense_scale = def_scale

        if player.cultivation_type == "体修":
            physical_attack_scale += 0.05
            physical_defense_scale += 0.04
            magic_attack_scale -= 0.04
            magic_defense_scale -= 0.02
        else:
            magic_attack_scale += 0.05
            magic_defense_scale += 0.03
            physical_attack_scale -= 0.02

        demon_hp = max(1, int(player_stats.max_hp * hp_scale))
        demon_mp = max(1, int(player_stats.max_mp * mp_scale))
        demon_physical_attack = max(1, int(player_stats.physical_attack * physical_attack_scale))
        demon_magic_attack = max(1, int(player_stats.magic_attack * magic_attack_scale))
        demon_physical_defense = max(0, int(player_stats.physical_defense * physical_defense_scale))
        demon_magic_defense = max(0, int(player_stats.magic_defense * magic_defense_scale))
        demon_speed = max(1, int(player_stats.speed * speed_scale))

        demon_critical_rate = min(0.12, 0.028 + player.level_index * 0.002 + difficulty_offset * 0.01)
        demon_critical_damage = min(1.28, 1.12 + difficulty_offset * 0.06)
        demon_dodge_rate = min(0.08, 0.012 + player.level_index * 0.0012 + difficulty_offset * 0.005)

        demon_skills = self._get_demon_skills(player.level_index, difficulty)
        
        return CombatStats(
            user_id="demon",
            name="心魔",
            hp=demon_hp,
            max_hp=demon_hp,
            mp=demon_mp,
            max_mp=demon_mp,
            physical_attack=demon_physical_attack,
            magic_attack=demon_magic_attack,
            physical_defense=demon_physical_defense,
            magic_defense=demon_magic_defense,
            speed=demon_speed,
            critical_rate=demon_critical_rate,
            critical_damage=demon_critical_damage,
            hit_rate=0.85,  # 从0.9降低到0.85
            dodge_rate=demon_dodge_rate,
            skills=demon_skills,
            skill_cooldowns={},
            shield=0,
            buffs=[],
            debuffs=[]
        )

    def _get_demon_skills(self, level_index: int, difficulty: float = 1.0) -> list:
        """根据境界获取心魔的技能（已降低技能伤害）
        
        Args:
            level_index: 玩家当前境界索引
            
        Returns:
            心魔技能列表
        """
        skills = []
        stage_bonus = min(0.18, level_index * 0.006)
        difficulty_bonus = max(0.0, difficulty - 1.0)
        
        # 基础技能：心魔冲击（降低伤害）
        base_skill = {
            "id": "demon_strike",
            "name": "心魔冲击",
            "type": "active",
            "damage_type": "magic",
            "mp_cost": 15,
            "cooldown": 0,
            "damage": {
                "base": 7 + level_index + int(difficulty_bonus * 4),
                "attack_ratio": round(min(1.08, 0.90 + stage_bonus + difficulty_bonus * 0.05), 2)
            },
            "effects": []
        }
        skills.append(base_skill)
        
        # 筑基期以上：添加恐惧技能（降低伤害和效果）
        if level_index >= 10:
            fear_skill = {
                "id": "demon_fear",
                "name": "心魔恐惧",
                "type": "active",
                "damage_type": "magic",
                "mp_cost": 25,
                "cooldown": 3,  # 从2增加到3
                "damage": {
                    "base": 10 + level_index * 2 + int(difficulty_bonus * 6),
                    "attack_ratio": round(min(1.15, 0.98 + stage_bonus * 0.7 + difficulty_bonus * 0.05), 2)
                },
                "effects": [
                    {
                        "type": "slow",
                        "value": round(min(0.18, 0.12 + stage_bonus * 0.16), 2),
                        "duration": 2,
                        "chance": round(min(0.46, 0.34 + difficulty_bonus * 0.04), 2)
                    }
                ]
            }
            skills.append(fear_skill)
        
        # 金丹期以上：添加心魔侵蚀（降低伤害和效果）
        if level_index >= 13:
            erosion_skill = {
                "id": "demon_erosion",
                "name": "心魔侵蚀",
                "type": "active",
                "damage_type": "magic",
                "mp_cost": 35,
                "cooldown": 4,  # 从3增加到4
                "damage": {
                    "base": 14 + level_index * 2 + int(difficulty_bonus * 8),
                    "attack_ratio": round(min(1.26, 1.08 + stage_bonus * 0.7 + difficulty_bonus * 0.06), 2)
                },
                "effects": [
                    {
                        "type": "poison",
                        "value": round(min(0.03, 0.02 + stage_bonus * 0.03), 2),
                        "duration": 2,
                        "chance": round(min(0.52, 0.42 + difficulty_bonus * 0.05), 2)
                    }
                ]
            }
            skills.append(erosion_skill)
        
        # 元婴期以上：添加心魔吞噬（降低伤害和效果）
        if level_index >= 16:
            devour_skill = {
                "id": "demon_devour",
                "name": "心魔吞噬",
                "type": "active",
                "damage_type": "magic",
                "mp_cost": 50,
                "cooldown": 5,  # 从4增加到5
                "damage": {
                    "base": 18 + level_index * 3 + int(difficulty_bonus * 10),
                    "attack_ratio": round(min(1.38, 1.20 + stage_bonus * 0.75 + difficulty_bonus * 0.05), 2)
                },
                "effects": [
                    {
                        "type": "mp_burn",
                        "value": round(min(0.07, 0.05 + stage_bonus * 0.04), 2),
                        "chance": round(min(0.54, 0.44 + difficulty_bonus * 0.04), 2)
                    }
                ],
                "lifesteal": round(min(0.17, 0.12 + difficulty_bonus * 0.02), 2)
            }
            skills.append(devour_skill)
        
        # 化神期以上：添加心魔幻境（降低伤害和效果）
        if level_index >= 19:
            illusion_skill = {
                "id": "demon_illusion",
                "name": "心魔幻境",
                "type": "active",
                "damage_type": "magic",
                "mp_cost": 60,
                "cooldown": 6,  # 从5增加到6
                "damage": {
                    "base": 24 + level_index * 4 + int(difficulty_bonus * 10),
                    "attack_ratio": round(min(1.52, 1.30 + stage_bonus * 0.7 + difficulty_bonus * 0.05), 2)
                },
                "effects": [
                    {
                        "type": "confusion",
                        "duration": 1,
                        "chance": round(min(0.32, 0.22 + difficulty_bonus * 0.03), 2)
                    }
                ]
            }
            skills.append(illusion_skill)
        
        return skills

    def check_breakthrough_requirements(self, player: Player) -> Tuple[bool, str]:
        """检查玩家是否满足突破条件

        Args:
            player: 玩家对象

        Returns:
            (是否满足, 错误消息)
        """
        # 根据修炼类型获取对应的境界数据
        level_data = self.config_manager.get_level_data(player.cultivation_type)

        # 检查是否已经是最高境界
        if player.level_index >= len(level_data) - 1:
            return False, "你已经达到了最高境界，无法继续突破！"

        # 获取下一境界所需修为
        next_level_index = player.level_index + 1
        next_level_data = level_data[next_level_index]
        required_exp = next_level_data.get("exp_needed", 0)

        # 检查修为是否满足
        if player.experience < required_exp:
            current_level = level_data[player.level_index]["level_name"]
            next_level = next_level_data["level_name"]
            return False, (
                f"修为不足！\n"
                f"当前境界：{current_level}\n"
                f"当前修为：{player.experience}\n"
                f"突破至【{next_level}】需要修为：{required_exp}"
            )

        return True, ""

    def get_breakthrough_info(self, player: Player, temp_bonus: float = 0.0) -> dict:
        """获取突破信息，包括心魔难度预估
        
        Args:
            player: 玩家对象
            
        Returns:
            突破信息字典
        """
        level_data = self.config_manager.get_level_data(player.cultivation_type)
        
        if player.level_index >= len(level_data) - 1:
            return {"error": "已达最高境界"}
        
        current_level_data = level_data[player.level_index]
        next_level_data = level_data[player.level_index + 1]
        
        difficulty_info = self._build_difficulty_info(player, temp_bonus=temp_bonus)
        
        return {
            "current_level": current_level_data["level_name"],
            "next_level": next_level_data["level_name"],
            "required_exp": next_level_data.get("exp_needed", 0),
            "current_exp": player.experience,
            "cultivation_speed": difficulty_info["cultivation_speed"],
            "difficulty": difficulty_info["final_difficulty"],
            "base_difficulty": difficulty_info["base_difficulty"],
            "difficulty_reduction": difficulty_info["difficulty_reduction"],
            "difficulty_rating": difficulty_info["difficulty_rating"],
            "difficulty_color": difficulty_info["difficulty_color"],
            "spiritual_root": player.spiritual_root,
        }

    async def execute_breakthrough(
        self,
        player: Player,
        pill_name: Optional[str] = None,
        temp_bonus: float = 0.0,
        death_rate_multiplier: float = 1.0,
        equipment_manager=None,
        skill_manager=None
    ) -> Tuple[bool, str, bool, Optional[dict]]:
        """执行突破 - 与心魔战斗

        Args:
            player: 玩家对象
            pill_name: 使用的破境丹名称（可选，降低心魔难度）
            temp_bonus: 临时加成（降低心魔属性）
            death_rate_multiplier: 死亡率倍率
            equipment_manager: 装备管理器
            skill_manager: 技能管理器

        Returns:
            (是否成功, 消息, 是否死亡, 战斗结果)
        """
        # 检查突破条件
        can_breakthrough, error_msg = self.check_breakthrough_requirements(player)
        if not can_breakthrough:
            return False, error_msg, False, None

        # 根据修炼类型获取对应的境界数据
        level_data = self.config_manager.get_level_data(player.cultivation_type)
        current_level_name = level_data[player.level_index]["level_name"]
        next_level_index = player.level_index + 1
        next_level_data = level_data[next_level_index]
        next_level_name = next_level_data["level_name"]

        difficulty_info = self._build_difficulty_info(player, pill_name, temp_bonus)
        base_difficulty = difficulty_info["base_difficulty"]
        difficulty_reduction = difficulty_info["difficulty_reduction"]
        final_difficulty = difficulty_info["final_difficulty"]
        pill_info = difficulty_info["pill_info"]

        if difficulty_info["breakthrough_bonus"] > 0:
            logger.info(
                f"玩家 {player.user_id} 使用破境丹【{pill_name}】，"
                f"突破加成: {difficulty_info['breakthrough_bonus']:.0%}"
            )

        logger.info(f"玩家 {player.user_id} 突破心魔难度: 基础={base_difficulty:.2f}, 减免={difficulty_reduction:.2f}, 最终={final_difficulty:.2f}")

        # 准备玩家战斗属性
        player_stats = self.battle_manager.prepare_combat_stats(
            player, equipment_manager, skill_manager
        )

        # 创建心魔
        demon_stats = self.create_demon_stats(player, final_difficulty, player_stats)
        
        # 执行战斗
        battle_result = self.battle_manager.execute_battle(
            player_stats, demon_stats, battle_type="duel"
        )
        
        # 判断战斗结果
        player_won = battle_result["winner"] == player.user_id
        
        if player_won:
            # 突破成功
            return await self._handle_breakthrough_success(
                player, level_data, current_level_name, next_level_index, 
                next_level_data, next_level_name, pill_info, battle_result,
                player_stats, demon_stats
            )
        else:
            # 突破失败
            return await self._handle_breakthrough_failure(
                player, current_level_name, next_level_name, 
                death_rate_multiplier, pill_info, battle_result,
                player_stats, demon_stats
            )

    async def _handle_breakthrough_success(
        self, player: Player, level_data: list, current_level_name: str,
        next_level_index: int, next_level_data: dict, next_level_name: str,
        pill_info: str, battle_result: dict,
        player_stats: CombatStats, demon_stats: CombatStats
    ) -> Tuple[bool, str, bool, dict]:
        """处理突破成功"""
        
        player.level_index = next_level_index

        # 直接从下一境界配置中读取突破增量
        lifespan_gain = next_level_data.get("breakthrough_lifespan_gain", 0)
        mental_power_gain = next_level_data.get("breakthrough_mental_power_gain", 0)
        physical_damage_gain = next_level_data.get("breakthrough_physical_damage_gain", 0)
        magic_damage_gain = next_level_data.get("breakthrough_magic_damage_gain", 0)
        physical_defense_gain = next_level_data.get("breakthrough_physical_defense_gain", 0)
        magic_defense_gain = next_level_data.get("breakthrough_magic_defense_gain", 0)
        
        # 战斗属性增益
        hp_gain = next_level_data.get("breakthrough_hp_gain", 0)
        mp_gain = next_level_data.get("breakthrough_mp_gain", 0)
        speed_gain = next_level_data.get("breakthrough_speed_gain", 0)

        # 根据修炼类型处理灵气/气血增长
        if player.cultivation_type == "体修":
            blood_qi_gain = next_level_data.get("breakthrough_blood_qi_gain", 0)
            energy_name = "气血"
            energy_gain = blood_qi_gain
        else:
            spiritual_qi_gain = next_level_data.get("breakthrough_spiritual_qi_gain", 0)
            energy_name = "灵气"
            energy_gain = spiritual_qi_gain

        # 记录原始值用于调试
        original_gains = {
            "lifespan": lifespan_gain,
            "mental_power": mental_power_gain,
            "physical_damage": physical_damage_gain,
            "magic_damage": magic_damage_gain,
            "physical_defense": physical_defense_gain,
            "magic_defense": magic_defense_gain,
            "hp": hp_gain,
            "mp": mp_gain,
            "speed": speed_gain,
            "energy": energy_gain
        }

        # 获取功法配置并应用成长修正
        technique_config = None
        modifier_info = ""
        applied_modifiers = {}
        
        if player.main_technique:
            technique_config = self.config_manager.get_technique_by_name(player.main_technique)
            if technique_config:
                modifiers = technique_config.get("growth_modifiers", {})
                technique_name = technique_config.get("name", player.main_technique)
                
                # 记录日志：功法加成信息
                logger.info(f"玩家 {player.user_id} 功法【{technique_name}】成长修正: {modifiers}")
                
                # 应用功法成长修正并记录
                if modifiers.get("lifespan", 1.0) != 1.0:
                    applied_modifiers["寿命"] = modifiers.get("lifespan", 1.0)
                lifespan_gain = int(lifespan_gain * modifiers.get("lifespan", 1.0))
                
                if modifiers.get("mental_power", 1.0) != 1.0:
                    applied_modifiers["精神力"] = modifiers.get("mental_power", 1.0)
                mental_power_gain = int(mental_power_gain * modifiers.get("mental_power", 1.0))
                
                if modifiers.get("physical_attack", 1.0) != 1.0:
                    applied_modifiers["物伤"] = modifiers.get("physical_attack", 1.0)
                physical_damage_gain = int(physical_damage_gain * modifiers.get("physical_attack", 1.0))
                
                if modifiers.get("magic_attack", 1.0) != 1.0:
                    applied_modifiers["法伤"] = modifiers.get("magic_attack", 1.0)
                magic_damage_gain = int(magic_damage_gain * modifiers.get("magic_attack", 1.0))
                
                if modifiers.get("physical_defense", 1.0) != 1.0:
                    applied_modifiers["物防"] = modifiers.get("physical_defense", 1.0)
                physical_defense_gain = int(physical_defense_gain * modifiers.get("physical_defense", 1.0))
                
                if modifiers.get("magic_defense", 1.0) != 1.0:
                    applied_modifiers["法防"] = modifiers.get("magic_defense", 1.0)
                magic_defense_gain = int(magic_defense_gain * modifiers.get("magic_defense", 1.0))
                
                if modifiers.get("hp", 1.0) != 1.0:
                    applied_modifiers["HP"] = modifiers.get("hp", 1.0)
                hp_gain = int(hp_gain * modifiers.get("hp", 1.0))
                
                if modifiers.get("mp", 1.0) != 1.0:
                    applied_modifiers["MP"] = modifiers.get("mp", 1.0)
                mp_gain = int(mp_gain * modifiers.get("mp", 1.0))
                
                if modifiers.get("speed", 1.0) != 1.0:
                    applied_modifiers["速度"] = modifiers.get("speed", 1.0)
                speed_gain = int(speed_gain * modifiers.get("speed", 1.0))
                
                if player.cultivation_type == "体修":
                    blood_qi_modifier = modifiers.get("blood_qi", modifiers.get("hp", 1.0))
                    if blood_qi_modifier != 1.0:
                        applied_modifiers["气血"] = blood_qi_modifier
                    blood_qi_gain = int(blood_qi_gain * blood_qi_modifier)
                    energy_gain = blood_qi_gain
                else:
                    spiritual_qi_modifier = modifiers.get("spiritual_qi", modifiers.get("mp", 1.0))
                    if spiritual_qi_modifier != 1.0:
                        applied_modifiers["灵气"] = spiritual_qi_modifier
                    spiritual_qi_gain = int(spiritual_qi_gain * spiritual_qi_modifier)
                    energy_gain = spiritual_qi_gain
                
                # 生成详细的功法加成信息
                if applied_modifiers:
                    modifier_details = ", ".join([f"{k}×{v}" for k, v in applied_modifiers.items()])
                    modifier_info = f"\n💫 功法【{technique_name}】加成: {modifier_details}"
                    logger.info(f"玩家 {player.user_id} 功法加成应用: {applied_modifiers}")
                else:
                    modifier_info = f"\n💫 功法【{technique_name}】已装备"
                    logger.info(f"玩家 {player.user_id} 功法【{technique_name}】无额外成长加成")
            else:
                logger.warning(f"玩家 {player.user_id} 主修功法【{player.main_technique}】配置未找到")

        # 记录最终增益值
        logger.info(f"玩家 {player.user_id} 突破属性增益 - 原始: {original_gains}, "
                   f"最终: lifespan={lifespan_gain}, hp={hp_gain}, mp={mp_gain}, "
                   f"physical_damage={physical_damage_gain}, magic_damage={magic_damage_gain}")

        # 应用属性增长
        player.lifespan += lifespan_gain
        player.physical_damage += physical_damage_gain
        player.magic_damage += magic_damage_gain
        player.physical_defense += physical_defense_gain
        player.magic_defense += magic_defense_gain
        player.mental_power += mental_power_gain
        
        # 应用战斗属性增长
        player.max_hp += hp_gain
        player.hp = player.max_hp
        player.max_mp += mp_gain
        player.mp = player.max_mp
        player.speed += speed_gain

        # 根据修炼类型应用灵气/气血增长
        if player.cultivation_type == "体修":
            player.max_blood_qi += blood_qi_gain
            player.blood_qi = player.max_blood_qi
        else:
            player.max_spiritual_qi += spiritual_qi_gain
            player.spiritual_qi = player.max_spiritual_qi

        # 保存到数据库
        await self.db.update_player(player)
        
        # 检查并处理突破贷款自动还款
        loan_msg = await self._handle_breakthrough_loan_repay(player)

        # 生成详细战斗报告
        battle_report = self._generate_detailed_battle_report(
            battle_result, player_stats, demon_stats, player.user_name
        )

        # 根据修炼类型生成不同的成功消息
        if player.cultivation_type == "体修":
            success_msg = (
                f"⚔️ 心魔战斗 ⚔️{pill_info}\n"
                f"\n{battle_report}\n"
                f"\n✨ 突破成功！✨\n"
                f"━━━━━━━━━━━━━━━\n"
                f"恭喜你战胜心魔，从【{current_level_name}】突破至【{next_level_name}】！\n"
                f"境界提升，肉身更加强横！{modifier_info}\n"
                f"\n【属性增长】\n"
                f"寿命 +{lifespan_gain}\n"
                f"最大气血 +{energy_gain}\n"
                f"最大HP +{hp_gain}\n"
                f"最大MP +{mp_gain}\n"
                f"物伤 +{physical_damage_gain}\n"
                f"物防 +{physical_defense_gain}\n"
                f"法防 +{magic_defense_gain}\n"
                f"速度 +{speed_gain}\n"
                f"精神力 +{mental_power_gain}"
            )
        else:
            success_msg = (
                f"⚔️ 心魔战斗 ⚔️{pill_info}\n"
                f"\n{battle_report}\n"
                f"\n✨ 突破成功！✨\n"
                f"━━━━━━━━━━━━━━━\n"
                f"恭喜你战胜心魔，从【{current_level_name}】突破至【{next_level_name}】！\n"
                f"境界提升，实力大增！{modifier_info}\n"
                f"\n【属性增长】\n"
                f"寿命 +{lifespan_gain}\n"
                f"最大灵气 +{energy_gain}\n"
                f"最大HP +{hp_gain}\n"
                f"最大MP +{mp_gain}\n"
                f"法伤 +{magic_damage_gain}\n"
                f"物伤 +{physical_damage_gain}\n"
                f"法防 +{magic_defense_gain}\n"
                f"物防 +{physical_defense_gain}\n"
                f"速度 +{speed_gain}\n"
                f"精神力 +{mental_power_gain}"
            )

        logger.info(
            f"玩家 {player.user_id} 突破成功：{current_level_name} -> {next_level_name}"
            f"{' (功法加成: ' + technique_config.get('name', '') + ')' if technique_config else ''}"
        )
        
        if loan_msg:
            success_msg += f"\n\n{loan_msg}"

        return True, success_msg, False, battle_result

    async def _handle_breakthrough_failure(
        self, player: Player, current_level_name: str, next_level_name: str,
        death_rate_multiplier: float, pill_info: str, battle_result: dict,
        player_stats: CombatStats, demon_stats: CombatStats
    ) -> Tuple[bool, str, bool, dict]:
        """处理突破失败"""
        
        # 生成详细战斗报告
        battle_report = self._generate_detailed_battle_report(
            battle_result, player_stats, demon_stats, player.user_name
        )
        
        # 降低死亡概率（心魔战斗失败的死亡率比原来低）
        death_probability_range = self.config.get("VALUES", {}).get(
            "BREAKTHROUGH_DEATH_PROBABILITY",
            [0.01, 0.1]
        )
        
        # 心魔战斗失败，死亡概率降低60%（从50%提高到60%）
        death_rate = random.uniform(death_probability_range[0], death_probability_range[1])
        death_rate = death_rate * 0.4 * death_rate_multiplier  # 从0.5降低到0.4
        death_rate = max(0.0, min(0.4, death_rate))  # 最高40%死亡率（从50%降低）
        
        died = random.random() < death_rate

        if died:
            # 检查是否有回生丹效果
            from .pill_manager import PillManager
            pill_manager = PillManager(self.db, self.config_manager)
            resurrected = await pill_manager.handle_resurrection(player)

            if resurrected:
                resurrection_msg = (
                    f"⚔️ 心魔战斗 ⚔️{pill_info}\n"
                    f"\n{battle_report}\n"
                    f"\n💀 突破失败，心魔反噬！💀\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"你在突破【{next_level_name}】时被心魔击败，神魂受创...\n"
                    f"\n"
                    f"⚡ 回生丹效果触发！⚡\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"🌟 你涅槃重生了！\n"
                    f"⚠️ 但所有属性降低到之前的一半\n"
                    f"💊 回生丹效果已消耗\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"请继续修炼，重回巅峰！"
                )

                logger.info(f"玩家 {player.user_id} 突破失败触发回生丹，成功复活")
                return False, resurrection_msg, False, battle_result

            # 玩家死亡
            await self.db.delete_player_cascade(player.user_id)

            death_msg = (
                f"⚔️ 心魔战斗 ⚔️{pill_info}\n"
                f"\n{battle_report}\n"
                f"\n💀 突破失败，心魔吞噬！💀\n"
                f"━━━━━━━━━━━━━━━\n"
                f"你在突破【{next_level_name}】时被心魔彻底击败...\n"
                f"神魂被心魔吞噬，身死道消\n"
                f"所有修为和装备化为虚无\n"
                f"若想重新修仙，请使用'我要修仙'命令重新开始"
            )

            logger.info(
                f"玩家 {player.user_id} 突破失败并死亡：{current_level_name} -> {next_level_name}"
            )

            return False, death_msg, True, battle_result

        else:
            # 突破失败但未死亡（降低修为惩罚）
            exp_penalty = int(player.experience * 0.08)  # 从0.1降低到0.08
            player.experience = max(0, player.experience - exp_penalty)

            await self.db.update_player(player)

            fail_msg = (
                f"⚔️ 心魔战斗 ⚔️{pill_info}\n"
                f"\n{battle_report}\n"
                f"\n❌ 突破失败 ❌\n"
                f"━━━━━━━━━━━━━━━\n"
                f"你被心魔击败，但幸运地保住了性命\n"
                f"神魂受创，损失了 {exp_penalty} 点修为\n"
                f"当前修为：{player.experience}\n"
                f"━━━━━━━━━━━━━━━\n"
                f"💡 提示：提升实力或使用破境丹可降低心魔难度\n"
                f"请继续修炼，再接再厉！"
            )

            logger.info(
                f"玩家 {player.user_id} 突破失败：{current_level_name} -> {next_level_name}，"
                f"损失修为 {exp_penalty}"
            )

            return False, fail_msg, False, battle_result

    def _generate_detailed_battle_report(
        self, battle_result: dict, 
        player_stats: CombatStats, 
        demon_stats: CombatStats,
        player_name: str
    ) -> str:
        """生成详细的战斗报告
        
        Args:
            battle_result: 战斗结果
            player_stats: 玩家初始战斗属性
            demon_stats: 心魔初始战斗属性
            player_name: 玩家名称
            
        Returns:
            详细战斗报告文本
        """
        lines = []
        
        # 战斗开始信息
        lines.append("╔══════════════════════╗")
        lines.append("║     ⚔️ 心魔试炼 ⚔️     ║")
        lines.append("╚══════════════════════╝")
        lines.append("")
        
        # 双方初始属性
        lines.append("【双方属性】")
        lines.append(f"┌─ 🔵 {player_name}")
        lines.append(f"│  HP: {player_stats.max_hp} | MP: {player_stats.max_mp}")
        lines.append(f"│  物攻: {player_stats.physical_attack} | 法攻: {player_stats.magic_attack}")
        lines.append(f"│  物防: {player_stats.physical_defense} | 法防: {player_stats.magic_defense}")
        lines.append(f"│  速度: {player_stats.speed} | 暴击: {player_stats.critical_rate:.0%}")
        lines.append(f"└─────────────────")
        lines.append(f"┌─ 🔴 心魔")
        lines.append(f"│  HP: {demon_stats.max_hp} | MP: {demon_stats.max_mp}")
        lines.append(f"│  物攻: {demon_stats.physical_attack} | 法攻: {demon_stats.magic_attack}")
        lines.append(f"│  物防: {demon_stats.physical_defense} | 法防: {demon_stats.magic_defense}")
        lines.append(f"│  速度: {demon_stats.speed} | 暴击: {demon_stats.critical_rate:.0%}")
        lines.append(f"└─────────────────")
        lines.append("")
        
        # 战斗日志
        battle_log = battle_result.get("log", [])
        rounds = battle_result.get("rounds", 0)
        
        lines.append("【战斗经过】")
        lines.append("─" * 24)
        
        # 处理战斗日志，使其更易读
        current_round = 0
        for log_line in battle_log:
            # 跳过开始信息（已经在上面显示了）
            if "开始" in log_line and ("切磋" in log_line or "决斗" in log_line):
                continue
            if log_line.startswith("🔵") and "HP:" in log_line and "MP:" in log_line and log_line.count("/") >= 2:
                # 这是初始状态行，跳过
                continue
            if log_line.startswith("🔴") and "HP:" in log_line and "MP:" in log_line and log_line.count("/") >= 2:
                # 这是初始状态行，跳过
                continue
            
            # 回合标记
            if "第" in log_line and "回合" in log_line:
                current_round += 1
                lines.append("")
                lines.append(f"◆ 第{current_round}回合 ◆")
                continue
            
            # 空行跳过
            if not log_line.strip():
                continue
            
            # 替换标签使其更美观
            formatted_line = log_line
            formatted_line = formatted_line.replace("🔵", f"【{player_name}】")
            formatted_line = formatted_line.replace("🔴", "【心魔】")
            
            # 添加缩进
            if formatted_line.startswith("【"):
                lines.append(f"  {formatted_line}")
            else:
                lines.append(f"    {formatted_line}")
        
        lines.append("")
        lines.append("─" * 24)
        
        # 战斗结果
        p1_final = battle_result.get("p1_final", {})
        p2_final = battle_result.get("p2_final", {})
        
        player_hp = p1_final.get("hp", 0)
        player_max_hp = p1_final.get("max_hp", 1)
        demon_hp = p2_final.get("hp", 0)
        demon_max_hp = p2_final.get("max_hp", 1)
        
        player_hp_percent = int(player_hp / player_max_hp * 100)
        demon_hp_percent = int(demon_hp / demon_max_hp * 100)
        
        # 生成HP条
        player_hp_bar = self._generate_hp_bar(player_hp_percent)
        demon_hp_bar = self._generate_hp_bar(demon_hp_percent)
        
        lines.append("【战斗结果】")
        lines.append(f"总回合数：{rounds}")
        lines.append("")
        lines.append(f"🔵 {player_name}")
        lines.append(f"   {player_hp_bar} {player_hp}/{player_max_hp} ({player_hp_percent}%)")
        lines.append("")
        lines.append(f"🔴 心魔")
        lines.append(f"   {demon_hp_bar} {demon_hp}/{demon_max_hp} ({demon_hp_percent}%)")
        lines.append("")
        
        # 胜负判定
        if battle_result.get("is_draw"):
            lines.append("⚖️ 结果：同归于尽")
        elif battle_result.get("winner") == p1_final.get("user_id"):
            lines.append(f"🏆 胜者：{player_name}")
        else:
            lines.append("💀 胜者：心魔")
        
        return "\n".join(lines)

    def _generate_hp_bar(self, percent: int, length: int = 10) -> str:
        """生成HP条
        
        Args:
            percent: HP百分比 (0-100)
            length: HP条长度
            
        Returns:
            HP条字符串
        """
        filled = int(length * percent / 100)
        empty = length - filled
        
        if percent > 60:
            bar_char = "█"
        elif percent > 30:
            bar_char = "▓"
        else:
            bar_char = "░"
        
        return f"[{bar_char * filled}{'░' * empty}]"

    def _generate_battle_summary(self, battle_result: dict) -> str:
        """生成简短的战斗摘要（保留兼容性）"""
        rounds = battle_result.get("rounds", 0)
        p1 = battle_result.get("p1_final", {})
        p2 = battle_result.get("p2_final", {})
        
        player_hp = p1.get("hp", 0)
        player_max_hp = p1.get("max_hp", 1)
        demon_hp = p2.get("hp", 0)
        demon_max_hp = p2.get("max_hp", 1)
        
        player_hp_percent = int(player_hp / player_max_hp * 100)
        demon_hp_percent = int(demon_hp / demon_max_hp * 100)
        
        return (
            f"━━━ 战斗结束 ━━━\n"
            f"回合数：{rounds}\n"
            f"你的HP：{player_hp}/{player_max_hp} ({player_hp_percent}%)\n"
            f"心魔HP：{demon_hp}/{demon_max_hp} ({demon_hp_percent}%)"
        )

    async def _handle_breakthrough_loan_repay(self, player: Player) -> str:
        """处理突破贷款自动还款
        
        Args:
            player: 玩家对象
            
        Returns:
            还款消息（如果有贷款的话）
        """
        try:
            loan = await self.db.ext.get_active_loan(player.user_id)
            if not loan or loan["loan_type"] != "breakthrough":
                return ""
            
            import time
            now = int(time.time())
            days_borrowed = max(1, (now - loan["borrowed_at"]) // 86400)
            interest = int(loan["principal"] * loan["interest_rate"] * days_borrowed)
            total_due = loan["principal"] + interest
            
            if player.gold >= total_due:
                player.gold -= total_due
                await self.db.update_player(player)
                
                await self.db.ext.close_loan(loan["id"])
                
                bank_data = await self.db.ext.get_bank_account(player.user_id)
                balance = bank_data["balance"] if bank_data else 0
                await self.db.ext.add_bank_transaction(
                    player.user_id, "auto_repay", -total_due, balance,
                    f"突破成功自动还款：本金{loan['principal']:,}+利息{interest:,}", now
                )
                
                return (
                    f"💰 突破贷款自动还款成功！\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"已还本金：{loan['principal']:,} 灵石\n"
                    f"已还利息：{interest:,} 灵石\n"
                    f"当前持有：{player.gold:,} 灵石"
                )
            else:
                return (
                    f"⚠️ 你有未还清的突破贷款！\n"
                    f"应还金额：{total_due:,} 灵石\n"
                    f"当前持有：{player.gold:,} 灵石\n"
                    f"请尽快使用 /还款 命令还款"
                )
        except Exception as e:
            logger.warning(f"处理突破贷款自动还款异常: {e}")
            return ""

    # 保留旧方法的兼容性
    def calculate_breakthrough_success_rate(
        self,
        player: Player,
        pill_name: Optional[str] = None,
        temp_bonus: float = 0.0
    ) -> Tuple[float, str]:
        """计算突破成功率（已废弃，保留兼容性）"""
        info = self.get_breakthrough_info(player)
        if "error" in info:
            return 0.0, info["error"]
        
        return 0.5, f"心魔难度：{info['difficulty_color']} {info['difficulty_rating']}"
