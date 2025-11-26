from pathlib import Path
from astrbot.api import logger, AstrBotConfig
from astrbot.api.star import Context, Star, register
from astrbot.api.event import AstrMessageEvent, filter
from .data import DataBase, MigrationManager
from .config_manager import ConfigManager
from .handlers import MiscHandler, PlayerHandler, EquipmentHandler, BreakthroughHandler, PillHandler, ShopHandler

# 指令定义
CMD_HELP = "修仙帮助"
CMD_START_XIUXIAN = "我要修仙"
CMD_PLAYER_INFO = "我的信息"
CMD_START_CULTIVATION = "闭关"
CMD_END_CULTIVATION = "出关"
CMD_CHECK_IN = "签到"
CMD_SHOW_EQUIPMENT = "我的装备"
CMD_EQUIP_ITEM = "装备"
CMD_UNEQUIP_ITEM = "卸下"
CMD_BREAKTHROUGH = "突破"
CMD_BREAKTHROUGH_INFO = "突破信息"
CMD_USE_PILL = "服用丹药"
CMD_SHOW_PILLS = "丹药背包"
CMD_PILL_INFO = "丹药信息"
CMD_SHOP = "商店"
CMD_BUY = "购买"
CMD_REFRESH_SHOP = "刷新商店"

@register(
    "astrbot_plugin_xiuxian_lite",
    "linjianyan0229",
    "基于astrbot框架的文字修仙游戏",
    "1.0.0dev",
    "https://github.com/linjianyan0229/astrbot_plugin_monixiuxian"
)
class XiuXianPlugin(Star):
    """修仙插件 - 文字修仙游戏"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        _current_dir = Path(__file__).parent
        self.config_manager = ConfigManager(_current_dir)

        files_config = self.config.get("FILES", {})
        db_file = files_config.get("DATABASE_FILE", "xiuxian_data_lite.db")
        self.db = DataBase(db_file)

        self.misc_handler = MiscHandler(self.db)
        self.player_handler = PlayerHandler(self.db, self.config, self.config_manager)
        self.equipment_handler = EquipmentHandler(self.db, self.config_manager)
        self.breakthrough_handler = BreakthroughHandler(self.db, self.config_manager, self.config)
        self.pill_handler = PillHandler(self.db, self.config_manager)
        self.shop_handler = ShopHandler(self.db, self.config, self.config_manager)

        access_control_config = self.config.get("ACCESS_CONTROL", {})
        self.whitelist_groups = [str(g) for g in access_control_config.get("WHITELIST_GROUPS", [])]

        logger.info("【修仙插件】XiuXianPlugin 初始化完成。")

    def _check_access(self, event: AstrMessageEvent) -> bool:
        """检查访问权限，支持群聊白名单控制"""
        # 如果没有配置白名单，允许所有访问
        if not self.whitelist_groups:
            return True

        # 获取群组ID，私聊时为None
        group_id = event.get_group_id()

        # 如果是私聊，允许访问
        if not group_id:
            return True

        # 检查群组是否在白名单中
        if str(group_id) in self.whitelist_groups:
            return True

        return False

    async def _send_access_denied_message(self, event: AstrMessageEvent):
        """发送访问被拒绝的提示消息"""
        try:
            await event.send("抱歉，此群聊未在修仙插件的白名单中，无法使用相关功能。")
        except:
            # 如果发送失败，静默处理
            pass

    async def initialize(self):
        await self.db.connect()
        migration_manager = MigrationManager(self.db.conn, self.config_manager)
        await migration_manager.migrate()
        logger.info("【修仙插件】已加载。")

    async def terminate(self):
        await self.db.close()
        logger.info("【修仙插件】已卸载。")

    @filter.command(CMD_HELP, "显示帮助信息")
    async def handle_help(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.misc_handler.handle_help(event):
            yield r

    @filter.command(CMD_START_XIUXIAN, "开始你的修仙之路")
    async def handle_start_xiuxian(self, event: AstrMessageEvent, cultivation_type: str = ""):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.player_handler.handle_start_xiuxian(event, cultivation_type):
            yield r

    @filter.command(CMD_PLAYER_INFO, "查看你的角色信息")
    async def handle_player_info(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.player_handler.handle_player_info(event):
            yield r

    @filter.command(CMD_START_CULTIVATION, "开始闭关修炼")
    async def handle_start_cultivation(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.player_handler.handle_start_cultivation(event):
            yield r

    @filter.command(CMD_END_CULTIVATION, "结束闭关修炼")
    async def handle_end_cultivation(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.player_handler.handle_end_cultivation(event):
            yield r

    @filter.command(CMD_CHECK_IN, "每日签到领取灵石")
    async def handle_check_in(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.player_handler.handle_check_in(event):
            yield r

    @filter.command(CMD_SHOW_EQUIPMENT, "查看已装备的物品")
    async def handle_show_equipment(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.equipment_handler.handle_show_equipment(event):
            yield r

    @filter.command(CMD_EQUIP_ITEM, "装备物品")
    async def handle_equip_item(self, event: AstrMessageEvent, item_name: str = ""):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.equipment_handler.handle_equip_item(event, item_name):
            yield r

    @filter.command(CMD_UNEQUIP_ITEM, "卸下装备")
    async def handle_unequip_item(self, event: AstrMessageEvent, slot_or_name: str = ""):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.equipment_handler.handle_unequip_item(event, slot_or_name):
            yield r

    @filter.command(CMD_BREAKTHROUGH_INFO, "查看突破信息")
    async def handle_breakthrough_info(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.breakthrough_handler.handle_breakthrough_info(event):
            yield r

    @filter.command(CMD_BREAKTHROUGH, "尝试突破境界")
    async def handle_breakthrough(self, event: AstrMessageEvent, pill_name: str = ""):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.breakthrough_handler.handle_breakthrough(event, pill_name):
            yield r

    @filter.command(CMD_USE_PILL, "服用丹药")
    async def handle_use_pill(self, event: AstrMessageEvent, pill_name: str = ""):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.pill_handler.handle_use_pill(event, pill_name):
            yield r

    @filter.command(CMD_SHOW_PILLS, "查看丹药背包")
    async def handle_show_pills(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.pill_handler.handle_show_pills(event):
            yield r

    @filter.command(CMD_PILL_INFO, "查看丹药信息")
    async def handle_pill_info(self, event: AstrMessageEvent, pill_name: str = ""):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.pill_handler.handle_pill_info(event, pill_name):
            yield r

    @filter.command(CMD_SHOP, "查看商店物品")
    async def handle_shop(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.shop_handler.handle_shop(event):
            yield r

    @filter.command(CMD_BUY, "购买商店物品")
    async def handle_buy(self, event: AstrMessageEvent, item_name: str = ""):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.shop_handler.handle_buy(event, item_name):
            yield r

    @filter.command(CMD_REFRESH_SHOP, "手动刷新商店")
    async def handle_refresh_shop(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.shop_handler.handle_refresh_shop(event):
            yield r
