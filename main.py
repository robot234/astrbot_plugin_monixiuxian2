import asyncio
from pathlib import Path
from astrbot.api import logger, AstrBotConfig
from astrbot.api.star import Context, Star, register
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.core.utils.astrbot_path import get_astrbot_data_path
from .data import DataBase, MigrationManager
from .config_manager import ConfigManager
from .handlers import (
    MiscHandler, PlayerHandler, EquipmentHandler, BreakthroughHandler, 
    PillHandler, ShopHandler, StorageRingHandler,
    SectHandlers, BossHandlers, CombatHandlers, RankingHandlers,
    RiftHandlers, AdventureHandlers, AlchemyHandlers, ImpartHandlers,
    NicknameHandler, BankHandlers, BountyHandlers, ImpartPkHandlers,
    BlessedLandHandlers, SpiritFarmHandlers, DualCultivationHandlers, SpiritEyeHandlers
)
from .managers import (
    CombatManager, SectManager, BossManager, RiftManager, 
    RankingManager, AdventureManager, AlchemyManager, ImpartManager,
    BankManager, BountyManager, ImpartPkManager,
    BlessedLandManager, SpiritFarmManager, DualCultivationManager, SpiritEyeManager
)

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
CMD_PILL_PAVILION = "丹阁"
CMD_WEAPON_PAVILION = "器阁"
CMD_TREASURE_PAVILION = "百宝阁"
CMD_BUY = "购买"
CMD_STORAGE_RING = "储物戒"
CMD_STORE_ITEM = "存入"
CMD_RETRIEVE_ITEM = "取出"
CMD_UPGRADE_RING = "更换储物戒"
CMD_DISCARD_ITEM = "丢弃"
CMD_GIFT_ITEM = "赠予"
CMD_ACCEPT_GIFT = "接收"
CMD_REJECT_GIFT = "拒绝"

# 宗门系统指令
CMD_CREATE_SECT = "创建宗门"
CMD_JOIN_SECT = "加入宗门"
CMD_LEAVE_SECT = "退出宗门"
CMD_MY_SECT = "我的宗门"
CMD_SECT_LIST = "宗门列表"
CMD_SECT_DONATE = "宗门捐献"
CMD_SECT_KICK = "踢出成员"
CMD_SECT_TRANSFER = "宗主传位"
CMD_SECT_TASK = "宗门任务"
CMD_SECT_POSITION = "职位变更"

# Boss系统指令
CMD_BOSS_INFO = "世界Boss"
CMD_BOSS_FIGHT = "挑战Boss"
CMD_SPAWN_BOSS = "生成Boss"

# 排行榜指令
CMD_RANK_LEVEL = "境界排行"
CMD_RANK_POWER = "战力排行"
CMD_RANK_WEALTH = "灵石排行"
CMD_RANK_SECT = "宗门排行"

# 战斗指令
CMD_DUEL = "决斗"
CMD_SPAR = "切磋"

# 秘境系统指令
CMD_RIFT_LIST = "秘境列表"
CMD_RIFT_EXPLORE = "探索秘境"
CMD_RIFT_COMPLETE = "完成探索"

# 历练系统指令
CMD_ADVENTURE_START = "开始历练"
CMD_ADVENTURE_COMPLETE = "完成历练"
CMD_ADVENTURE_STATUS = "历练状态"
CMD_ADVENTURE_INFO = "历练信息"

# 炼丹系统指令
CMD_ALCHEMY_RECIPES = "丹药配方"
CMD_ALCHEMY_CRAFT = "炼丹"

# 传承系统指令
CMD_IMPART_INFO = "传承信息"

# Phase 1: 道号系统
CMD_CHANGE_NICKNAME = "改道号"

# Phase 2: 灵石银行
CMD_BANK_INFO = "银行"
CMD_BANK_DEPOSIT = "存灵石"
CMD_BANK_WITHDRAW = "取灵石"
CMD_BANK_INTEREST = "领取利息"

# Phase 2: 悬赏令
CMD_BOUNTY_LIST = "悬赏令"
CMD_BOUNTY_ACCEPT = "接取悬赏"
CMD_BOUNTY_STATUS = "悬赏状态"
CMD_BOUNTY_COMPLETE = "完成悬赏"
CMD_BOUNTY_ABANDON = "放弃悬赏"

# Phase 3: 传承PK
CMD_IMPART_CHALLENGE = "传承挑战"
CMD_IMPART_RANKING = "传承排行"

