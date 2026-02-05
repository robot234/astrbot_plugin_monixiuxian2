# handlers/equipment_handler.py

from astrbot.api.event import AstrMessageEvent
from ..data import DataBase
from ..core import EquipmentManager, PillManager, StorageRingManager
from ..core.skill_manager import SkillManager
from ..config_manager import ConfigManager
from ..models import Player
from .utils import player_required

CMD_SHOW_EQUIPMENT = "我的装备"
CMD_EQUIP_ITEM = "装备"
CMD_UNEQUIP_ITEM = "卸下"

__all__ = ["EquipmentHandler"]

class EquipmentHandler:
    """装备系统处理器"""

    def __init__(self, db: DataBase, config_manager: ConfigManager):
        self.db = db
        self.config_manager = config_manager
        self.storage_ring_manager = StorageRingManager(db, config_manager)
        self.equipment_manager = EquipmentManager(db, config_manager, self.storage_ring_manager)
        self.pill_manager = PillManager(db, config_manager)
        self.skill_manager = SkillManager(db, config_manager)

    @player_required
    async def handle_show_equipment(self, player: Player, event: AstrMessageEvent):
        """显示玩家当前装备"""
        display_name = event.get_sender_name()

        # 获取所有已装备物品
        equipped_items = self.equipment_manager.get_equipped_items(
            player,
            self.config_manager.items_data,
            self.config_manager.weapons_data
        )

        await self.pill_manager.update_temporary_effects(player)
        pill_multipliers = self.pill_manager.calculate_pill_attribute_effects(player)

        # 构建装备显示
        equipment_lines = [
            f"⚔️ {display_name} 的装备\n",
            f"━━━━━━━━━━━━━━━\n",
            f"\n",
            f"【装备栏】\n",
            f"  🗡️ 武器：{player.weapon if player.weapon else '未装备'}\n",
            f"  🛡️ 防具：{player.armor if player.armor else '未装备'}\n",
            f"\n",
            f"【功法栏】(1/1)\n",
            f"  📜 功法：{player.main_technique if player.main_technique else '未装备'}\n",
        ]

        # 技能槽（最多2个）
        equipped_skills = self.skill_manager.get_equipped_skill_configs(player)
        equipment_lines.append(f"\n")
        equipment_lines.append(f"【技能栏】({len(equipped_skills)}/2)\n")
        
        if equipped_skills:
            for i, skill in enumerate(equipped_skills, 1):
                skill_name = skill.get("name", "未知技能")
                damage_type = "物理" if skill.get("damage_type") == "physical" else "法术"
                mp_cost = skill.get("mp_cost", 0)
                equipment_lines.append(f"  {i}. {skill_name} ({damage_type}) [消耗{mp_cost}MP]\n")
        else:
            equipment_lines.append(f"  (无已装备技能)\n")

        # 总属性加成
        if equipped_items:
            equipment_lines.append(f"\n")
            equipment_lines.append(f"━━━ 装备属性加成 ━━━\n")
            total_attrs = player.get_total_attributes(equipped_items, pill_multipliers)

            # 计算加成值（总属性 - 基础属性）
            magic_damage_bonus = total_attrs["magic_damage"] - player.magic_damage
            physical_damage_bonus = total_attrs["physical_damage"] - player.physical_damage
            magic_defense_bonus = total_attrs["magic_defense"] - player.magic_defense
            physical_defense_bonus = total_attrs["physical_defense"] - player.physical_defense
            mental_power_bonus = total_attrs["mental_power"] - player.mental_power
            max_spiritual_qi_bonus = total_attrs["max_spiritual_qi"] - player.max_spiritual_qi
            exp_multiplier = total_attrs["exp_multiplier"]
            
            # 新增战斗属性加成
            speed_bonus = total_attrs.get("speed", player.speed) - player.speed
            critical_rate_bonus = total_attrs.get("critical_rate", player.critical_rate) - player.critical_rate
            critical_damage_bonus = total_attrs.get("critical_damage", player.critical_damage) - player.critical_damage
            max_hp_bonus = total_attrs.get("max_hp", player.max_hp) - player.max_hp
            max_mp_bonus = total_attrs.get("max_mp", player.max_mp) - player.max_mp

            has_bonus = False
            if magic_damage_bonus > 0:
                equipment_lines.append(f"  ⚔️ 法伤 +{magic_damage_bonus}\n")
                has_bonus = True
            if physical_damage_bonus > 0:
                equipment_lines.append(f"  🗡️ 物伤 +{physical_damage_bonus}\n")
                has_bonus = True
            if magic_defense_bonus > 0:
                equipment_lines.append(f"  🛡️ 法防 +{magic_defense_bonus}\n")
                has_bonus = True
            if physical_defense_bonus > 0:
                equipment_lines.append(f"  🪨 物防 +{physical_defense_bonus}\n")
                has_bonus = True
            if mental_power_bonus > 0:
                equipment_lines.append(f"  🧠 精神力 +{mental_power_bonus}\n")
                has_bonus = True
            if max_spiritual_qi_bonus > 0:
                equipment_lines.append(f"  ✨ 灵气容量 +{max_spiritual_qi_bonus}\n")
                has_bonus = True
            if exp_multiplier > 0:
                equipment_lines.append(f"  📈 修为倍率 +{exp_multiplier:.1%}\n")
                has_bonus = True
            if speed_bonus > 0:
                equipment_lines.append(f"  💨 速度 +{speed_bonus}\n")
                has_bonus = True
            if critical_rate_bonus > 0:
                equipment_lines.append(f"  💥 暴击率 +{critical_rate_bonus:.1%}\n")
                has_bonus = True
            if critical_damage_bonus > 0:
                equipment_lines.append(f"  💢 暴击伤害 +{critical_damage_bonus:.1%}\n")
                has_bonus = True
            if max_hp_bonus > 0:
                equipment_lines.append(f"  ❤️ HP +{max_hp_bonus}\n")
                has_bonus = True
            if max_mp_bonus > 0:
                equipment_lines.append(f"  💙 MP +{max_mp_bonus}\n")
                has_bonus = True
            
            if not has_bonus:
                equipment_lines.append(f"  (无额外加成)\n")

        equipment_lines.append(f"\n")
        equipment_lines.append(f"━━━━━━━━━━━━━━━\n")
        equipment_lines.append(f"💡 装备：装备 <物品名>\n")
        equipment_lines.append(f"💡 卸下：卸下 武器/防具/功法\n")
        equipment_lines.append(f"💡 技能：装备技能/卸下技能 <技能名>")

        yield event.plain_result("".join(equipment_lines))

    @player_required
    async def handle_equip_item(self, player: Player, event: AstrMessageEvent, item_name: str):
        """装备物品"""
        if not item_name or item_name.strip() == "":
            yield event.plain_result(f"请指定要装备的物品名称\n用法：{CMD_EQUIP_ITEM} 物品名称")
            return

        item_name = item_name.strip()

        # 检查物品是否存在于配置中（先查items再查weapons再查techniques）
        item_config = self.config_manager.items_data.get(item_name)
        if not item_config:
            item_config = self.config_manager.weapons_data.get(item_name)
        if not item_config:
            item_config = self.config_manager.techniques_data.get(item_name)
            if not item_config:
                # 尝试通过名称查找功法
                for tech_id, tech_data in self.config_manager.techniques_data.items():
                    if tech_data.get("name") == item_name:
                        item_config = tech_data
                        break

        if not item_config:
            yield event.plain_result(f"未找到物品：{item_name}")
            return

        # 检查物品类型是否可装备
        item_type = item_config.get("type", "")
        equippable_types = ["weapon", "armor", "main_technique", "technique"]
        
        # 兼容旧格式
        if item_type == "法器":
            subtype = item_config.get("subtype", "")
            if subtype == "武器":
                item_type = "weapon"
            elif subtype == "防具":
                item_type = "armor"
        elif item_type == "功法":
            item_type = "technique"
        
        # 将 technique 类型统一处理为 main_technique（因为只有一个功法槽）
        if item_type == "technique":
            item_type = "main_technique"
        
        if item_type not in equippable_types:
            yield event.plain_result(f"【{item_name}】不是可装备的物品类型")
            return

        # 检查储物戒中是否有该物品
        if not self.storage_ring_manager.has_item(player, item_name, 1):
            yield event.plain_result(
                f"❌ 储物戒中没有【{item_name}】\n"
                f"请先通过购买或获得该装备"
            )
            return

        # 从储物戒取出物品
        success, retrieve_msg = await self.storage_ring_manager.retrieve_item(player, item_name, 1)
        if not success:
            yield event.plain_result(f"❌ 无法从储物戒取出装备：{retrieve_msg}")
            return

        # 创建Item对象
        from ..models import Item
        item = Item(
            item_id=item_config.get("id", item_name),
            name=item_name,
            item_type=item_type,
            description=item_config.get("description", ""),
            rank=item_config.get("rank", ""),
            required_level_index=item_config.get("required_level_index", 0),
            weapon_category=item_config.get("weapon_category", ""),
            magic_damage=item_config.get("magic_damage", 0),
            physical_damage=item_config.get("physical_damage", 0),
            magic_defense=item_config.get("magic_defense", 0),
            physical_defense=item_config.get("physical_defense", 0),
            mental_power=item_config.get("mental_power", 0),
            exp_multiplier=item_config.get("exp_multiplier", 0.0),
            spiritual_qi=item_config.get("spiritual_qi", 0),
            speed=item_config.get("speed", 0),
            critical_rate=item_config.get("critical_rate", 0.0),
            critical_damage=item_config.get("critical_damage", 0.0),
            hp_bonus=item_config.get("hp_bonus", 0),
            mp_bonus=item_config.get("mp_bonus", 0)
        )

        # 装备物品
        success, message = await self.equipment_manager.equip_item(player, item)

        if success:
            # 显示属性加成
            attr_display = item.get_attribute_display()
            result_msg = (
                f"✅ {message}\n"
                f"━━━━━━━━━━━━━━━\n"
                f"属性加成：{attr_display}"
            )
            yield event.plain_result(result_msg)
        else:
            # 装备失败，将物品放回储物戒
            await self.storage_ring_manager.store_item(player, item_name, 1, silent=True)
            yield event.plain_result(f"❌ {message}")

    @player_required
    async def handle_unequip_item(self, player: Player, event: AstrMessageEvent, slot_or_name: str):
        """卸下装备"""
        if not slot_or_name or slot_or_name.strip() == "":
            yield event.plain_result(
                f"请指定要卸下的装备\n"
                f"用法：{CMD_UNEQUIP_ITEM} 武器/防具/功法\n"
                f"技能请使用：卸下技能 <技能名>"
            )
            return

        slot_or_name = slot_or_name.strip()

        # 获取卸下前的装备名称，用于存入储物戒
        unequipped_item_name = None
        if slot_or_name in ["武器", "weapon"]:
            unequipped_item_name = player.weapon
        elif slot_or_name in ["防具", "armor"]:
            unequipped_item_name = player.armor
        elif slot_or_name in ["功法", "主修功法", "心法", "主修心法", "main_technique", "technique"]:
            unequipped_item_name = player.main_technique
            slot_or_name = "main_technique"  # 统一为内部标识
        else:
            # 检查是否是具体的装备名称
            if player.weapon == slot_or_name:
                unequipped_item_name = player.weapon
                slot_or_name = "weapon"
            elif player.armor == slot_or_name:
                unequipped_item_name = player.armor
                slot_or_name = "armor"
            elif player.main_technique == slot_or_name:
                unequipped_item_name = player.main_technique
                slot_or_name = "main_technique"

        if not unequipped_item_name:
            yield event.plain_result(
                f"❌ 未找到装备【{slot_or_name}】\n"
                f"可卸下的装备类型：武器、防具、功法\n"
                f"技能请使用：卸下技能 <技能名>"
            )
            return

        # 卸下装备
        success, message = await self.equipment_manager.unequip_item(player, slot_or_name)

        if success:
            # 卸下成功后，将装备存入储物戒
            storage_msg = ""
            if unequipped_item_name:
                store_success, store_msg = await self.storage_ring_manager.store_item(
                    player, unequipped_item_name, 1, silent=True
                )
                if store_success:
                    storage_msg = f"\n已存入储物戒"
                else:
                    storage_msg = f"\n⚠️ 存入储物戒失败：{store_msg}"
            
            yield event.plain_result(f"✅ {message}{storage_msg}")
        else:
            yield event.plain_result(f"❌ {message}")
