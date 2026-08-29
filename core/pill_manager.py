# core/pill_manager.py

import time
from typing import Dict, List, Optional, Tuple
from astrbot.api import logger

from ..models import Player
from ..data import DataBase
from ..config_manager import ConfigManager


class PillManager:
    """丹药管理器 - 处理丹药效果、属性加成和限制机制"""

    def __init__(self, db: DataBase, config_manager: ConfigManager):
        self.db = db
        self.config_manager = config_manager

    def _ensure_non_negative_attributes(self, player: Player):
        """保证属性不为负，并同步能量上限约束"""
        attrs = [
            "lifespan",
            "experience",
            "physical_damage",
            "magic_damage",
            "physical_defense",
            "magic_defense",
            "mental_power",
            "spiritual_qi",
            "max_spiritual_qi",
            "blood_qi",
            "max_blood_qi",
            "max_hp",
            "max_mp",
            "speed",
        ]
        for attr in attrs:
            value = getattr(player, attr, 0)
            if value < 0:
                setattr(player, attr, 0)

        # 保证当前能量不超过上限
        if player.spiritual_qi > player.max_spiritual_qi:
            player.spiritual_qi = player.max_spiritual_qi
        if player.blood_qi > player.max_blood_qi:
            player.blood_qi = player.max_blood_qi
        if player.hp > player.max_hp:
            player.hp = player.max_hp
        if player.mp > player.max_mp:
            player.mp = player.max_mp

    def get_pill_by_name(self, pill_name: str) -> Optional[dict]:
        """根据名称获取丹药配置

        Args:
            pill_name: 丹药名称

        Returns:
            丹药配置字典，如果找不到返回None
        """
        # 尝试从破境丹中查找
        pill = self.config_manager.pills_data.get(pill_name)
        if pill:
            return pill

        # 尝试从修为丹中查找
        pill = self.config_manager.exp_pills_data.get(pill_name)
        if pill:
            return pill

        # 尝试从功能丹中查找
        pill = self.config_manager.utility_pills_data.get(pill_name)
        if pill:
            return pill

        # 尝试从items.json中查找
        for item in self.config_manager.items_data.values():
            if item.get("name") == pill_name and item.get("type") == "丹药":
                return item

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

    async def update_temporary_effects(self, player: Player):
        """更新临时丹药效果，移除过期效果

        Args:
            player: 玩家对象
        """
        effects = player.get_active_pill_effects()
        current_time = int(time.time())
        updated_effects = []
        has_changes = False

        for effect in effects:
            if self._apply_periodic_effects(player, effect, current_time):
                has_changes = True

            expiry_time = effect.get("expiry_time", 0)
            if expiry_time <= 0 or current_time < expiry_time:
                updated_effects.append(effect)
            else:
                has_changes = True
                logger.info(f"玩家 {player.user_id} 的丹药效果 {effect.get('pill_name')} 已过期")

        if has_changes or len(updated_effects) != len(effects):
            player.set_active_pill_effects(updated_effects)
            await self.db.update_player(player)

    async def use_pill(
        self,
        player: Player,
        pill_name: str
    ) -> Tuple[bool, str]:
        """使用丹药

        Args:
            player: 玩家对象
            pill_name: 丹药名称

        Returns:
            (是否成功, 消息)
        """
        # 检查背包是否有该丹药
        inventory = player.get_pills_inventory()
        if pill_name not in inventory or inventory[pill_name] <= 0:
            return False, f"你的背包中没有【{pill_name}】！"

        # 获取丹药配置
        pill_data = self.get_pill_by_name(pill_name)
        if not pill_data:
            return False, f"丹药【{pill_name}】配置不存在！"

        # 检查境界需求
        required_level = pill_data.get("required_level_index", 0)
        if player.level_index < required_level:
            # 根据玩家修炼类型获取对应境界名称
            level_data = self.config_manager.get_level_data(player.cultivation_type)
            level_name = f"境界{required_level}"
            if 0 <= required_level < len(level_data):
                level_name = level_data[required_level]["level_name"]
            return False, (
                f"境界不足！使用【{pill_name}】需要达到【{level_name}】"
            )

        # 根据丹药类型处理
        effect_type = pill_data.get("effect_type", "instant")
        subtype = pill_data.get("subtype", "")

        # 处理破境丹（支持多种类型标识）
        if self._is_breakthrough_pill(pill_data):
            # 如果是临时效果类型的破境丹，允许服用以获得临时加成
            if effect_type == "temporary":
                return await self._use_temporary_pill(player, pill_name, pill_data)
            else:
                return False, f"【{pill_name}】是破境丹，只能在突破时使用，或先服用获得临时加成！"

        if subtype == "exp":
            # 修为丹
            return await self._use_exp_pill(player, pill_name, pill_data)
        elif subtype == "resurrection":
            # 回生丹
            return await self._use_resurrection_pill(player, pill_name, pill_data)
        elif effect_type == "temporary":
            # 临时效果丹药
            return await self._use_temporary_pill(player, pill_name, pill_data)
        elif effect_type == "permanent":
            # 永久属性丹药
            return await self._use_permanent_pill(player, pill_name, pill_data)
        elif effect_type == "instant":
            # 瞬间效果丹药
            return await self._use_instant_pill(player, pill_name, pill_data)
        else:
            return False, f"未知的丹药类型：{effect_type}"

    async def _use_exp_pill(self, player: Player, pill_name: str, pill_data: dict) -> Tuple[bool, str]:
        """使用修为丹"""
        exp_gain = pill_data.get("exp_gain", 0)
        player.experience += exp_gain

        # 扣除丹药
        inventory = player.get_pills_inventory()
        inventory[pill_name] -= 1
        if inventory[pill_name] <= 0:
            del inventory[pill_name]
        player.set_pills_inventory(inventory)

        await self.db.update_player(player)

        return True, (
            f"✨ 服用【{pill_name}】成功！\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📈 获得修为：{exp_gain}\n"
            f"💫 当前修为：{player.experience}\n"
            f"━━━━━━━━━━━━━━━"
        )

    async def _use_resurrection_pill(self, player: Player, pill_name: str, pill_data: dict) -> Tuple[bool, str]:
        """使用回生丹"""
        if player.has_resurrection_pill:
            return False, "你已经拥有回生丹效果，无需重复使用！"

        player.has_resurrection_pill = True

        # 扣除丹药
        inventory = player.get_pills_inventory()
        inventory[pill_name] -= 1
        if inventory[pill_name] <= 0:
            del inventory[pill_name]
        player.set_pills_inventory(inventory)

        await self.db.update_player(player)

        return True, (
            f"✨ 服用【{pill_name}】成功！\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🛡️ 你获得了起死回生的能力\n"
            f"下次死亡时将自动复活\n"
            f"（复活后所有属性减半）\n"
            f"━━━━━━━━━━━━━━━"
        )

    async def _use_temporary_pill(self, player: Player, pill_name: str, pill_data: dict) -> Tuple[bool, str]:
        """使用临时效果丹药"""
        duration_minutes = pill_data.get("duration_minutes", 60)
        current_time = int(time.time())
        expiry_time = current_time + duration_minutes * 60

        # 创建效果记录
        effect = {
            "pill_name": pill_name,
            "pill_id": pill_data.get("id", ""),
            "subtype": pill_data.get("subtype", ""),
            "start_time": current_time,
            "expiry_time": expiry_time,
            "duration_minutes": duration_minutes,
            "last_tick_time": current_time,
        }

        # 添加具体效果数据
        effect_keys = [
            "cultivation_multiplier", "physical_damage_multiplier", "magic_damage_multiplier",
            "physical_defense_multiplier", "magic_defense_multiplier",
            "hp_multiplier", "mp_multiplier", "speed_multiplier",
            "lifespan_cost_per_minute", "lifespan_regen_per_minute",
            "spiritual_qi_regen_per_minute", "blood_qi_regen_per_minute", "blood_qi_cost_per_minute",
            "breakthrough_bonus"
        ]
        for key in effect_keys:
            if key in pill_data:
                effect[key] = pill_data[key]
        
        # 从 effect 字段中提取 breakthrough_bonus（items.json 格式）
        if "breakthrough_bonus" not in effect or effect.get("breakthrough_bonus", 0) == 0:
            effect_data = pill_data.get("effect", {})
            if isinstance(effect_data, dict) and "add_breakthrough_bonus" in effect_data:
                effect["breakthrough_bonus"] = effect_data["add_breakthrough_bonus"]

        # 添加到活跃效果
        effects = player.get_active_pill_effects()
        effects.append(effect)
        player.set_active_pill_effects(effects)

        # 扣除丹药
        inventory = player.get_pills_inventory()
        inventory[pill_name] -= 1
        if inventory[pill_name] <= 0:
            del inventory[pill_name]
        player.set_pills_inventory(inventory)

        await self.db.update_player(player)

        # 构建效果描述
        effect_desc = []
        if "cultivation_multiplier" in pill_data:
            mult = pill_data["cultivation_multiplier"]
            if mult > 0:
                effect_desc.append(f"修炼速度+{mult:.0%}")
            else:
                effect_desc.append(f"修炼速度{mult:.0%}")

        if "physical_damage_multiplier" in pill_data:
            mult = pill_data["physical_damage_multiplier"]
            if mult > 0:
                effect_desc.append(f"物伤+{mult:.0%}")
            else:
                effect_desc.append(f"物伤{mult:.0%}")

        if "magic_damage_multiplier" in pill_data:
            mult = pill_data["magic_damage_multiplier"]
            if mult > 0:
                effect_desc.append(f"法伤+{mult:.0%}")
            else:
                effect_desc.append(f"法伤{mult:.0%}")

        if "physical_defense_multiplier" in pill_data:
            mult = pill_data["physical_defense_multiplier"]
            if mult > 0:
                effect_desc.append(f"物防+{mult:.0%}")
            else:
                effect_desc.append(f"物防{mult:.0%}")

        if "magic_defense_multiplier" in pill_data:
            mult = pill_data["magic_defense_multiplier"]
            if mult > 0:
                effect_desc.append(f"法防+{mult:.0%}")
            else:
                effect_desc.append(f"法防{mult:.0%}")

        if "hp_multiplier" in pill_data:
            mult = pill_data["hp_multiplier"]
            if mult > 0:
                effect_desc.append(f"最大HP+{mult:.0%}")
            else:
                effect_desc.append(f"最大HP{mult:.0%}")

        if "mp_multiplier" in pill_data:
            mult = pill_data["mp_multiplier"]
            if mult > 0:
                effect_desc.append(f"最大MP+{mult:.0%}")
            else:
                effect_desc.append(f"最大MP{mult:.0%}")

        if "speed_multiplier" in pill_data:
            mult = pill_data["speed_multiplier"]
            if mult > 0:
                effect_desc.append(f"速度+{mult:.0%}")
            else:
                effect_desc.append(f"速度{mult:.0%}")

        if "lifespan_cost_per_minute" in pill_data:
            cost = pill_data["lifespan_cost_per_minute"]
            effect_desc.append(f"每分钟扣除寿命-{cost}")

        if "lifespan_regen_per_minute" in pill_data:
            regen = pill_data["lifespan_regen_per_minute"]
            effect_desc.append(f"每分钟恢复寿命+{regen}")

        if "spiritual_qi_regen_per_minute" in pill_data:
            regen = pill_data["spiritual_qi_regen_per_minute"]
            effect_desc.append(f"每分钟恢复灵气+{regen}")

        if "blood_qi_regen_per_minute" in pill_data:
            regen = pill_data["blood_qi_regen_per_minute"]
            effect_desc.append(f"每分钟恢复气血+{regen}")

        if "blood_qi_cost_per_minute" in pill_data:
            cost = pill_data["blood_qi_cost_per_minute"]
            effect_desc.append(f"每分钟扣除气血-{cost}")

        # 处理突破加成（支持两种格式）
        breakthrough_bonus = self._get_breakthrough_bonus(pill_data)
        if breakthrough_bonus > 0:
            effect_desc.append(f"突破成功率+{breakthrough_bonus:.0%}")
        elif breakthrough_bonus < 0:
            effect_desc.append(f"突破成功率{breakthrough_bonus:.0%}")

        effects_str = "、".join(effect_desc) if effect_desc else "特殊效果"

        return True, (
            f"✨ 服用【{pill_name}】成功！\n"
            f"━━━━━━━━━━━━━━━\n"
            f"⏱️ 持续时间：{duration_minutes}分钟\n"
            f"🎯 效果：{effects_str}\n"
            f"━━━━━━━━━━━━━━━"
        )

    async def _use_permanent_pill(self, player: Player, pill_name: str, pill_data: dict) -> Tuple[bool, str]:
        """使用永久属性丹药
        
        注意：永久丹药只对基础属性生效，不影响装备和功法加成
        每个境界的永久属性丹药增益最多为基础属性的50%
        """
        # 检查境界限制（50%上限）
        permanent_gains = player.get_permanent_pill_gains()
        level_key = f"level_{player.level_index}"

        if level_key not in permanent_gains:
            permanent_gains[level_key] = {
                "physical_damage": 0,
                "magic_damage": 0,
                "physical_defense": 0,
                "magic_defense": 0,
                "mental_power": 0,
                "lifespan": 0,
                "max_spiritual_qi": 0,
                "max_blood_qi": 0,
                "max_hp": 0,
                "max_mp": 0,
                "speed": 0,
            }

        # 计算基础属性（当前境界突破时获得的属性，不包含装备和功法加成）
        base_attrs = self._get_base_attributes_for_level(player, player.level_index)

        # 检查各项属性是否已达上限
        attr_mapping = {
            "physical_damage_gain": ("physical_damage", "物伤"),
            "magic_damage_gain": ("magic_damage", "法伤"),
            "physical_defense_gain": ("physical_defense", "物防"),
            "magic_defense_gain": ("magic_defense", "法防"),
            "mental_power_gain": ("mental_power", "精神力"),
            "lifespan_gain": ("lifespan", "寿命"),
            "max_spiritual_qi_gain": ("max_spiritual_qi", "最大灵气"),
            "max_blood_qi_gain": ("max_blood_qi", "最大气血"),
            "max_hp_gain": ("max_hp", "最大HP"),
            "max_mp_gain": ("max_mp", "最大MP"),
            "speed_gain": ("speed", "速度"),
        }

        gains_applied = {}
        gains_blocked = {}

        for gain_key, (attr_key, attr_name) in attr_mapping.items():
            if gain_key not in pill_data:
                continue

            gain = pill_data[gain_key]
            if gain == 0:
                continue

            # 只有正向增益才受50%限制
            if gain > 0:
                current_gain = permanent_gains[level_key].get(attr_key, 0)
                base_value = base_attrs.get(attr_key, 100)  # 默认基础值100
                limit = base_value * 0.5  # 50%上限

                if current_gain >= limit:
                    gains_blocked[attr_name] = f"已达上限({limit:.0f})"
                    continue

                # 计算实际可以增加的值
                actual_gain = min(gain, limit - current_gain)
                if actual_gain < gain:
                    gains_blocked[attr_name] = f"部分受限(+{actual_gain:.0f}/{gain})"

                # 应用增益
                permanent_gains[level_key][attr_key] += actual_gain
                setattr(player, attr_key, getattr(player, attr_key) + int(actual_gain))
                gains_applied[attr_name] = int(actual_gain)
            else:
                # 负向效果直接应用
                permanent_gains[level_key][attr_key] += gain
                setattr(player, attr_key, getattr(player, attr_key) + int(gain))
                gains_applied[attr_name] = int(gain)

        # 处理修炼倍率（永久）
        if "cultivation_multiplier" in pill_data:
            cult_mult = pill_data["cultivation_multiplier"]
            if "cultivation_multiplier" not in permanent_gains[level_key]:
                permanent_gains[level_key]["cultivation_multiplier"] = 0
            permanent_gains[level_key]["cultivation_multiplier"] += cult_mult
            gains_applied["修炼速度"] = f"{cult_mult:+.0%}"

        # 处理突破死亡概率降低
        if "death_protection_multiplier" in pill_data:
            death_mult = pill_data["death_protection_multiplier"]
            if "death_protection_multiplier" not in permanent_gains[level_key]:
                permanent_gains[level_key]["death_protection_multiplier"] = 1.0
            permanent_gains[level_key]["death_protection_multiplier"] *= death_mult
            gains_applied["突破死亡概率"] = f"降低{(1 - death_mult) * 100:.0f}%"

        if not gains_applied:
            return False, "该丹药的所有属性增益都已达到上限，无法使用！"

        # 修正属性下限与能量上限
        self._ensure_non_negative_attributes(player)

        # 更新玩家数据
        player.set_permanent_pill_gains(permanent_gains)

        # 扣除丹药
        inventory = player.get_pills_inventory()
        inventory[pill_name] -= 1
        if inventory[pill_name] <= 0:
            del inventory[pill_name]
        player.set_pills_inventory(inventory)

        await self.db.update_player(player)

        # 构建消息
        msg_parts = [
            f"✨ 服用【{pill_name}】成功！",
            "━━━━━━━━━━━━━━━",
            "💪 永久增益："
        ]
        for attr_name, value in gains_applied.items():
            if isinstance(value, int):
                msg_parts.append(f"  {attr_name} +{value}")
            else:
                msg_parts.append(f"  {attr_name} {value}")

        if gains_blocked:
            msg_parts.append("\n⚠️ 受限提示：")
            for attr_name, reason in gains_blocked.items():
                msg_parts.append(f"  {attr_name} {reason}")

        msg_parts.append("━━━━━━━━━━━━━━━")
        msg_parts.append("注：每个境界的永久属性丹药\n增益最多为基础属性的50%")

        return True, "\n".join(msg_parts)

    async def _use_instant_pill(self, player: Player, pill_name: str, pill_data: dict) -> Tuple[bool, str]:
        """使用瞬间效果丹药"""
        msg_parts = [
            f"✨ 服用【{pill_name}】成功！",
            "━━━━━━━━━━━━━━━"
        ]

        # 恢复能量（灵气/气血）
        energy_restore = None
        energy_label = "灵气"
        current_energy = player.spiritual_qi
        max_energy = player.max_spiritual_qi

        # 体修优先使用专属气血恢复键；若无则复用灵气恢复作为气血恢复
        if player.cultivation_type == "体修" and "blood_qi_restore" in pill_data:
            energy_restore = pill_data["blood_qi_restore"]
            energy_label = "气血"
            current_energy = player.blood_qi
            max_energy = player.max_blood_qi
        elif "spiritual_qi_restore" in pill_data:
            energy_restore = pill_data["spiritual_qi_restore"]
            if player.cultivation_type == "体修":
                energy_label = "气血"
                current_energy = player.blood_qi
                max_energy = player.max_blood_qi

        if energy_restore is not None:
            if energy_restore == -1:
                # 恢复至满
                actual_restore = max_energy - current_energy
                current_energy = max_energy
            else:
                old_energy = current_energy
                current_energy = min(current_energy + energy_restore, max_energy)
                actual_restore = current_energy - old_energy

            if energy_label == "气血":
                player.blood_qi = current_energy
                msg_parts.append(f"🌟 恢复气血：+{actual_restore}")
                msg_parts.append(f"🩸 当前气血：{player.blood_qi}/{player.max_blood_qi}")
            else:
                player.spiritual_qi = current_energy
                msg_parts.append(f"🌟 恢复灵气：+{actual_restore}")
                msg_parts.append(f"💫 当前灵气：{player.spiritual_qi}/{player.max_spiritual_qi}")

        # HP恢复
        if "hp_restore" in pill_data:
            hp_restore = pill_data["hp_restore"]
            if hp_restore == -1:
                # 恢复至满
                actual_restore = player.max_hp - player.hp
                player.hp = player.max_hp
            elif 0 < hp_restore < 1:
                # 百分比恢复
                restore_amount = int(player.max_hp * hp_restore)
                old_hp = player.hp
                player.hp = min(player.hp + restore_amount, player.max_hp)
                actual_restore = player.hp - old_hp
            else:
                # 固定值恢复
                old_hp = player.hp
                player.hp = min(player.hp + int(hp_restore), player.max_hp)
                actual_restore = player.hp - old_hp
            if actual_restore > 0:
                msg_parts.append(f"❤️ 恢复HP：+{actual_restore}")
                msg_parts.append(f"💖 当前HP：{player.hp}/{player.max_hp}")

        # MP恢复
        if "mp_restore" in pill_data:
            mp_restore = pill_data["mp_restore"]
            if mp_restore == -1:
                # 恢复至满
                actual_restore = player.max_mp - player.mp
                player.mp = player.max_mp
            elif 0 < mp_restore < 1:
                # 百分比恢复
                restore_amount = int(player.max_mp * mp_restore)
                old_mp = player.mp
                player.mp = min(player.mp + restore_amount, player.max_mp)
                actual_restore = player.mp - old_mp
            else:
                # 固定值恢复
                old_mp = player.mp
                player.mp = min(player.mp + int(mp_restore), player.max_mp)
                actual_restore = player.mp - old_mp
            if actual_restore > 0:
                msg_parts.append(f"💙 恢复MP：+{actual_restore}")
                msg_parts.append(f"🔮 当前MP：{player.mp}/{player.max_mp}")

        # 重置永久丹药增益
        if pill_data.get("resets_permanent_pills"):
            reset_applied = self._reset_permanent_pill_effects(player)
            if reset_applied:
                msg_parts.append("🔄 已重置所有永久属性丹药增益")
                refund_ratio = pill_data.get("reset_refund_ratio", 0.5)
                refund = int(pill_data.get("price", 0) * refund_ratio)
                if refund > 0:
                    player.gold += refund
                    msg_parts.append(f"💰 返还灵石：{refund}")
            else:
                msg_parts.append("ℹ️ 当前没有可重置的永久增益")

        # 定魂丹 - 下一次负面效果免疫
        if pill_data.get("blocks_next_debuff"):
            if player.has_debuff_shield:
                msg_parts.append("🛡️ 定魂护盾已存在，无需重复使用")
            else:
                player.has_debuff_shield = True
                msg_parts.append("🛡️ 获得定魂护盾：下一次负面效果将被抵消")

        # 扣除丹药
        inventory = player.get_pills_inventory()
        inventory[pill_name] -= 1
        if inventory[pill_name] <= 0:
            del inventory[pill_name]
        player.set_pills_inventory(inventory)

        await self.db.update_player(player)

        msg_parts.append("━━━━━━━━━━━━━━━")
        return True, "\n".join(msg_parts)

    def _get_base_attributes_for_level(self, player: Player, level_index: int) -> dict:
        """获取当前境界的基础属性（用于计算50%上限）
        
        注意：这里只返回境界本身提供的基础属性，不包含装备和功法加成

        Args:
            player: 玩家对象，用于确定修炼类型
            level_index: 境界索引

        Returns:
            基础属性字典
        """
        level_data = self.config_manager.get_level_data(player.cultivation_type)
        # 兜底：如果数据为空，使用灵修配置避免索引错误
        if not level_data:
            level_data = self.config_manager.level_data

        # 越界保护
        if level_data:
            level_index = min(level_index, len(level_data) - 1)
            level_config = level_data[level_index]
        else:
            level_config = {}

        # 获取境界基础属性
        base_hp = level_config.get("base_hp", 100)
        base_mp = level_config.get("base_mp", 50)
        base_speed = level_config.get("base_speed", 10)

        return {
            "physical_damage": level_config.get("breakthrough_physical_damage_gain", 10),
            "magic_damage": level_config.get("breakthrough_magic_damage_gain", 10),
            "physical_defense": level_config.get("breakthrough_physical_defense_gain", 5),
            "magic_defense": level_config.get("breakthrough_magic_defense_gain", 5),
            "mental_power": level_config.get("breakthrough_mental_power_gain", 100),
            "lifespan": level_config.get("breakthrough_lifespan_gain", 100),
            "max_spiritual_qi": level_config.get("breakthrough_spiritual_qi_gain", 100),
            "max_blood_qi": level_config.get("breakthrough_blood_qi_gain", 100),
            "max_hp": level_config.get("breakthrough_hp_gain", base_hp),
            "max_mp": level_config.get("breakthrough_mp_gain", base_mp),
            "speed": level_config.get("breakthrough_speed_gain", base_speed),
        }

    async def handle_resurrection(self, player: Player) -> bool:
        """处理玩家死亡时的回生丹效果

        Args:
            player: 玩家对象

        Returns:
            是否成功复活
        """
        if not player.has_resurrection_pill:
            return False

        logger.info(f"玩家 {player.user_id} 触发回生丹效果")

        # 消耗回生丹效果
        player.has_resurrection_pill = False

        # 所有属性减半
        player.lifespan = player.lifespan // 2
        player.experience = player.experience // 2
        player.physical_damage = player.physical_damage // 2
        player.magic_damage = player.magic_damage // 2
        player.physical_defense = player.physical_defense // 2
        player.magic_defense = player.magic_defense // 2
        player.mental_power = player.mental_power // 2
        player.max_spiritual_qi = player.max_spiritual_qi // 2
        player.spiritual_qi = player.max_spiritual_qi // 2
        player.max_blood_qi = player.max_blood_qi // 2
        player.blood_qi = player.max_blood_qi // 2
        player.max_hp = player.max_hp // 2
        player.hp = player.max_hp // 2
        player.max_mp = player.max_mp // 2
        player.mp = player.max_mp // 2
        player.speed = max(1, player.speed // 2)

        self._ensure_non_negative_attributes(player)

        await self.db.update_player(player)
        return True

    def calculate_pill_attribute_effects(self, player: Player) -> dict:
        """计算丹药对属性的影响（乘法加成）

        Args:
            player: 玩家对象

        Returns:
            属性乘法倍率字典
        """
        effects = player.get_active_pill_effects()
        current_time = int(time.time())
        multipliers = {
            "physical_damage": 1.0,
            "magic_damage": 1.0,
            "physical_defense": 1.0,
            "magic_defense": 1.0,
            "cultivation_speed": 1.0,
            "max_hp": 1.0,
            "max_mp": 1.0,
            "speed": 1.0,
        }

        # 累加临时效果
        for effect in effects:
            expiry_time = effect.get("expiry_time", 0)
            if expiry_time > 0 and current_time >= expiry_time:
                continue
            if "physical_damage_multiplier" in effect:
                multipliers["physical_damage"] += effect["physical_damage_multiplier"]
            if "magic_damage_multiplier" in effect:
                multipliers["magic_damage"] += effect["magic_damage_multiplier"]
            if "physical_defense_multiplier" in effect:
                multipliers["physical_defense"] += effect["physical_defense_multiplier"]
            if "magic_defense_multiplier" in effect:
                multipliers["magic_defense"] += effect["magic_defense_multiplier"]
            if "cultivation_multiplier" in effect:
                multipliers["cultivation_speed"] += effect["cultivation_multiplier"]
            if "hp_multiplier" in effect:
                multipliers["max_hp"] += effect["hp_multiplier"]
            if "mp_multiplier" in effect:
                multipliers["max_mp"] += effect["mp_multiplier"]
            if "speed_multiplier" in effect:
                multipliers["speed"] += effect["speed_multiplier"]

        # 累加永久效果
        permanent_gains = player.get_permanent_pill_gains()
        level_key = f"level_{player.level_index}"
        if level_key in permanent_gains:
            level_gains = permanent_gains[level_key]
            if "cultivation_multiplier" in level_gains:
                multipliers["cultivation_speed"] += level_gains["cultivation_multiplier"]

        # 确保倍率不为负
        for key in multipliers:
            multipliers[key] = max(0.0, multipliers[key])

        return multipliers

    def get_breakthrough_modifiers(self, player: Player) -> dict:
        """获取突破时的临时与永久加成信息"""
        effects = player.get_active_pill_effects()
        current_time = int(time.time())
        temp_bonus = 0.0
        has_temp_effects = False

        # 按丹药类型分组计算加成，同类型只取最高值
        bonus_groups = {}
        for effect in effects:
            expiry_time = effect.get("expiry_time", 0)
            if expiry_time > 0 and current_time >= expiry_time:
                continue

            subtype = effect.get("subtype", "")
            # 支持多种破境丹类型标识
            if subtype in {"breakthrough_boost", "breakthrough_debuff", "breakthrough"}:
                pill_name = effect.get("pill_name", "")
                # 根据丹药名称判断类型
                if "凝神增益丹" in pill_name:
                    group = "zengyi"
                elif "破境增益丹" in pill_name:
                    group = "zengyi"
                elif "渡劫增益丹" in pill_name:
                    group = "zengyi"
                elif "化神增益丹" in pill_name:
                    group = "zengyi"
                elif "破虚增益丹" in pill_name:
                    group = "zengyi"
                elif "破劫增益丹" in pill_name:
                    group = "zengyi"
                elif "焚天逆命" in pill_name:
                    group = "special"
                else:
                    group = "other"
                
                # 同类型只保留最高加成
                current_bonus = effect.get("breakthrough_bonus", 0)
                if group not in bonus_groups or current_bonus > bonus_groups[group]:
                    bonus_groups[group] = current_bonus

        # 累加不同类型的加成
        temp_bonus = sum(bonus_groups.values())
        has_temp_effects = len(bonus_groups) > 0
        # 限制总加成不超过50%
        temp_bonus = min(temp_bonus, 0.5)

        permanent_multiplier = 1.0
        permanent_gains = player.get_permanent_pill_gains()
        for level_gain in permanent_gains.values():
            permanent_multiplier *= level_gain.get("death_protection_multiplier", 1.0)

        return {
            "temp_bonus": temp_bonus,
            "has_temp_effects": has_temp_effects,
            "permanent_death_multiplier": max(0.0, min(1.0, permanent_multiplier)),
        }

    async def consume_breakthrough_effects(self, player: Player):
        """突破完成后移除相关临时丹药效果"""
        effects = player.get_active_pill_effects()
        remaining_effects = [
            effect for effect in effects
            if effect.get("subtype", "") not in {"breakthrough_boost", "breakthrough_debuff", "breakthrough"}
        ]

        if len(remaining_effects) != len(effects):
            player.set_active_pill_effects(remaining_effects)
            await self.db.update_player(player)

    async def add_pill_to_inventory(self, player: Player, pill_name: str, count: int = 1):
        """添加丹药到背包

        Args:
            player: 玩家对象
            pill_name: 丹药名称
            count: 数量
        """
        inventory = player.get_pills_inventory()
        if pill_name in inventory:
            inventory[pill_name] += count
        else:
            inventory[pill_name] = count
        player.set_pills_inventory(inventory)
        await self.db.update_player(player)

    def get_pill_inventory_display(self, player: Player) -> str:
        """获取丹药背包显示文本

        Args:
            player: 玩家对象

        Returns:
            丹药背包的格式化文本
        """
        inventory = player.get_pills_inventory()
        if not inventory:
            return "你的丹药背包是空的！"

        lines = ["--- 丹药背包 ---"]
        for pill_name, count in inventory.items():
            pill_data = self.get_pill_by_name(pill_name)
            if pill_data:
                rank = pill_data.get("rank", "未知")
                lines.append(f"[{rank}] {pill_name} × {count}")
            else:
                lines.append(f"{pill_name} × {count}")

        lines.append("-" * 20)
        return "\n".join(lines)

    def _apply_periodic_effects(self, player: Player, effect: dict, current_time: int) -> bool:
        """根据时间自动结算持续恢复/扣减"""
        expiry_time = effect.get("expiry_time", 0)
        tick_limit = min(current_time, expiry_time) if expiry_time > 0 else current_time
        last_tick = effect.get("last_tick_time", effect.get("start_time", current_time))

        if tick_limit <= last_tick:
            return False

        elapsed_seconds = tick_limit - last_tick
        minutes = elapsed_seconds // 60
        if minutes <= 0:
            return False

        effect["last_tick_time"] = last_tick + minutes * 60
        changed = False

        if "lifespan_cost_per_minute" in effect:
            total_cost = effect["lifespan_cost_per_minute"] * minutes
            player.lifespan = max(0, player.lifespan - total_cost)
            changed = True

        if "lifespan_regen_per_minute" in effect:
            total_regen = effect["lifespan_regen_per_minute"] * minutes
            player.lifespan += total_regen
            changed = True

        if "spiritual_qi_regen_per_minute" in effect:
            total_qi = effect["spiritual_qi_regen_per_minute"] * minutes
            player.spiritual_qi = min(player.max_spiritual_qi, player.spiritual_qi + total_qi)
            changed = True

        if "blood_qi_regen_per_minute" in effect:
            total_blood = effect["blood_qi_regen_per_minute"] * minutes
            player.blood_qi = min(player.max_blood_qi, player.blood_qi + total_blood)
            changed = True

        if "blood_qi_cost_per_minute" in effect:
            total_cost = effect["blood_qi_cost_per_minute"] * minutes
            player.blood_qi = max(0, player.blood_qi - total_cost)
            changed = True

        if changed:
            self._ensure_non_negative_attributes(player)

        return changed

    def _reset_permanent_pill_effects(self, player: Player) -> bool:
        """清空永久丹药增益并回退属性"""
        permanent_gains = player.get_permanent_pill_gains()
        if not permanent_gains:
            return False

        attr_keys = [
            "physical_damage",
            "magic_damage",
            "physical_defense",
            "magic_defense",
            "mental_power",
            "lifespan",
            "max_spiritual_qi",
            "max_blood_qi",
            "max_hp",
            "max_mp",
            "speed",
        ]

        changed = False
        for gain in permanent_gains.values():
            for attr_key in attr_keys:
                value = gain.get(attr_key, 0)
                if value:
                    delta = int(value)
                    setattr(player, attr_key, getattr(player, attr_key) - delta)
                    changed = True

            if "cultivation_multiplier" in gain:
                gain["cultivation_multiplier"] = 0
            if "death_protection_multiplier" in gain:
                gain["death_protection_multiplier"] = 1.0

        player.set_permanent_pill_gains({})
        return changed
