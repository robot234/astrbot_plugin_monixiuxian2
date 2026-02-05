"""
技能管理器 - 处理技能学习、装备和效果计算
"""

from typing import Dict, List, Optional, Tuple
from astrbot.api import logger

from ..models import Player
from ..data import DataBase
from ..config_manager import ConfigManager


class SkillManager:
    """技能管理器"""
    
    MAX_EQUIPPED_SKILLS = 2  # 最大可装备技能数量
    
    def __init__(self, db: DataBase, config_manager: ConfigManager):
        self.db = db
        self.config_manager = config_manager
    
    def get_skill_by_id(self, skill_id: str) -> Optional[dict]:
        """根据技能ID获取技能配置"""
        return self.config_manager.get_skill_by_id(skill_id)
    
    def get_skill_by_name(self, skill_name: str) -> Optional[dict]:
        """根据技能名称获取技能配置"""
        return self.config_manager.get_skill_by_name(skill_name)
    
    def get_all_skills(self) -> Dict[str, dict]:
        """获取所有技能配置"""
        return self.config_manager.get_all_skills()
    
    def get_available_skills_for_player(self, player: Player) -> List[dict]:
        """获取玩家当前可学习的技能列表
        
        Args:
            player: 玩家对象
            
        Returns:
            可学习技能配置列表
        """
        all_skills = self.get_all_skills()
        learned_skills = player.get_learned_skills()
        available = []
        
        for skill_id, skill_config in all_skills.items():
            # 跳过已学会的技能
            if skill_id in learned_skills:
                continue
            
            # 检查境界要求
            required_level = skill_config.get("required_level_index", 0)
            if player.level_index < required_level:
                continue
            
            available.append(skill_config)
        
        # 按价格排序
        available.sort(key=lambda x: x.get("price", 0))
        
        return available
    
    async def learn_skill(self, player: Player, skill_id: str, cost_gold: bool = True) -> Tuple[bool, str]:
        """学习技能
        
        Args:
            player: 玩家对象
            skill_id: 技能ID
            cost_gold: 是否扣除灵石（从商店购买时为False，因为已经扣过了）
            
        Returns:
            (是否成功, 消息)
        """
        skill_config = self.get_skill_by_id(skill_id)
        if not skill_config:
            return False, f"技能不存在：{skill_id}"
        
        skill_name = skill_config.get("name", "未知技能")
        
        # 检查是否已学会
        learned_skills = player.get_learned_skills()
        if skill_id in learned_skills:
            return False, f"你已经学会了【{skill_name}】"
        
        # 检查境界要求
        required_level = skill_config.get("required_level_index", 0)
        if player.level_index < required_level:
            return False, f"境界不足，学习【{skill_name}】需要达到更高境界"
        
        # 检查并扣除灵石
        if cost_gold:
            price = skill_config.get("price", 0)
            if player.gold < price:
                return False, f"灵石不足，学习【{skill_name}】需要 {price} 灵石"
            player.gold -= price
        
        # 添加到已学技能
        learned_skills.append(skill_id)
        player.set_learned_skills(learned_skills)
        
        await self.db.update_player(player)
        
        logger.info(f"玩家 {player.user_id} 学习了技能：{skill_name}")
        
        return True, f"成功学习技能【{skill_name}】"
    
    async def equip_skill(self, player: Player, skill_id: str) -> Tuple[bool, str]:
        """装备技能到槽位
        
        Args:
            player: 玩家对象
            skill_id: 技能ID
            
        Returns:
            (是否成功, 消息)
        """
        skill_config = self.get_skill_by_id(skill_id)
        if not skill_config:
            return False, f"技能不存在：{skill_id}"
        
        skill_name = skill_config.get("name", "未知技能")
        
        # 检查是否已学会
        learned_skills = player.get_learned_skills()
        if skill_id not in learned_skills:
            return False, f"你还没有学会【{skill_name}】"
        
        # 检查是否已装备
        equipped_skills = player.get_equipped_skills()
        if skill_id in equipped_skills:
            return False, f"【{skill_name}】已经装备了"
        
        # 检查槽位是否已满
        if len(equipped_skills) >= self.MAX_EQUIPPED_SKILLS:
            return False, f"技能槽已满（最多装备{self.MAX_EQUIPPED_SKILLS}个技能），请先卸下其他技能"
        
        # 装备技能
        equipped_skills.append(skill_id)
        player.set_equipped_skills(equipped_skills)
        
        await self.db.update_player(player)
        
        logger.info(f"玩家 {player.user_id} 装备了技能：{skill_name}")
        
        return True, f"成功装备技能【{skill_name}】"
    
    async def unequip_skill(self, player: Player, skill_id: str) -> Tuple[bool, str]:
        """卸下技能
        
        Args:
            player: 玩家对象
            skill_id: 技能ID
            
        Returns:
            (是否成功, 消息)
        """
        skill_config = self.get_skill_by_id(skill_id)
        if not skill_config:
            return False, f"技能不存在：{skill_id}"
        
        skill_name = skill_config.get("name", "未知技能")
        
        # 检查是否已装备
        equipped_skills = player.get_equipped_skills()
        if skill_id not in equipped_skills:
            return False, f"【{skill_name}】没有装备"
        
        # 卸下技能
        equipped_skills.remove(skill_id)
        player.set_equipped_skills(equipped_skills)
        
        await self.db.update_player(player)
        
        logger.info(f"玩家 {player.user_id} 卸下了技能：{skill_name}")
        
        return True, f"成功卸下技能【{skill_name}】"
    
    async def equip_skill_by_name(self, player: Player, skill_name: str) -> Tuple[bool, str]:
        """根据技能名称装备技能
        
        Args:
            player: 玩家对象
            skill_name: 技能名称
            
        Returns:
            (是否成功, 消息)
        """
        skill_config = self.get_skill_by_name(skill_name)
        if not skill_config:
            return False, f"未找到技能【{skill_name}】"
        
        skill_id = skill_config.get("id", "")
        return await self.equip_skill(player, skill_id)
    
    async def unequip_skill_by_name(self, player: Player, skill_name: str) -> Tuple[bool, str]:
        """根据技能名称卸下技能
        
        Args:
            player: 玩家对象
            skill_name: 技能名称
            
        Returns:
            (是否成功, 消息)
        """
        skill_config = self.get_skill_by_name(skill_name)
        if not skill_config:
            return False, f"未找到技能【{skill_name}】"
        
        skill_id = skill_config.get("id", "")
        return await self.unequip_skill(player, skill_id)
    
    def get_learned_skill_configs(self, player: Player) -> List[dict]:
        """获取玩家已学会技能的完整配置列表
        
        Args:
            player: 玩家对象
            
        Returns:
            技能配置列表
        """
        learned_skills = player.get_learned_skills()
        configs = []
        
        for skill_id in learned_skills:
            skill_config = self.get_skill_by_id(skill_id)
            if skill_config:
                configs.append(skill_config)
        
        return configs
    
    def get_equipped_skill_configs(self, player: Player) -> List[dict]:
        """获取玩家已装备技能的完整配置列表
        
        Args:
            player: 玩家对象
            
        Returns:
            技能配置列表
        """
        equipped_skills = player.get_equipped_skills()
        configs = []
        
        for skill_id in equipped_skills:
            skill_config = self.get_skill_by_id(skill_id)
            if skill_config:
                configs.append(skill_config)
        
        return configs
    
    def get_skill_display(self, skill_config: dict) -> str:
        """生成技能信息显示文本
        
        Args:
            skill_config: 技能配置
            
        Returns:
            格式化的技能信息文本
        """
        name = skill_config.get("name", "未知")
        skill_type = skill_config.get("type", "active")
        damage_type = skill_config.get("damage_type", "physical")
        description = skill_config.get("description", "无描述")
        mp_cost = skill_config.get("mp_cost", 0)
        cooldown = skill_config.get("cooldown", 0)
        
        damage_config = skill_config.get("damage", {})
        base_damage = damage_config.get("base", 0)
        attack_ratio = damage_config.get("attack_ratio", 1.0)
        
        type_text = "主动" if skill_type == "active" else "被动"
        damage_type_text = "物理" if damage_type == "physical" else "法术"
        
        lines = [
            f"【{name}】",
            f"类型：{type_text} | {damage_type_text}",
            f"描述：{description}",
            f"消耗：{mp_cost} MP",
        ]
        
        if cooldown > 0:
            lines.append(f"冷却：{cooldown}回合")
        
        lines.append(f"伤害：{base_damage} + {attack_ratio:.1f}x攻击力")
        
        effects = skill_config.get("effects", [])
        if effects:
            effect_strs = []
            for eff in effects:
                eff_type = eff.get("type", "")
                eff_value = eff.get("value", 0)
                eff_duration = eff.get("duration", 1)
                eff_chance = eff.get("chance", 1.0)
                
                if eff_chance < 1.0:
                    effect_strs.append(f"{eff_type}({eff_value}, {eff_duration}回合, {eff_chance:.0%})")
                else:
                    effect_strs.append(f"{eff_type}({eff_value}, {eff_duration}回合)")
            
            lines.append(f"效果：{', '.join(effect_strs)}")
        
        lifesteal = skill_config.get("lifesteal", 0)
        if lifesteal > 0:
            lines.append(f"生命偷取：{lifesteal:.0%}")
        
        return "\n".join(lines)
    
    def get_player_skills_summary(self, player: Player) -> dict:
        """获取玩家技能概览
        
        Args:
            player: 玩家对象
            
        Returns:
            技能概览字典
        """
        learned_skills = player.get_learned_skills()
        equipped_skills = player.get_equipped_skills()
        
        learned_configs = self.get_learned_skill_configs(player)
        equipped_configs = self.get_equipped_skill_configs(player)
        
        return {
            "learned_count": len(learned_skills),
            "equipped_count": len(equipped_skills),
            "max_equipped": self.MAX_EQUIPPED_SKILLS,
            "learned_skills": learned_configs,
            "equipped_skills": equipped_configs,
        }
    
    def can_use_skill(self, player: Player, skill_id: str) -> Tuple[bool, str]:
        """检查玩家是否可以使用技能
        
        Args:
            player: 玩家对象
            skill_id: 技能ID
            
        Returns:
            (是否可用, 原因)
        """
        skill_config = self.get_skill_by_id(skill_id)
        if not skill_config:
            return False, "技能不存在"
        
        skill_name = skill_config.get("name", "未知技能")
        
        # 检查是否已装备
        equipped_skills = player.get_equipped_skills()
        if skill_id not in equipped_skills:
            return False, f"【{skill_name}】未装备"
        
        # 检查MP是否足够
        mp_cost = skill_config.get("mp_cost", 0)
        if player.mp < mp_cost:
            return False, f"MP不足，需要 {mp_cost} MP"
        
        return True, "可以使用"
    
    def calculate_skill_damage(self, skill_config: dict, attacker_atk: int, 
                               is_critical: bool = False, 
                               critical_damage_multiplier: float = 1.5) -> int:
        """计算技能伤害
        
        Args:
            skill_config: 技能配置
            attacker_atk: 攻击者攻击力（物攻或法攻）
            is_critical: 是否暴击
            critical_damage_multiplier: 暴击伤害倍率
            
        Returns:
            计算后的伤害值
        """
        damage_config = skill_config.get("damage", {})
        base_damage = damage_config.get("base", 0)
        attack_ratio = damage_config.get("attack_ratio", 1.0)
        
        # 基础伤害计算
        damage = base_damage + int(attacker_atk * attack_ratio)
        
        # 暴击加成
        if is_critical:
            damage = int(damage * critical_damage_multiplier)
        
        return max(1, damage)
