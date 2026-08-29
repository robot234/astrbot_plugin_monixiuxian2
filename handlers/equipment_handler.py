from astrbot.api.event import AstrMessageEvent

from ..config_manager import ConfigManager
from ..core import EquipmentManager, PillManager, StorageRingManager
from ..core.skill_manager import SkillManager
from ..data import DataBase
from ..models import Player
from .utils import player_required

CMD_SHOW_EQUIPMENT = "我的装备"
CMD_EQUIP_ITEM = "装备"
CMD_UNEQUIP_ITEM = "卸下"

__all__ = ["EquipmentHandler"]


class EquipmentHandler:
    """装备系统处理器。"""

    def __init__(self, db: DataBase, config_manager: ConfigManager):
        self.db = db
        self.config_manager = config_manager
        self.storage_ring_manager = StorageRingManager(db, config_manager)
        self.equipment_manager = EquipmentManager(db, config_manager, self.storage_ring_manager)
        self.pill_manager = PillManager(db, config_manager)
        self.skill_manager = SkillManager(db, config_manager)

    def _normalize_spaces(self, value: str) -> str:
        if not value:
            return ""
        return value.replace("\u3000", " ").strip()

    def _normalize_item_name(self, item_name: str) -> str:
        """兼容别名命令与用户输入里的前缀文本。"""
        normalized = self._normalize_spaces(item_name)
        for prefix in ("装备功法", "装备心法", "装备饰品", "装备法宝", "装备"):
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix):].strip()
                break
        return normalized

    def _normalize_unequip_name(self, slot_or_name: str) -> str:
        """兼容别名命令与用户输入里的前缀文本。"""
        normalized = self._normalize_spaces(slot_or_name)
        for prefix in ("卸下功法", "卸下心法", "卸下饰品", "卸下法宝", "卸下"):
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix):].strip()
                break
        return normalized

    @player_required
    async def handle_show_equipment(self, player: Player, event: AstrMessageEvent):
        """显示玩家当前装备。"""
        display_name = event.get_sender_name()
        equipped_items = self.equipment_manager.get_equipped_items(
            player,
            self.config_manager.items_data,
            self.config_manager.weapons_data,
            self.config_manager.techniques_data,
        )

        await self.pill_manager.update_temporary_effects(player)
        pill_multipliers = self.pill_manager.calculate_pill_attribute_effects(player)

        lines = [
            f"⚔️ {display_name} 的装备\n",
            "━━━━━━━━━━━━━━━\n",
            "\n",
            "【装备栏】\n",
            f"  武器：{player.weapon or '未装备'}\n",
            f"  防具：{player.armor or '未装备'}\n",
            f"  饰品：{player.accessory or '未装备'}\n",
            "\n",
            "【功法栏】\n",
            f"  主修功法：{player.main_technique or '未装备'}\n",
        ]

        techniques_list = player.get_techniques_list()
        if techniques_list:
            lines.append(f"  辅修功法（{len(techniques_list)}/3）：\n")
            for index, technique_name in enumerate(techniques_list, 1):
                lines.append(f"    {index}. {technique_name}\n")
        else:
            lines.append("  辅修功法：未装备\n")

        equipped_skills = self.skill_manager.get_equipped_skill_configs(player)
        lines.append("\n")
        lines.append(f"【技能栏】({len(equipped_skills)}/2)\n")
        if equipped_skills:
            for index, skill in enumerate(equipped_skills, 1):
                skill_name = skill.get("name", "未知技能")
                damage_type = "物理" if skill.get("damage_type") == "physical" else "法术"
                mp_cost = skill.get("mp_cost", 0)
                lines.append(f"  {index}. {skill_name}（{damage_type}，消耗 {mp_cost} MP）\n")
        else:
            lines.append("  暂未装备技能\n")

        if equipped_items:
            total_attrs = player.get_total_attributes(equipped_items, pill_multipliers)
            bonuses = [
                ("法伤", total_attrs["magic_damage"] - player.magic_damage),
                ("物伤", total_attrs["physical_damage"] - player.physical_damage),
                ("法防", total_attrs["magic_defense"] - player.magic_defense),
                ("物防", total_attrs["physical_defense"] - player.physical_defense),
                ("精神力", total_attrs["mental_power"] - player.mental_power),
                ("灵气容量", total_attrs["max_spiritual_qi"] - player.max_spiritual_qi),
                ("修为倍率", total_attrs["exp_multiplier"]),
                ("速度", total_attrs.get("speed", player.speed) - player.speed),
                ("暴击率", total_attrs.get("critical_rate", player.critical_rate) - player.critical_rate),
                ("暴击伤害", total_attrs.get("critical_damage", player.critical_damage) - player.critical_damage),
                ("HP", total_attrs.get("max_hp", player.max_hp) - player.max_hp),
                ("MP", total_attrs.get("max_mp", player.max_mp) - player.max_mp),
            ]

            lines.append("\n")
            lines.append("【装备属性加成】\n")
            has_bonus = False
            for label, value in bonuses:
                if value > 0:
                    has_bonus = True
                    if label in {"修为倍率", "暴击率", "暴击伤害"}:
                        lines.append(f"  {label} +{value:.1%}\n")
                    else:
                        lines.append(f"  {label} +{value}\n")
            if not has_bonus:
                lines.append("  当前没有额外属性加成\n")

        lines.extend(
            [
                "\n",
                "━━━━━━━━━━━━━━━\n",
                "📌 装备：装备 <物品名>\n",
                "📌 装备功法：装备功法 <功法名>\n",
                "📌 卸下：卸下 <武器/防具/饰品/功法名>\n",
                "📌 技能：装备技能 <技能名> / 卸下技能 <技能名>\n",
            ]
        )
        yield event.plain_result("".join(lines))

    @player_required
    async def handle_equip_item(self, player: Player, event: AstrMessageEvent, item_name: str):
        """装备物品或功法。"""
        item_name = self._normalize_item_name(item_name)
        if not item_name:
            yield event.plain_result(
                f"请指定要装备的物品名称\n用法：{CMD_EQUIP_ITEM} <物品名>\n"
                "功法也可以使用：装备功法 <功法名>"
            )
            return

        item = self.equipment_manager.parse_item_from_name(
            item_name,
            self.config_manager.items_data,
            self.config_manager.weapons_data,
            self.config_manager.techniques_data,
        )
        if not item:
            yield event.plain_result(f"未找到物品：{item_name}")
            return

        if item.item_type not in {"weapon", "armor", "accessory", "main_technique", "technique"}:
            yield event.plain_result(f"【{item_name}】不是可装备的物品类型")
            return

        if not self.storage_ring_manager.has_item(player, item_name, 1):
            yield event.plain_result(
                f"❌ 储物戒中没有【{item_name}】\n"
                "请先购买、获得或确认名称与储物戒中的显示一致"
            )
            return

        success, retrieve_msg = await self.storage_ring_manager.retrieve_item(player, item_name, 1)
        if not success:
            yield event.plain_result(f"❌ 无法从储物戒取出【{item_name}】：{retrieve_msg}")
            return

        success, message = await self.equipment_manager.equip_item(player, item)
        if success:
            yield event.plain_result(f"✅ {message}\n属性加成：{item.get_attribute_display()}")
            return

        await self.storage_ring_manager.store_item(player, item_name, 1, silent=True)
        yield event.plain_result(f"❌ {message}")

    @player_required
    async def handle_unequip_item(self, player: Player, event: AstrMessageEvent, slot_or_name: str):
        """卸下装备或功法。"""
        slot_or_name = self._normalize_unequip_name(slot_or_name)
        if not slot_or_name:
            yield event.plain_result(
                f"请指定要卸下的装备\n"
                f"用法：{CMD_UNEQUIP_ITEM} <武器/防具/饰品/功法名>\n"
                "也可以使用：卸下功法 <功法名>"
            )
            return

        original_name = slot_or_name
        unequipped_item_name = None

        if slot_or_name in {"武器", "weapon"}:
            unequipped_item_name = player.weapon
            slot_or_name = "weapon"
        elif slot_or_name in {"防具", "armor"}:
            unequipped_item_name = player.armor
            slot_or_name = "armor"
        elif slot_or_name in {"饰品", "配饰", "法宝", "accessory"}:
            unequipped_item_name = player.accessory
            slot_or_name = "accessory"
        elif slot_or_name in {"功法", "主修功法", "心法", "主修心法", "main_technique"}:
            unequipped_item_name = player.main_technique
            slot_or_name = "main_technique"
        else:
            if player.weapon == slot_or_name:
                unequipped_item_name = player.weapon
                slot_or_name = "weapon"
            elif player.armor == slot_or_name:
                unequipped_item_name = player.armor
                slot_or_name = "armor"
            elif player.accessory == slot_or_name:
                unequipped_item_name = player.accessory
                slot_or_name = "accessory"
            elif player.main_technique == slot_or_name:
                unequipped_item_name = player.main_technique
                slot_or_name = "main_technique"
            elif slot_or_name in player.get_techniques_list():
                unequipped_item_name = slot_or_name

        if not unequipped_item_name:
            yield event.plain_result(
                f"❌ 未找到已装备的【{original_name}】\n"
                "可卸下类型：武器、防具、饰品、主修功法、辅修功法"
            )
            return

        success, message = await self.equipment_manager.unequip_item(player, slot_or_name)
        if not success:
            yield event.plain_result(f"❌ {message}")
            return

        store_success, store_msg = await self.storage_ring_manager.store_item(
            player, unequipped_item_name, 1, silent=True
        )
        if store_success:
            yield event.plain_result(f"✅ {message}\n已存入储物戒")
        else:
            yield event.plain_result(f"✅ {message}\n⚠️ 存入储物戒失败：{store_msg}")
