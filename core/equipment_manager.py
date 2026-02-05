# core/equipment_manager.py

from typing import Optional, List, Dict, TYPE_CHECKING
from ..models import Player, Item
from ..data import DataBase

if TYPE_CHECKING:
    from ..config_manager import ConfigManager
    from .storage_ring_manager import StorageRingManager

class EquipmentManager:
    """装备管理器 - 处理装备的穿戴、卸下和属性计算"""

    def __init__(self, db: DataBase, config_manager: "ConfigManager" = None, storage_ring_manager: "StorageRingManager" = None):
        self.db = db
        self.config_manager = config_manager
        self.storage_ring_manager = storage_ring_manager

    def parse_item_from_name(self, item_name: str, items_data: dict, weapons_data: dict = None) -> Optional[Item]:
        """从物品名称解析为Item对象

        Args:
            item_name: 物品名称
            items_data: 物品配置数据字典
            weapons_data: 武器配置数据字典（可选）

        Returns:
            Item对象，如果未找到则返回None
        """
        if not item_name or item_name == "":
            return None

        # 先从物品配置中查找
        item_config = items_data.get(item_name)

        # 如果没找到且提供了武器配置，从武器配置中查找
        if not item_config and weapons_data:
            item_config = weapons_data.get(item_name)

        if not item_config:
            return None

        # 处理新旧格式兼容性
        item_type = item_config.get("type", "")
        physical_damage = item_config.get("physical_damage", 0)
        physical_defense = item_config.get("physical_defense", 0)
        magic_damage = item_config.get("magic_damage", 0)
        magic_defense = item_config.get("magic_defense", 0)
        mental_power = item_config.get("mental_power", 0)

        # 旧格式兼容：处理 items.json 中的法器（equip_effects 格式）
        if "equip_effects" in item_config:
            equip_effects = item_config["equip_effects"]
            # 旧格式 attack -> physical_damage
            if "attack" in equip_effects:
                physical_damage = equip_effects["attack"]
            # 旧格式 defense -> physical_defense
            if "defense" in equip_effects:
                physical_defense = equip_effects["defense"]
            # 旧格式 max_hp 可用于体修的 blood_qi 加成

        # 旧格式兼容：处理类型映射
        # "法器" + subtype="武器" -> "weapon"
        # "法器" + subtype="防具" -> "armor"
        # "法器" + subtype="饰品" -> "accessory" (暂不支持装备)
        if item_type == "法器":
            subtype = item_config.get("subtype", "")
            if subtype == "武器":
                item_type = "weapon"
            elif subtype == "防具":
                item_type = "armor"
            elif subtype == "饰品":
                item_type = "accessory"
        elif item_type == "功法":
            # 旧格式功法 -> technique
            item_type = "technique"

        return Item(
            item_id=item_config.get("id", item_name),
            name=item_name,
            item_type=item_type,
            description=item_config.get("description", ""),
            rank=item_config.get("rank", ""),
            required_level_index=item_config.get("required_level_index", 0),
            weapon_category=item_config.get("weapon_category", ""),
            magic_damage=magic_damage,
            physical_damage=physical_damage,
            magic_defense=magic_defense,
            physical_defense=physical_defense,
            mental_power=mental_power,
            # 新增战斗属性
            speed=item_config.get("speed", 0),
            critical_rate=item_config.get("critical_rate", 0.0),
            critical_damage=item_config.get("critical_damage", 0.0),
            hp_bonus=item_config.get("hp_bonus", 0),
            mp_bonus=item_config.get("mp_bonus", 0),
            # 现有属性继续
            exp_multiplier=item_config.get("exp_multiplier", 0.0),
            spiritual_qi=item_config.get("spiritual_qi", 0),
            blood_qi=item_config.get("blood_qi", 0)
        )

    def get_equipped_items(self, player: Player, items_data: dict, weapons_data: dict = None) -> List[Item]:
        """获取玩家所有已装备的物品

        Args:
            player: 玩家对象
            items_data: 物品配置数据字典
            weapons_data: 武器配置数据字典（可选）

        Returns:
            已装备物品列表
        """
        equipped = []

        # 武器
        if player.weapon:
            item = self.parse_item_from_name(player.weapon, items_data, weapons_data)
            if item:
                equipped.append(item)

        # 防具
        if player.armor:
            item = self.parse_item_from_name(player.armor, items_data, weapons_data)
            if item:
                equipped.append(item)

        # 主修心法
        if player.main_technique:
            item = self.parse_item_from_name(player.main_technique, items_data, weapons_data)
            if item:
                equipped.append(item)

        # 功法列表
        techniques_list = player.get_techniques_list()
        for technique_name in techniques_list:
            item = self.parse_item_from_name(technique_name, items_data, weapons_data)
            if item:
                equipped.append(item)

        return equipped

    def check_equipment_level_requirement(self, player: Player, item: Item) -> tuple[bool, str]:
        """检查玩家是否满足装备的境界要求

        Args:
            player: 玩家对象
            item: 装备物品

        Returns:
            (是否满足, 提示消息)
        """
        if player.level_index < item.required_level_index:
            # 获取需求境界名称
            required_level_name = self._format_required_level(item.required_level_index)
            return False, f"境界不足！装备【{item.name}】（{item.rank}）需要达到【{required_level_name}】以上"
        return True, ""

    def _format_required_level(self, level_index: int) -> str:
        """格式化需求境界名称（同时显示灵修/体修）"""
        if not self.config_manager:
            return f"境界{level_index}"

        names = []
        # 灵修境界名称
        if 0 <= level_index < len(self.config_manager.level_data):
            name = self.config_manager.level_data[level_index].get("level_name", "")
            if name:
                names.append(name)
        # 体修境界名称
        if 0 <= level_index < len(self.config_manager.body_level_data):
            name = self.config_manager.body_level_data[level_index].get("level_name", "")
            if name and name not in names:
                names.append(name)

        if not names:
            return f"境界{level_index}"
        return " / ".join(names)

    async def equip_item(self, player: Player, item: Item) -> tuple[bool, str]:
        """装备物品

        Args:
            player: 玩家对象
            item: 要装备的物品

        Returns:
            (是否成功, 消息)
        """
        # 检查境界要求
        can_equip, error_msg = self.check_equipment_level_requirement(player, item)
        if not can_equip:
            return False, error_msg

        # 根据物品类型装备到相应位置
        if item.item_type == "weapon":
            old_item = player.weapon
            player.weapon = item.name
            await self.db.update_player(player)
            if old_item:
                # 尝试将旧装备存入储物戒
                storage_msg = await self._store_old_equipment(player, old_item)
                return True, f"已将【{old_item}】替换为【{item.name}】（{item.rank}）{storage_msg}"
            else:
                return True, f"已装备武器【{item.name}】（{item.rank}）"

        elif item.item_type == "armor":
            old_item = player.armor
            player.armor = item.name
            await self.db.update_player(player)
            if old_item:
                # 尝试将旧装备存入储物戒
                storage_msg = await self._store_old_equipment(player, old_item)
                return True, f"已将【{old_item}】替换为【{item.name}】（{item.rank}）{storage_msg}"
            else:
                return True, f"已装备防具【{item.name}】（{item.rank}）"

        elif item.item_type == "main_technique":
            old_item = player.main_technique
            player.main_technique = item.name
            await self.db.update_player(player)
            if old_item:
                # 尝试将旧心法存入储物戒
                storage_msg = await self._store_old_equipment(player, old_item)
                return True, f"已将主修心法【{old_item}】替换为【{item.name}】（{item.rank}）{storage_msg}"
            else:
                return True, f"已装备主修心法【{item.name}】（{item.rank}）"

        elif item.item_type == "technique":
            techniques_list = player.get_techniques_list()

            # 检查是否已装备
            if item.name in techniques_list:
                return False, f"功法【{item.name}】已装备"

            # 检查功法栏是否已满（最多3个）
            if len(techniques_list) >= 3:
                return False, f"功法栏已满（最多3个），请先卸下其他功法"

            # 添加功法
            techniques_list.append(item.name)
            player.set_techniques_list(techniques_list)
            await self.db.update_player(player)
            return True, f"已装备功法【{item.name}】（{item.rank}）（{len(techniques_list)}/3）"

        else:
            return False, f"未知的装备类型：{item.item_type}"

    async def unequip_item(self, player: Player, slot_or_name: str) -> tuple[bool, str]:
        """卸下装备

        Args:
            player: 玩家对象
            slot_or_name: 装备槽位名称（武器/防具/主修心法）或功法名称

        Returns:
            (是否成功, 消息)
        """
        # 尝试按槽位卸下
        if slot_or_name in ["武器", "weapon"]:
            if not player.weapon:
                return False, "未装备武器"
            item_name = player.weapon
            player.weapon = ""
            await self.db.update_player(player)
            return True, f"已卸下武器【{item_name}】"

        elif slot_or_name in ["防具", "armor"]:
            if not player.armor:
                return False, "未装备防具"
            item_name = player.armor
            player.armor = ""
            await self.db.update_player(player)
            return True, f"已卸下防具【{item_name}】"

        elif slot_or_name in ["主修心法", "心法", "main_technique"]:
            if not player.main_technique:
                return False, "未装备主修心法"
            item_name = player.main_technique
            player.main_technique = ""
            await self.db.update_player(player)
            return True, f"已卸下主修心法【{item_name}】"

        # 尝试从功法列表中卸下（按名称）
        techniques_list = player.get_techniques_list()
        if slot_or_name in techniques_list:
            techniques_list.remove(slot_or_name)
            player.set_techniques_list(techniques_list)
            await self.db.update_player(player)
            return True, f"已卸下功法【{slot_or_name}】"

        return False, f"未找到装备：{slot_or_name}"

    async def _store_old_equipment(self, player: Player, item_name: str) -> str:
        """尝试将旧装备存入储物戒

        Args:
            player: 玩家对象
            item_name: 物品名称

        Returns:
            存储结果消息
        """
        if not self.storage_ring_manager:
            return ""

        success, msg = await self.storage_ring_manager.store_item(player, item_name, 1, silent=True)
        if success:
            return f"\n旧装备【{item_name}】已存入储物戒"
        else:
            return f"\n⚠️ 旧装备【{item_name}】存入储物戒失败：{msg}"
