# handlers/shop_handler.py

import time
from astrbot.api.event import AstrMessageEvent
from astrbot.api import AstrBotConfig
from ..data import DataBase
from ..core import ShopManager, EquipmentManager, PillManager
from ..models import Player
from ..config_manager import ConfigManager
from .utils import player_required

CMD_SHOP = "商店"
CMD_BUY = "购买"
CMD_REFRESH_SHOP = "刷新商店"

__all__ = ["ShopHandler"]

class ShopHandler:
    """商店处理器"""

    def __init__(self, db: DataBase, config: AstrBotConfig, config_manager: ConfigManager):
        self.db = db
        self.config = config
        self.config_manager = config_manager
        self.shop_manager = ShopManager(config, config_manager)
        self.equipment_manager = EquipmentManager(db)
        self.pill_manager = PillManager(db, config_manager)
        access_control = self.config.get("ACCESS_CONTROL", {})
        self.shop_manager_ids = {
            str(user_id)
            for user_id in access_control.get("SHOP_MANAGERS", [])
        }

    def _is_shop_manager(self, event: AstrMessageEvent) -> bool:
        """检查当前用户是否拥有商店管理权限"""
        if not self.shop_manager_ids:
            return False
        sender_id = str(event.get_sender_id())
        return sender_id in self.shop_manager_ids

    async def _ensure_shop_refreshed(self) -> None:
        """确保商店已刷新"""
        last_refresh_time, current_items = await self.db.get_shop_data("global")

        # 检查是否需要刷新
        if not current_items or self.shop_manager.should_refresh_shop(last_refresh_time):
            # 生成新的商店物品
            item_count = self.config.get("SHOP_ITEM_COUNT", 10)
            new_items = self.shop_manager.generate_shop_items(item_count)

            # 保存到数据库
            current_time = int(time.time())
            await self.db.update_shop_data("global", current_time, new_items)

    async def handle_shop(self, event: AstrMessageEvent):
        """处理查看商店命令"""
        # 确保商店已刷新
        await self._ensure_shop_refreshed()

        # 获取商店数据
        last_refresh_time, current_items = await self.db.get_shop_data("global")

        if not current_items:
            yield event.plain_result("商店暂无物品出售，请稍后再试。")
            return

        # 计算下次刷新时间
        refresh_hours = self.config.get("SHOP_REFRESH_HOURS", 6)
        next_refresh_time = last_refresh_time + (refresh_hours * 3600)
        current_time = int(time.time())
        time_until_refresh = next_refresh_time - current_time

        hours = time_until_refresh // 3600
        minutes = (time_until_refresh % 3600) // 60

        # 格式化商店展示
        shop_display = self.shop_manager.format_shop_display(current_items)

        if refresh_hours > 0:
            shop_display += f"\n下次刷新时间: {hours}小时{minutes}分钟后"

        yield event.plain_result(shop_display)

    @player_required
    async def handle_buy(self, player: Player, event: AstrMessageEvent, item_name: str = ""):
        """处理购买物品命令

        Args:
            player: 玩家对象
            event: 事件对象
            item_name: 物品名称
        """
        if not item_name or item_name.strip() == "":
            yield event.plain_result("请指定要购买的物品名称，例如：购买 青铜剑")
            return

        item_name = item_name.strip()

        # 确保商店已刷新
        await self._ensure_shop_refreshed()

        # 获取商店数据
        last_refresh_time, current_items = await self.db.get_shop_data("global")

        # 查找物品
        target_item = next((item for item in current_items if item['name'] == item_name), None)

        if not target_item:
            yield event.plain_result(f"商店中没有找到【{item_name}】，请检查物品名称。")
            return

        price = target_item['price']

        # 检查灵石是否足够
        if player.gold < price:
            yield event.plain_result(
                f"灵石不足！\n"
                f"【{target_item['name']}】价格: {price} 灵石\n"
                f"你的灵石: {player.gold}"
            )
            return

        # 根据物品类型处理
        item_type = target_item['type']
        result_lines = []

        if item_type in ['weapon', 'armor', 'main_technique', 'technique']:
            item_obj = self.equipment_manager.parse_item_from_name(
                target_item['name'],
                self.config_manager.items_data,
                self.config_manager.weapons_data
            )
            if not item_obj:
                yield event.plain_result("装备信息不存在，无法完成购买。")
                return

            success, message = await self.equipment_manager.equip_item(player, item_obj)
            if not success:
                yield event.plain_result(message)
                return
            result_lines.append(message)

        elif item_type in ['pill', 'exp_pill', 'utility_pill']:
            pill_name = target_item['name']
            await self.pill_manager.add_pill_to_inventory(player, pill_name)
            result_lines.append(f"成功购买【{pill_name}】x1！")
            result_lines.append("丹药已添加到背包。")

        else:
            yield event.plain_result(f"未知的物品类型: {item_type}")
            return

        # 扣除灵石并保存
        player.gold -= price
        await self.db.update_player(player)

        result_lines.append(f"花费灵石: {price}")
        result_lines.append(f"剩余灵石: {player.gold}")
        yield event.plain_result("\n".join(result_lines))

    async def handle_refresh_shop(self, event: AstrMessageEvent):
        """处理手动刷新商店命令（管理员功能）"""
        if not self.shop_manager_ids:
            yield event.plain_result("未配置商店管理员，无法手动刷新商店。")
            return

        if not self._is_shop_manager(event):
            yield event.plain_result("你无权刷新商店。")
            return

        # 生成新的商店物品
        item_count = self.config.get("SHOP_ITEM_COUNT", 10)
        new_items = self.shop_manager.generate_shop_items(item_count)

        # 保存到数据库
        current_time = int(time.time())
        await self.db.update_shop_data("global", current_time, new_items)

        yield event.plain_result("商店已手动刷新！")
