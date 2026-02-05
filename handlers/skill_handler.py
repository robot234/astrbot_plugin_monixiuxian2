"""
技能相关命令处理器
"""

from astrbot.api.event import AstrMessageEvent

from ..models import Player
from ..data import DataBase
from ..config_manager import ConfigManager
from ..core.skill_manager import SkillManager
from .utils import player_required


class SkillHandler:
    """技能相关命令处理器"""
    
    def __init__(self, db: DataBase, config_manager: ConfigManager):
        self.db = db
        self.config_manager = config_manager
        self.skill_manager = SkillManager(db, config_manager)
    
    @player_required
    async def handle_skill_list(self, player: Player, event: AstrMessageEvent) -> str:
        """处理 '技能列表' 命令
        
        显示已学技能和已装备技能
        """
        # 获取玩家技能概览
        summary = self.skill_manager.get_player_skills_summary(player)
        
        lines = [
            "📚 【技能列表】",
            "━━━━━━━━━━━━━━━"
        ]
        
        # 已装备技能
        equipped_skills = player.get_equipped_skills()
        equipped_configs = self.skill_manager.get_equipped_skill_configs(player)
        
        lines.append(f"⚔️ 已装备技能 ({len(equipped_skills)}/{SkillManager.MAX_EQUIPPED_SKILLS})：")
        
        if equipped_configs:
            for i, skill in enumerate(equipped_configs, 1):
                skill_name = skill.get("name", "未知")
                skill_type = "物理" if skill.get("damage_type") == "physical" else "法术"
                mp_cost = skill.get("mp_cost", 0)
                lines.append(f"  {i}. 【{skill_name}】[{skill_type}] MP:{mp_cost}")
        else:
            lines.append("  (无)")
        
        lines.append("")
        
        # 已学会技能
        learned_skills = player.get_learned_skills()
        learned_configs = self.skill_manager.get_learned_skill_configs(player)
        
        lines.append(f"📖 已学会技能 ({len(learned_skills)}个)：")
        
        if learned_configs:
            # 按伤害类型分组
            physical_skills = []
            magic_skills = []
            
            for skill in learned_configs:
                if skill.get("damage_type") == "physical":
                    physical_skills.append(skill)
                else:
                    magic_skills.append(skill)
            
            if physical_skills:
                lines.append("  【物理技能】")
                for skill in physical_skills:
                    skill_id = skill.get("id", "")
                    skill_name = skill.get("name", "未知")
                    mp_cost = skill.get("mp_cost", 0)
                    is_equipped = skill_id in equipped_skills
                    equipped_mark = " ✓" if is_equipped else ""
                    lines.append(f"    • {skill_name} (MP:{mp_cost}){equipped_mark}")
            
            if magic_skills:
                lines.append("  【法术技能】")
                for skill in magic_skills:
                    skill_id = skill.get("id", "")
                    skill_name = skill.get("name", "未知")
                    mp_cost = skill.get("mp_cost", 0)
                    is_equipped = skill_id in equipped_skills
                    equipped_mark = " ✓" if is_equipped else ""
                    lines.append(f"    • {skill_name} (MP:{mp_cost}){equipped_mark}")
        else:
            lines.append("  (无)")
        
        lines.append("")
        lines.append("━━━━━━━━━━━━━━━")
        lines.append("💡 提示：")
        lines.append("  装备技能 <名称> - 装备技能")
        lines.append("  卸下技能 <名称> - 卸下技能")
        lines.append("  技能信息 <名称> - 查看详情")
        
        return "\n".join(lines)
    
    @player_required
    async def handle_learn_skill(self, player: Player, event: AstrMessageEvent,
                                  skill_name: str) -> str:
        """处理 '学习技能 <名称>' 命令"""
        if not skill_name:
            return "❌ 请指定要学习的技能名称！\n用法：学习技能 <技能名称>"
        
        # 根据名称查找技能
        skill_config = self.skill_manager.get_skill_by_name(skill_name)
        if not skill_config:
            return f"❌ 未找到名为【{skill_name}】的技能！"
        
        skill_id = skill_config.get("id", "")
        
        # 尝试学习技能
        success, message = await self.skill_manager.learn_skill(player, skill_id)
        
        if success:
            # 获取技能详情
            skill_display = self.skill_manager.get_skill_display(skill_config)
            return (
                f"✨ 学习成功！\n"
                f"━━━━━━━━━━━━━━━\n"
                f"{skill_display}\n"
                f"━━━━━━━━━━━━━━━\n"
                f"💡 使用 '装备技能 {skill_name}' 来装备此技能"
            )
        else:
            return f"❌ {message}"
    
    @player_required
    async def handle_equip_skill(self, player: Player, event: AstrMessageEvent,
                                  skill_name: str) -> str:
        """处理 '装备技能 <名称>' 命令"""
        if not skill_name:
            return "❌ 请指定要装备的技能名称！\n用法：装备技能 <技能名称>"
        
        # 尝试装备技能
        success, message = await self.skill_manager.equip_skill_by_name(player, skill_name)
        
        if success:
            # 获取当前装备的技能
            equipped_configs = self.skill_manager.get_equipped_skill_configs(player)
            equipped_names = [s.get("name", "未知") for s in equipped_configs]
            
            return (
                f"✅ 成功装备技能【{skill_name}】！\n"
                f"━━━━━━━━━━━━━━━\n"
                f"⚔️ 当前装备技能：\n"
                f"  {' | '.join(equipped_names) if equipped_names else '(无)'}\n"
                f"━━━━━━━━━━━━━━━\n"
                f"💡 战斗中将自动使用已装备的技能"
            )
        else:
            return f"❌ {message}"
    
    @player_required
    async def handle_unequip_skill(self, player: Player, event: AstrMessageEvent,
                                    skill_name: str) -> str:
        """处理 '卸下技能 <名称>' 命令"""
        if not skill_name:
            return "❌ 请指定要卸下的技能名称！\n用法：卸下技能 <技能名称>"
        
        # 尝试卸下技能
        success, message = await self.skill_manager.unequip_skill_by_name(player, skill_name)
        
        if success:
            # 获取当前装备的技能
            equipped_configs = self.skill_manager.get_equipped_skill_configs(player)
            equipped_names = [s.get("name", "未知") for s in equipped_configs]
            
            return (
                f"✅ 成功卸下技能【{skill_name}】！\n"
                f"━━━━━━━━━━━━━━━\n"
                f"⚔️ 当前装备技能：\n"
                f"  {' | '.join(equipped_names) if equipped_names else '(无)'}\n"
                f"━━━━━━━━━━━━━━━"
            )
        else:
            return f"❌ {message}"
    
    async def handle_skill_info(self, event: AstrMessageEvent, skill_name: str) -> str:
        """处理 '技能信息 <名称>' 命令
        
        显示技能详细信息（无需登录）
        """
        if not skill_name:
            return "❌ 请指定要查看的技能名称！\n用法：技能信息 <技能名称>"
        
        # 根据名称查找技能
        skill_config = self.skill_manager.get_skill_by_name(skill_name)
        if not skill_config:
            return f"❌ 未找到名为【{skill_name}】的技能！"
        
        # 生成技能详细信息
        lines = [
            "📜 【技能详情】",
            "━━━━━━━━━━━━━━━"
        ]
        
        # 基础信息
        name = skill_config.get("name", "未知")
        skill_type = skill_config.get("type", "active")
        damage_type = skill_config.get("damage_type", "physical")
        description = skill_config.get("description", "无描述")
        
        type_text = "主动" if skill_type == "active" else "被动"
        damage_type_text = "物理" if damage_type == "physical" else "法术"
        
        lines.append(f"📛 名称：{name}")
        lines.append(f"🏷️ 类型：{type_text} | {damage_type_text}")
        lines.append(f"📝 描述：{description}")
        lines.append("")
        
        # 消耗与冷却
        mp_cost = skill_config.get("mp_cost", 0)
        cooldown = skill_config.get("cooldown", 0)
        
        lines.append("⚡ 消耗与冷却：")
        lines.append(f"  MP消耗：{mp_cost}")
        if cooldown > 0:
            lines.append(f"  冷却时间：{cooldown}回合")
        else:
            lines.append("  冷却时间：无")
        lines.append("")
        
        # 伤害信息
        damage_config = skill_config.get("damage", {})
        base_damage = damage_config.get("base", 0)
        attack_ratio = damage_config.get("attack_ratio", 1.0)
        
        lines.append("💥 伤害计算：")
        lines.append(f"  基础伤害：{base_damage}")
        lines.append(f"  攻击倍率：{attack_ratio:.1f}x")
        
        atk_type = "物攻" if damage_type == "physical" else "法攻"
        lines.append(f"  公式：{base_damage} + {atk_type} × {attack_ratio:.1f}")
        lines.append("")
        
        # 技能效果
        effects = skill_config.get("effects", [])
        if effects:
            lines.append("🎯 技能效果：")
            for effect in effects:
                effect_type = effect.get("type", "")
                value = effect.get("value", 0)
                duration = effect.get("duration", 1)
                chance = effect.get("chance", 1.0)
                
                effect_desc = self._get_effect_description(effect_type, value, duration)
                if chance < 1.0:
                    effect_desc += f" ({chance:.0%}概率)"
                
                lines.append(f"  • {effect_desc}")
            lines.append("")
        
        # 生命偷取
        lifesteal = skill_config.get("lifesteal", 0)
        if lifesteal > 0:
            lines.append(f"🩸 生命偷取：{lifesteal:.0%}")
            lines.append("")
        
        # MP耗尽惩罚
        mp_penalty = skill_config.get("mp_exhausted_penalty", 0)
        if mp_penalty > 0:
            lines.append(f"⚠️ MP耗尽惩罚：受到{mp_penalty:.0%}最大HP的反噬伤害")
            lines.append("")
        
        # 学习要求
        required_level = skill_config.get("required_level_index", 0)
        price = skill_config.get("price", 0)
        
        lines.append("📋 学习要求：")
        
        # 获取境界名称
        level_name = f"境界{required_level}"
        if self.config_manager.level_data and required_level < len(self.config_manager.level_data):
            level_name = self.config_manager.level_data[required_level].get("level_name", level_name)
        
        lines.append(f"  境界要求：{level_name}")
        if price > 0:
            lines.append(f"  学习费用：{price:,} 灵石")
        
        lines.append("━━━━━━━━━━━━━━━")
        
        return "\n".join(lines)
    
    @player_required
    async def handle_available_skills(self, player: Player, event: AstrMessageEvent) -> str:
        """处理 '可学技能' 命令
        
        显示玩家当前可以学习的技能列表
        """
        available_skills = self.skill_manager.get_available_skills_for_player(player)
        
        if not available_skills:
            return (
                "📚 【可学技能】\n"
                "━━━━━━━━━━━━━━━\n"
                "当前没有可学习的新技能\n"
                "━━━━━━━━━━━━━━━\n"
                "💡 提升境界可解锁更多技能"
            )
        
        lines = [
            "📚 【可学技能】",
            "━━━━━━━━━━━━━━━"
        ]
        
        # 按伤害类型分组
        physical_skills = []
        magic_skills = []
        
        for skill in available_skills:
            if skill.get("damage_type") == "physical":
                physical_skills.append(skill)
            else:
                magic_skills.append(skill)
        
        if physical_skills:
            lines.append("⚔️ 【物理技能】")
            for skill in physical_skills:
                name = skill.get("name", "未知")
                mp_cost = skill.get("mp_cost", 0)
                price = skill.get("price", 0)
                
                # 获取境界要求
                required_level = skill.get("required_level_index", 0)
                level_name = f"境界{required_level}"
                if self.config_manager.level_data and required_level < len(self.config_manager.level_data):
                    level_name = self.config_manager.level_data[required_level].get("level_name", level_name)
                
                lines.append(f"  • {name}")
                lines.append(f"    MP:{mp_cost} | {level_name} | {price:,}灵石")
            lines.append("")
        
        if magic_skills:
            lines.append("✨ 【法术技能】")
            for skill in magic_skills:
                name = skill.get("name", "未知")
                mp_cost = skill.get("mp_cost", 0)
                price = skill.get("price", 0)
                
                # 获取境界要求
                required_level = skill.get("required_level_index", 0)
                level_name = f"境界{required_level}"
                if self.config_manager.level_data and required_level < len(self.config_manager.level_data):
                    level_name = self.config_manager.level_data[required_level].get("level_name", level_name)
                
                lines.append(f"  • {name}")
                lines.append(f"    MP:{mp_cost} | {level_name} | {price:,}灵石")
            lines.append("")
        
        lines.append("━━━━━━━━━━━━━━━")
        lines.append(f"💰 当前灵石：{player.gold:,}")
        lines.append("💡 使用 '学习技能 <名称>' 来学习")
        
        return "\n".join(lines)
    
    def _get_effect_description(self, effect_type: str, value: float, duration: int) -> str:
        """获取效果描述文本"""
        effect_descriptions = {
            "stun": f"眩晕目标{duration}回合",
            "freeze": f"冰冻目标{duration}回合",
            "paralysis": f"麻痹目标{duration}回合",
            "confusion": f"使目标混乱{duration}回合",
            "bleed": f"使目标流血{duration}回合，每回合损失{value:.0%}最大HP" if value < 1 else f"使目标流血{duration}回合，每回合损失{int(value)}HP",
            "burn": f"灼烧目标{duration}回合，每回合损失{value:.0%}最大HP" if value < 1 else f"灼烧目标{duration}回合，每回合损失{int(value)}HP",
            "poison": f"使目标中毒{duration}回合，每回合损失{value:.0%}最大HP" if value < 1 else f"使目标中毒{duration}回合，每回合损失{int(value)}HP",
            "slow": f"减速目标{duration}回合，速度降低{value:.0%}",
            "armor_break": f"破甲{duration}回合，物防降低{value:.0%}",
            "magic_break": f"破法{duration}回合，法防降低{value:.0%}",
            "defense_boost": f"提升自身防御{duration}回合，防御提升{value:.0%}",
            "attack_boost": f"提升自身攻击{duration}回合，攻击提升{value:.0%}",
            "dodge_boost": f"提升自身闪避{duration}回合，闪避率提升{value:.0%}",
            "critical_boost": f"提升自身暴击{duration}回合，暴击率提升{value:.0%}",
            "speed_boost": f"提升自身速度{duration}回合，速度提升{value:.0%}",
            "shield": f"获得护盾，吸收{value:.0%}最大HP的伤害" if value < 1 else f"获得{int(value)}点护盾",
            "heal": f"恢复{value:.0%}最大HP" if value < 1 else f"恢复{int(value)}HP",
            "self_damage": f"自身受到{value:.0%}最大HP的伤害" if value < 1 else f"自身受到{int(value)}点伤害",
            "mp_burn": f"燃烧目标{value:.0%}最大MP" if value < 1 else f"燃烧目标{int(value)}MP",
            "purify": "净化自身一个负面效果",
        }
        
        return effect_descriptions.get(effect_type, f"未知效果({effect_type})")
