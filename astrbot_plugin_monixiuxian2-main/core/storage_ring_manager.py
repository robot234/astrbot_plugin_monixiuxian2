# core/storage_ring_manager.py

from typing import TYPE_CHECKING, Optional, Tuple, List, Dict
from ..models import Player

if TYPE_CHECKING:
    from ..data import DataBase
    from ..config_manager import ConfigManager


class StorageRingManager:
    """储物戒管理器 - 处理储物戒的存取、升级和容量管理"""

    # 丹药类型列表，这些物品不能存入储物戒
    PILL_TYPES = ["丹药"]

    def __init__(self, db: "DataBase", config_manager: "ConfigManager"):
        self.db = db
        self.config_manager = config_manager

    def get_storage_ring_config(self, ring_name: str) -> Optional[dict]:
        """获取储物戒配置"""
        return self.config_manager.storage_rings_data.get(ring_name)

    def get_ring_capacity(self, ring_name: str) -> int:
        """获取储物戒容量"""
        config = self.get_storage_ring_config(ring_name)
        if config:
            return config.get("capacity", 20)
        return 20

    def get_used_slots(self, player: Player) -> int:
        """获取已使用的格子数（每种物品占1格，不管数量多少）"""
        items = player.get_storage_ring_items()
        return len(items)  # 物品种类数 = 已用格子数

    def get_available_slots(self, player: Player) -> int:
        """获取可用的格子数"""
        capacity = self.get_ring_capacity(player.storage_ring)
        used = self.get_used_slots(player)
        return capacity - used

    def get_space_warning(self, player: Player) -> Optional[str]:
        """获取储物戒空间警告（已满或剩余2格以下）

        Returns:
            警告消息，如果不需要警告则返回None
        """
        available = self.get_available_slots(player)
        capacity = self.get_ring_capacity(player.storage_ring)
        used = self.get_used_slots(player)

        if available == 0:
            return f"⚠️ 储物戒已满！({used}/{capacity}格)"
        elif available <= 2:
            return f"⚠️ 储物戒空间不足！仅剩{available}格({used}/{capacity}格)"
        return None

    def is_pill(self, item_name: str) -> bool:
        """检查物品是否为丹药类型"""
        return self.config_manager.is_pill(item_name)

    def can_store_item(self, item_name: str) -> Tuple[bool, str]:
        """检查物品是否可以存入储物戒"""
        # 丹药不能存入储物戒
        if self.is_pill(item_name):
            return False, f"【{item_name}】是丹药，不能存入储物戒（请使用丹药背包）"

        # 储物戒本身不能存入储物戒
        if item_name in self.config_manager.storage_rings_data:
            return False, f"【{item_name}】是储物戒，不能存入另一个储物戒"

        return True, ""

    async def store_item(self, player: Player, item_name: str, count: int = 1, silent: bool = False, external_transaction: bool = False) -> Tuple[bool, str]:
        """将物品存入储物戒（带事务保护）
        
        Args:
            external_transaction: 如果为True，表示外部已有事务，跳过内部事务管理
        """
        can_store, reason = self.can_store_item(item_name)
        if not can_store:
            return False, reason

        if not external_transaction:
            await self.db.conn.execute("BEGIN IMMEDIATE")
        try:
            # 当外部事务存在时，直接使用传递的player对象，避免多次获取导致的覆盖问题
            if not external_transaction:
                fresh_player = await self.db.get_player_by_id(player.user_id)
                if not fresh_player:
                    if not external_transaction:
                        await self.db.conn.rollback()
                    return False, "玩家不存在或已被删除"
                player = fresh_player
            items = player.get_storage_ring_items()

            if item_name not in items:
                available = self.get_available_slots(player)
                if available <= 0:
                    if not external_transaction:
                        await self.db.conn.rollback()
                    capacity = self.get_ring_capacity(player.storage_ring)
                    return False, f"储物戒已满！({capacity}/{capacity}格)"

            items[item_name] = items.get(item_name, 0) + count
            player.set_storage_ring_items(items)
            # 当外部事务存在时，不直接更新数据库，而是让外部事务统一处理
            if not external_transaction:
                await self.db.update_player(player)
                await self.db.conn.commit()

            capacity = self.get_ring_capacity(player.storage_ring)
            used = self.get_used_slots(player)

            if silent:
                return True, ""

            warning = self.get_space_warning(player)
            msg = f"已将【{item_name}】x{count} 存入储物戒（{used}/{capacity}格）"
            if warning:
                msg += f"\n{warning}"

            return True, msg
        except Exception:
            if not external_transaction:
                await self.db.conn.rollback()
            raise

    async def retrieve_item(self, player: Player, item_name: str, count: int = 1) -> Tuple[bool, str]:
        """从储物戒取出物品（带事务保护）"""
        await self.db.conn.execute("BEGIN IMMEDIATE")
        try:
            player = await self.db.get_player_by_id(player.user_id)
            items = player.get_storage_ring_items()

            if item_name not in items:
                await self.db.conn.rollback()
                return False, f"储物戒中没有【{item_name}】"

            current_count = items[item_name]
            if count > current_count:
                await self.db.conn.rollback()
                return False, f"储物戒中【{item_name}】数量不足（当前：{current_count}个）"

            if count >= current_count:
                del items[item_name]
            else:
                items[item_name] = current_count - count

            player.set_storage_ring_items(items)
            await self.db.update_player(player)
            await self.db.conn.commit()

            capacity = self.get_ring_capacity(player.storage_ring)
            used = self.get_used_slots(player)
            return True, f"已从储物戒取出【{item_name}】x{count}（{used}/{capacity}格）"
        except Exception:
            await self.db.conn.rollback()
            raise

    async def discard_item(self, player: Player, item_name: str, count: int = 1) -> Tuple[bool, str]:
        """丢弃储物戒中的物品（带事务保护）"""
        await self.db.conn.execute("BEGIN IMMEDIATE")
        try:
            player = await self.db.get_player_by_id(player.user_id)
            items = player.get_storage_ring_items()

            if item_name not in items:
                await self.db.conn.rollback()
                return False, f"储物戒中没有【{item_name}】"

            current_count = items[item_name]
            if count > current_count:
                await self.db.conn.rollback()
                return False, f"储物戒中【{item_name}】数量不足（当前：{current_count}个）"

            if count >= current_count:
                del items[item_name]
                discard_count = current_count
            else:
                items[item_name] = current_count - count
                discard_count = count

            player.set_storage_ring_items(items)
            await self.db.update_player(player)
            await self.db.conn.commit()

            capacity = self.get_ring_capacity(player.storage_ring)
            used = self.get_used_slots(player)
            return True, f"已丢弃【{item_name}】x{discard_count}（{used}/{capacity}格）"
        except Exception:
            await self.db.conn.rollback()
            raise

    def check_upgrade_requirement(self, player: Player, new_ring_name: str) -> Tuple[bool, str]:
        """检查玩家是否满足储物戒升级要求"""
        # 检查是否为储物戒类型
        ring_config = self.get_storage_ring_config(new_ring_name)
        if not ring_config:
            return False, f"【{new_ring_name}】不是储物戒类型的物品"

        if ring_config.get("type") != "storage_ring":
            return False, f"【{new_ring_name}】不是储物戒类型的物品"

        # 检查境界要求
        required_level = ring_config.get("required_level_index", 0)
        if player.level_index < required_level:
            level_name = self._format_required_level(required_level)
            return False, f"境界不足！【{new_ring_name}】（{ring_config.get('rank', '')}）需要达到【{level_name}】以上"

        # 检查是否为升级（容量必须更大）
        current_capacity = self.get_ring_capacity(player.storage_ring)
        new_capacity = ring_config.get("capacity", 20)
        if new_capacity <= current_capacity:
            return False, f"【{new_ring_name}】容量（{new_capacity}格）不高于当前储物戒（{current_capacity}格），无法替换"

        return True, ""

    def _format_required_level(self, level_index: int) -> str:
        """格式化需求境界名称（同时显示灵修/体修）"""
        names = []
        if 0 <= level_index < len(self.config_manager.level_data):
            name = self.config_manager.level_data[level_index].get("level_name", "")
            if name:
                names.append(name)
        if 0 <= level_index < len(self.config_manager.body_level_data):
            name = self.config_manager.body_level_data[level_index].get("level_name", "")
            if name and name not in names:
                names.append(name)

        if not names:
            return f"境界{level_index}"
        return " / ".join(names)

    async def upgrade_ring(self, player: Player, new_ring_name: str) -> Tuple[bool, str]:
        """升级/替换储物戒"""
        can_upgrade, error_msg = self.check_upgrade_requirement(player, new_ring_name)
        if not can_upgrade:
            return False, error_msg

        ring_config = self.get_storage_ring_config(new_ring_name)
        old_ring = player.storage_ring
        old_capacity = self.get_ring_capacity(old_ring)
        new_capacity = ring_config.get("capacity", 20)
        
        # 检查价格并扣除灵石
        price = ring_config.get("price", 0)
        if price > 0:
            if player.gold < price:
                return False, (
                    f"❌ 灵石不足！\n"
                    f"【{new_ring_name}】需要 {price:,} 灵石\n"
                    f"你当前拥有：{player.gold:,} 灵石"
                )
            player.gold -= price

        player.storage_ring = new_ring_name
        await self.db.update_player(player)

        cost_msg = f"\n消耗灵石：{price:,}" if price > 0 else ""
        return True, (
            f"储物戒升级成功！\n"
            f"【{old_ring}】({old_capacity}格) → 【{new_ring_name}】({new_capacity}格)\n"
            f"品级：{ring_config.get('rank', '未知')}{cost_msg}"
        )

    def get_storage_ring_info(self, player: Player) -> dict:
        """获取储物戒完整信息"""
        ring_config = self.get_storage_ring_config(player.storage_ring) or {}
        items = player.get_storage_ring_items()
        capacity = self.get_ring_capacity(player.storage_ring)
        used = self.get_used_slots(player)

        return {
            "name": player.storage_ring,
            "rank": ring_config.get("rank", "未知"),
            "description": ring_config.get("description", ""),
            "capacity": capacity,
            "used": used,
            "available": capacity - used,
            "items": items
        }

    def get_all_storage_rings(self) -> List[dict]:
        """获取所有可用的储物戒列表"""
        rings = []
        for name, config in self.config_manager.storage_rings_data.items():
            rings.append({
                "name": name,
                "rank": config.get("rank", ""),
                "capacity": config.get("capacity", 20),
                "required_level_index": config.get("required_level_index", 0),
                "price": config.get("price", 0),
                "description": config.get("description", "")
            })
        rings.sort(key=lambda x: x["capacity"])
        return rings

    def get_item_count(self, player: Player, item_name: str) -> int:
        """获取储物戒中某物品的数量"""
        items = player.get_storage_ring_items()
        return items.get(item_name, 0)

    def has_item(self, player: Player, item_name: str, count: int = 1) -> bool:
        """检查储物戒中是否有足够数量的物品"""
        return self.get_item_count(player, item_name) >= count