# Phase 4: 洞天福地
CMD_BLESSED_LAND_INFO = "我的洞天"
CMD_BLESSED_LAND_BUY = "购买洞天"
CMD_BLESSED_LAND_UPGRADE = "升级洞天"
CMD_BLESSED_LAND_COLLECT = "洞天收取"

# Phase 4: 灵田
CMD_SPIRIT_FARM_INFO = "我的灵田"
CMD_SPIRIT_FARM_CREATE = "开垦灵田"
CMD_SPIRIT_FARM_PLANT = "种植"
CMD_SPIRIT_FARM_HARVEST = "收获"
CMD_SPIRIT_FARM_UPGRADE = "升级灵田"

# Phase 4: 双修
CMD_DUAL_CULT_REQUEST = "双修"
CMD_DUAL_CULT_ACCEPT = "接受双修"
CMD_DUAL_CULT_REJECT = "拒绝双修"

# Phase 4: 灵眼
CMD_SPIRIT_EYE_INFO = "灵眼信息"
CMD_SPIRIT_EYE_CLAIM = "抢占灵眼"
CMD_SPIRIT_EYE_COLLECT = "灵眼收取"
CMD_SPIRIT_EYE_RELEASE = "释放灵眼"

@register(
    "astrbot_plugin_monixiuxian2",
    "linjianyan0229",
    "基于astrbot框架的文字修仙游戏（重构版）",
    "2.4.2",
    "https://github.com/xiaojuwa/astrbot_plugin_monixiuxian2"
)
class XiuXianPlugin(Star):
    """修仙插件 - 文字修仙游戏"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        _current_dir = Path(__file__).parent
        self.config_manager = ConfigManager(_current_dir)

        files_config = self.config.get("FILES", {})
        db_filename = files_config.get("DATABASE_FILE", "xiuxian_data_v2.db")
        plugin_data_path = Path(get_astrbot_data_path()) / "plugin_data" / "astrbot_plugin_monixiuxian2"
        plugin_data_path.mkdir(parents=True, exist_ok=True)
        db_path = plugin_data_path / db_filename
        self.db = DataBase(str(db_path))

        self.misc_handler = MiscHandler(self.db)
        self.player_handler = PlayerHandler(self.db, self.config, self.config_manager)
        self.equipment_handler = EquipmentHandler(self.db, self.config_manager)
        self.breakthrough_handler = BreakthroughHandler(self.db, self.config_manager, self.config)
        self.pill_handler = PillHandler(self.db, self.config_manager)
        self.shop_handler = ShopHandler(self.db, self.config, self.config_manager)
        self.storage_ring_handler = StorageRingHandler(self.db, self.config_manager)
        
        # 初始化核心管理器
        self.combat_mgr = CombatManager()
        self.sect_mgr = SectManager(self.db, self.config_manager)
        self.boss_mgr = BossManager(self.db, self.combat_mgr, self.config_manager)
        self.rift_mgr = RiftManager(self.db, self.config_manager)
        self.rank_mgr = RankingManager(self.db, self.combat_mgr)
        self.adventure_mgr = AdventureManager(self.db)
        self.alchemy_mgr = AlchemyManager(self.db, self.config_manager)
        self.impart_mgr = ImpartManager(self.db)

        # 初始化新功能处理器
        self.sect_handlers = SectHandlers(self.db, self.sect_mgr)
        self.boss_handlers = BossHandlers(self.db, self.boss_mgr)
        self.combat_handlers = CombatHandlers(self.db, self.combat_mgr, self.config_manager)
        self.ranking_handlers = RankingHandlers(self.db, self.rank_mgr)
        self.rift_handlers = RiftHandlers(self.db, self.rift_mgr)
        self.adventure_handlers = AdventureHandlers(self.db, self.adventure_mgr)
        self.alchemy_handlers = AlchemyHandlers(self.db, self.alchemy_mgr)
        self.impart_handlers = ImpartHandlers(self.db, self.impart_mgr)
        self.nickname_handler = NicknameHandler(self.db)  # Phase 1
        
        # Phase 2: 灵石银行和悬赏令
        self.bank_mgr = BankManager(self.db)
        self.bounty_mgr = BountyManager(self.db)
        self.bank_handlers = BankHandlers(self.db, self.bank_mgr)
        self.bounty_handlers = BountyHandlers(self.db, self.bounty_mgr)
        
        # Phase 3: 传承PK
        self.impart_pk_mgr = ImpartPkManager(self.db, self.combat_mgr)
        self.impart_pk_handlers = ImpartPkHandlers(self.db, self.impart_pk_mgr)
        
        # Phase 4: 扩展功能
        self.blessed_land_mgr = BlessedLandManager(self.db)
        self.blessed_land_handlers = BlessedLandHandlers(self.db, self.blessed_land_mgr)
        self.spirit_farm_mgr = SpiritFarmManager(self.db)
        self.spirit_farm_handlers = SpiritFarmHandlers(self.db, self.spirit_farm_mgr)
        self.dual_cult_mgr = DualCultivationManager(self.db)
        self.dual_cult_handlers = DualCultivationHandlers(self.db, self.dual_cult_mgr)
        self.spirit_eye_mgr = SpiritEyeManager(self.db)
        self.spirit_eye_handlers = SpiritEyeHandlers(self.db, self.spirit_eye_mgr)
        
        self.boss_task = None # Boss生成任务

        access_control_config = self.config.get("ACCESS_CONTROL", {})
        self.whitelist_groups = [str(g) for g in access_control_config.get("WHITELIST_GROUPS", [])]

        logger.info(f"【修仙插件】XiuXianPlugin 初始化完成，数据库路径: {db_path}")

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
        
        # 启动定时任务
        self.boss_task = asyncio.create_task(self._schedule_boss_spawn())
        
        logger.info("【修仙插件】已加载。")

    async def terminate(self):
        if self.boss_task:
            self.boss_task.cancel()
        await self.db.close()
        logger.info("【修仙插件】已卸载。")
        
    async def _schedule_boss_spawn(self):
        """Boss定时生成任务"""
        while True:
            try:
                # 获取配置的刷新时间
                interval = self.config_manager.boss_config.get("spawn_interval", 3600)
                await asyncio.sleep(interval)
                
                # 尝试生成Boss
                if self.boss_mgr:
                    success, msg, boss = await self.boss_mgr.auto_spawn_boss()
                    if success and boss:
                        logger.info(f"【修仙插件】自动生成Boss: {boss.boss_name}")
                        # 这里无法直接发送群消息通知，因为没有event上下文
                        # 实际应用中可能需要保存Context引用并广播
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Boss生成任务异常: {e}")
                await asyncio.sleep(60) # 出错后等待1分钟重试

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

    @filter.command(CMD_PILL_PAVILION, "查看丹阁丹药")
    async def handle_pill_pavilion(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.shop_handler.handle_pill_pavilion(event):
            yield r

    @filter.command(CMD_WEAPON_PAVILION, "查看器阁武器")
    async def handle_weapon_pavilion(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.shop_handler.handle_weapon_pavilion(event):
            yield r

    @filter.command(CMD_TREASURE_PAVILION, "查看百宝阁物品")
    async def handle_treasure_pavilion(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.shop_handler.handle_treasure_pavilion(event):
            yield r

    @filter.command(CMD_BUY, "购买物品")
    async def handle_buy(self, event: AstrMessageEvent, item_name: str = ""):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.shop_handler.handle_buy(event, item_name):
            yield r

    @filter.command(CMD_STORAGE_RING, "查看储物戒信息")
    async def handle_storage_ring(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.storage_ring_handler.handle_storage_ring(event):
            yield r

    @filter.command(CMD_STORE_ITEM, "存入物品到储物戒")
    async def handle_store_item(self, event: AstrMessageEvent, args: str = ""):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.storage_ring_handler.handle_store_item(event, args):
            yield r

    @filter.command(CMD_RETRIEVE_ITEM, "从储物戒取出物品")
    async def handle_retrieve_item(self, event: AstrMessageEvent, args: str = ""):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.storage_ring_handler.handle_retrieve_item(event, args):
            yield r

    @filter.command(CMD_UPGRADE_RING, "升级储物戒")
    async def handle_upgrade_ring(self, event: AstrMessageEvent, ring_name: str = ""):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.storage_ring_handler.handle_upgrade_ring(event, ring_name):
            yield r

    @filter.command(CMD_DISCARD_ITEM, "丢弃储物戒中的物品")
    async def handle_discard_item(self, event: AstrMessageEvent, args: str = ""):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.storage_ring_handler.handle_discard_item(event, args):
            yield r

    @filter.command(CMD_GIFT_ITEM, "赠予物品给其他玩家")
    async def handle_gift_item(self, event: AstrMessageEvent, args: str = ""):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.storage_ring_handler.handle_gift_item(event, args):
            yield r

    @filter.command(CMD_ACCEPT_GIFT, "接收赠予的物品")
    async def handle_accept_gift(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.storage_ring_handler.handle_accept_gift(event):
            yield r

    @filter.command(CMD_REJECT_GIFT, "拒绝赠予的物品")
    async def handle_reject_gift(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.storage_ring_handler.handle_reject_gift(event):
            yield r

    # ================= 宗门系统指令 =================

    @filter.command(CMD_CREATE_SECT, "创建宗门")
    async def handle_create_sect(self, event: AstrMessageEvent, name: str = ""):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        if not name:
            yield event.plain_result(f"请输入宗门名称，例如：/{CMD_CREATE_SECT} 逍遥门")
            return
        async for r in self.sect_handlers.handle_create_sect(event, name):
            yield r

    @filter.command(CMD_JOIN_SECT, "加入宗门")
    async def handle_join_sect(self, event: AstrMessageEvent, name: str = ""):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        if not name:
            yield event.plain_result(f"请输入要加入的宗门名称，例如：/{CMD_JOIN_SECT} 逍遥门")
            return
        async for r in self.sect_handlers.handle_join_sect(event, name):
            yield r

    @filter.command(CMD_LEAVE_SECT, "退出当前宗门")
    async def handle_leave_sect(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.sect_handlers.handle_leave_sect(event):
            yield r

    @filter.command(CMD_MY_SECT, "查看我的宗门信息")
    async def handle_my_sect(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.sect_handlers.handle_my_sect(event):
            yield r

    @filter.command(CMD_SECT_TASK, "执行宗门任务")
    async def handle_sect_task(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.sect_handlers.handle_sect_task(event):
            yield r

    @filter.command(CMD_SECT_LIST, "查看宗门列表")
    async def handle_sect_list(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.sect_handlers.handle_sect_list(event):
            yield r

    @filter.command(CMD_SECT_DONATE, "宗门捐献")
    async def handle_sect_donate(self, event: AstrMessageEvent, amount: int = 0):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        if amount <= 0:
             yield event.plain_result(f"请输入捐献数量，例如：/{CMD_SECT_DONATE} 1000")
             return
        async for r in self.sect_handlers.handle_donate(event, amount):
            yield r

    @filter.command(CMD_SECT_KICK, "踢出宗门成员")
    async def handle_sect_kick(self, event: AstrMessageEvent, target: str = ""):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.sect_handlers.handle_kick_member(event, target):
            yield r

    @filter.command(CMD_SECT_TRANSFER, "宗主传位")
    async def handle_sect_transfer(self, event: AstrMessageEvent, target: str = ""):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.sect_handlers.handle_transfer(event, target):
            yield r

    @filter.command(CMD_SECT_POSITION, "变更成员职位")
    async def handle_sect_position(self, event: AstrMessageEvent, target: str = "", position: int = -1):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        if position < 0:
            yield event.plain_result(f"请输入目标和职位ID(0-4)，例如：/{CMD_SECT_POSITION} @某人 1")
            return
        async for r in self.sect_handlers.handle_position_change(event, target, position):
            yield r

    # ================= Boss系统指令 =================

    @filter.command(CMD_BOSS_INFO, "查看世界Boss状态")
    async def handle_boss_info(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.boss_handlers.handle_boss_info(event):
            yield r

    @filter.command(CMD_BOSS_FIGHT, "挑战世界Boss")
    async def handle_boss_fight(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.boss_handlers.handle_boss_fight(event):
            yield r

    @filter.command(CMD_SPAWN_BOSS, "生成世界Boss(管理员)")
    async def handle_spawn_boss(self, event: AstrMessageEvent):
        # 暂时开放给所有人测试，实际应该鉴权
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.boss_handlers.handle_spawn_boss(event):
            yield r

    # ================= 排行榜指令 =================

    @filter.command(CMD_RANK_LEVEL, "查看境界排行榜")
    async def handle_rank_level(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.ranking_handlers.handle_rank_level(event):
            yield r

    @filter.command(CMD_RANK_POWER, "查看战力排行榜")
    async def handle_rank_power(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.ranking_handlers.handle_rank_power(event):
            yield r

    @filter.command(CMD_RANK_WEALTH, "查看财富排行榜")
    async def handle_rank_wealth(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.ranking_handlers.handle_rank_wealth(event):
            yield r

    @filter.command(CMD_RANK_SECT, "查看宗门排行榜")
    async def handle_rank_sect(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.ranking_handlers.handle_rank_sect(event):
            yield r

    # ================= 战斗指令 =================

    @filter.command(CMD_DUEL, "与其他玩家决斗(消耗气血)")
    async def handle_duel(self, event: AstrMessageEvent, target: str = ""):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.combat_handlers.handle_duel(event, target):
            yield r
            
    @filter.command(CMD_SPAR, "与其他玩家切磋(无消耗)")
    async def handle_spar(self, event: AstrMessageEvent, target: str = ""):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.combat_handlers.handle_spar(event, target):
            yield r

    # ================= 秘境指令 =================
    @filter.command(CMD_RIFT_LIST, "查看秘境列表")
    async def handle_rift_list(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.rift_handlers.handle_rift_list(event):
            yield r

    @filter.command(CMD_RIFT_EXPLORE, "探索秘境")
    async def handle_rift_explore(self, event: AstrMessageEvent, rift_id: int = 0):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.rift_handlers.handle_rift_explore(event, rift_id):
            yield r

    @filter.command(CMD_RIFT_COMPLETE, "完成秘境探索")
    async def handle_rift_complete(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.rift_handlers.handle_rift_complete(event):
            yield r

    # ================= 历练指令 =================
    @filter.command(CMD_ADVENTURE_START, "开始历练")
    async def handle_adventure_start(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        # 这里默认 medium，后续可以解析参数
        async for r in self.adventure_handlers.handle_start_adventure(event, "medium"):
            yield r

    @filter.command(CMD_ADVENTURE_COMPLETE, "完成历练")
    async def handle_adventure_complete(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.adventure_handlers.handle_complete_adventure(event):
            yield r

    @filter.command(CMD_ADVENTURE_STATUS, "查看历练状态")
    async def handle_adventure_status(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.adventure_handlers.handle_adventure_status(event):
            yield r

    @filter.command(CMD_ADVENTURE_INFO, "查看历练系统说明")
    async def handle_adventure_info(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.adventure_handlers.handle_adventure_info(event):
            yield r

    # ================= 炼丹指令 =================
    @filter.command(CMD_ALCHEMY_RECIPES, "查看丹药配方")
    async def handle_alchemy_recipes(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.alchemy_handlers.handle_recipes(event):
            yield r

    @filter.command(CMD_ALCHEMY_CRAFT, "炼制丹药")
    async def handle_alchemy_craft(self, event: AstrMessageEvent, pill_id: int = 0):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.alchemy_handlers.handle_craft(event, pill_id):
            yield r

    # ================= 传承指令 =================
    @filter.command(CMD_IMPART_INFO, "查看传承信息")
    async def handle_impart_info(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.impart_handlers.handle_impart_info(event):
            yield r

    # ================= Phase 1: 道号系统 =================
    @filter.command(CMD_CHANGE_NICKNAME, "修改道号")
    async def handle_change_nickname(self, event: AstrMessageEvent, new_name: str = ""):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.nickname_handler.handle_change_nickname(event, new_name):
            yield r

    # ================= Phase 2: 灵石银行 =================
    @filter.command(CMD_BANK_INFO, "查看银行信息")
    async def handle_bank_info(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.bank_handlers.handle_bank_info(event):
            yield r

    @filter.command(CMD_BANK_DEPOSIT, "存入灵石")
    async def handle_bank_deposit(self, event: AstrMessageEvent, amount: int = 0):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.bank_handlers.handle_deposit(event, amount):
            yield r

    @filter.command(CMD_BANK_WITHDRAW, "取出灵石")
    async def handle_bank_withdraw(self, event: AstrMessageEvent, amount: int = 0):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.bank_handlers.handle_withdraw(event, amount):
            yield r

    @filter.command(CMD_BANK_INTEREST, "领取利息")
    async def handle_bank_interest(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.bank_handlers.handle_claim_interest(event):
            yield r

    # ================= Phase 2: 悬赏令 =================
    @filter.command(CMD_BOUNTY_LIST, "查看悬赏任务")
    async def handle_bounty_list(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.bounty_handlers.handle_bounty_list(event):
            yield r

    @filter.command(CMD_BOUNTY_ACCEPT, "接取悬赏任务")
    async def handle_bounty_accept(self, event: AstrMessageEvent, bounty_id: int = 0):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.bounty_handlers.handle_accept_bounty(event, bounty_id):
            yield r

    @filter.command(CMD_BOUNTY_STATUS, "查看悬赏状态")
    async def handle_bounty_status(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.bounty_handlers.handle_bounty_status(event):
            yield r

    @filter.command(CMD_BOUNTY_COMPLETE, "完成悬赏任务")
    async def handle_bounty_complete(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.bounty_handlers.handle_complete_bounty(event):
            yield r

    @filter.command(CMD_BOUNTY_ABANDON, "放弃悬赏任务")
    async def handle_bounty_abandon(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.bounty_handlers.handle_abandon_bounty(event):
            yield r

    # ================= Phase 3: 传承PK =================
    @filter.command(CMD_IMPART_CHALLENGE, "发起传承挑战")
    async def handle_impart_challenge(self, event: AstrMessageEvent, target: str = ""):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.impart_pk_handlers.handle_impart_challenge(event, target):
            yield r

    @filter.command(CMD_IMPART_RANKING, "查看传承排行")
    async def handle_impart_ranking(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.impart_pk_handlers.handle_impart_ranking(event):
            yield r

    # ================= Phase 4: 洞天福地 =================
    @filter.command(CMD_BLESSED_LAND_INFO, "查看洞天信息")
    async def handle_blessed_land_info(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.blessed_land_handlers.handle_blessed_land_info(event):
            yield r

    @filter.command(CMD_BLESSED_LAND_BUY, "购买洞天")
    async def handle_blessed_land_buy(self, event: AstrMessageEvent, land_type: int = 0):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.blessed_land_handlers.handle_purchase(event, land_type):
            yield r

    @filter.command(CMD_BLESSED_LAND_UPGRADE, "升级洞天")
    async def handle_blessed_land_upgrade(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.blessed_land_handlers.handle_upgrade(event):
            yield r

    @filter.command(CMD_BLESSED_LAND_COLLECT, "收取洞天产出")
    async def handle_blessed_land_collect(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.blessed_land_handlers.handle_collect(event):
            yield r

    # ================= Phase 4: 灵田 =================
    @filter.command(CMD_SPIRIT_FARM_INFO, "查看灵田")
    async def handle_spirit_farm_info(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.spirit_farm_handlers.handle_farm_info(event):
            yield r

    @filter.command(CMD_SPIRIT_FARM_CREATE, "开垦灵田")
    async def handle_spirit_farm_create(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.spirit_farm_handlers.handle_create_farm(event):
            yield r

    @filter.command(CMD_SPIRIT_FARM_PLANT, "种植灵草")
    async def handle_spirit_farm_plant(self, event: AstrMessageEvent, herb_name: str = ""):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.spirit_farm_handlers.handle_plant(event, herb_name):
            yield r

    @filter.command(CMD_SPIRIT_FARM_HARVEST, "收获灵草")
    async def handle_spirit_farm_harvest(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.spirit_farm_handlers.handle_harvest(event):
            yield r

    @filter.command(CMD_SPIRIT_FARM_UPGRADE, "升级灵田")
    async def handle_spirit_farm_upgrade(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.spirit_farm_handlers.handle_upgrade_farm(event):
            yield r

    # ================= Phase 4: 双修 =================
    @filter.command(CMD_DUAL_CULT_REQUEST, "发起双修")
    async def handle_dual_cult_request(self, event: AstrMessageEvent, target: str = ""):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.dual_cult_handlers.handle_dual_request(event, target):
            yield r

    @filter.command(CMD_DUAL_CULT_ACCEPT, "接受双修")
    async def handle_dual_cult_accept(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.dual_cult_handlers.handle_accept(event):
            yield r

    @filter.command(CMD_DUAL_CULT_REJECT, "拒绝双修")
    async def handle_dual_cult_reject(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.dual_cult_handlers.handle_reject(event):
            yield r

    # ================= Phase 4: 天地灵眼 =================
    @filter.command(CMD_SPIRIT_EYE_INFO, "查看灵眼")
    async def handle_spirit_eye_info(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.spirit_eye_handlers.handle_spirit_eye_info(event):
            yield r

    @filter.command(CMD_SPIRIT_EYE_CLAIM, "抢占灵眼")
    async def handle_spirit_eye_claim(self, event: AstrMessageEvent, eye_id: int = 0):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.spirit_eye_handlers.handle_claim(event, eye_id):
            yield r

    @filter.command(CMD_SPIRIT_EYE_COLLECT, "收取灵眼产出")
    async def handle_spirit_eye_collect(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.spirit_eye_handlers.handle_collect(event):
            yield r

    @filter.command(CMD_SPIRIT_EYE_RELEASE, "释放灵眼")
    async def handle_spirit_eye_release(self, event: AstrMessageEvent):
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for r in self.spirit_eye_handlers.handle_release(event):
            yield r
