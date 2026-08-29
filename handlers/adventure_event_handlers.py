"""
奇遇事件处理器
"""
from astrbot.api.event import AstrMessageEvent
from ..data import DataBase
from ..models import Player
from ..managers.adventure_event_manager import AdventureEventManager
from .utils import player_required


class AdventureEventHandlers:
    """奇遇事件处理器"""
    
    def __init__(self, db: DataBase, adventure_event_mgr: AdventureEventManager):
        self.db = db
        self.adventure_event_mgr = adventure_event_mgr
    
    @player_required
    async def handle_wander(self, player: Player, event: AstrMessageEvent):
        """处理游历指令 - 主动触发奇遇"""
        # 检查是否有进行中的奇遇
        if await self.adventure_event_mgr.has_active_event(player):
            active = await self.adventure_event_mgr.get_active_event(player)
            event_name = active.event_data.get('name', '未知') if active else '未知'
            yield event.plain_result(
                f"❌ 你正在进行奇遇【{event_name}】\n"
                f"请先完成当前奇遇，或发送「放弃奇遇」放弃"
            )
            return
        
        # 检查玩家状态
        try:
            from ..models_extended import UserStatus
            user_cd = await self.db.ext.get_user_cd(player.user_id)
            if user_cd and user_cd.type != UserStatus.IDLE:
                status_name = UserStatus.get_name(user_cd.type)
                yield event.plain_result(f"❌ 你当前正在{status_name}，无法游历")
                return
        except ImportError:
            # 如果模块不存在，跳过状态检查
            pass
        except AttributeError:
            # 如果方法不存在，跳过状态检查
            pass
        
        # 尝试触发奇遇
        triggered, msg, data = await self.adventure_event_mgr.try_trigger_event(
            player, "wander", {}
        )
        
        if not triggered:
            if msg:
                yield event.plain_result(msg)
            else:
                yield event.plain_result(
                    "🚶 你四处游历，但今日并无奇遇...\n"
                    "━━━━━━━━━━━━━━━\n"
                    "💡 奇遇可遇不可求，稍后再试吧"
                )
            return
        
        yield event.plain_result(msg)
    
    @player_required
    async def handle_event_choice(self, player: Player, event: AstrMessageEvent, choice: int = 0):
        """处理奇遇选择"""
        # 确保 choice 是整数
        try:
            choice = int(choice)
        except (ValueError, TypeError):
            choice = 0
            
        if choice <= 0:
            yield event.plain_result("❌ 请输入有效的选择编号，如：奇遇选择 1")
            return
        
        success, msg = await self.adventure_event_mgr.handle_choice(player, choice)
        yield event.plain_result(msg)
    
    @player_required
    async def handle_event_battle(self, player: Player, event: AstrMessageEvent):
        """处理奇遇战斗"""
        success, msg = await self.adventure_event_mgr.handle_battle(player)
        yield event.plain_result(msg)
    
    @player_required
    async def handle_abandon_event(self, player: Player, event: AstrMessageEvent):
        """放弃当前奇遇"""
        success, msg = await self.adventure_event_mgr.abandon_event(player)
        yield event.plain_result(msg)
    
    @player_required
    async def handle_event_status(self, player: Player, event: AstrMessageEvent):
        """查看当前奇遇状态"""
        active = await self.adventure_event_mgr.get_active_event(player)
        
        if not active:
            yield event.plain_result(
                "📜 当前没有进行中的奇遇\n"
                "━━━━━━━━━━━━━━━\n"
                "💡 发送「游历」主动寻找奇遇\n"
                "💡 闭关出关、完成历练等也可能触发奇遇"
            )
            return
        
        event_data = active.event_data
        rarity_names = {
            "common": "普通",
            "rare": "稀有",
            "epic": "史诗",
            "legendary": "传说"
        }
        rarity = event_data.get('rarity', 'common')
        rarity_name = rarity_names.get(rarity, '普通')
        
        type_names = {
            "fortune": "机缘",
            "inheritance": "传承",
            "challenge": "挑战",
            "choice": "抉择",
            "story": "剧情"
        }
        type_name = type_names.get(event_data.get('type', ''), '未知')
        
        msg = (
            f"📜 当前奇遇：【{event_data.get('name', '未知')}】\n"
            f"━━━━━━━━━━━━━━━\n"
            f"类型：{type_name}\n"
            f"稀有度：{rarity_name}\n"
        )
        
        if active.pending_choice:
            msg += "\n⏳ 等待你的选择...\n"
            msg += "💡 发送「奇遇选择 <编号>」进行选择"
        elif active.battle_pending:
            msg += "\n⚔️ 等待战斗...\n"
            msg += "💡 发送「奇遇战斗」开始战斗"
        
        msg += "\n\n💡 发送「放弃奇遇」可放弃当前奇遇"
        
        yield event.plain_result(msg)
