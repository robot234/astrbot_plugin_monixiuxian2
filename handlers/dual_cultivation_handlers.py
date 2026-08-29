# handlers/dual_cultivation_handlers.py
"""道侣系统处理器 - 共享功能版本"""
import re
from astrbot.api.event import AstrMessageEvent
from astrbot.api.all import At
from ..data import DataBase
from ..managers.dual_cultivation_manager import DualCultivationManager
from ..models import Player
from .utils import player_required

__all__ = ["DualCultivationHandlers"]


class DualCultivationHandlers:
    """道侣系统处理器"""
    
    def __init__(self, db: DataBase, dual_mgr: DualCultivationManager):
        self.db = db
        self.mgr = dual_mgr
        self.pill_mgr = None  # 丹药管理器，需要外部注入
    
    def set_pill_manager(self, pill_mgr):
        """设置丹药管理器（用于延迟注入）"""
        self.pill_mgr = pill_mgr
    
    # ==================== 道侣关系 ====================
    
    @player_required
    async def handle_partner_request(self, player: Player, event: AstrMessageEvent, target: str = ""):
        """发起道侣请求"""
        target_id = self._extract_target_id(event, target)
        
        if not target_id:
            yield event.plain_result(
                "💕 道侣系统\n"
                "━━━━━━━━━━━━━━━\n"
                "与他人结为道侣，共享资源！\n"
                "━━━━━━━━━━━━━━━\n"
                "道侣共享功能：\n"
                "• 共享储物戒 - 可取用对方物品\n"
                "• 共享丹药 - 可使用对方丹药\n"
                "• 共享灵石 - 灵石合并使用\n"
                "• 修炼加速 - 同时闭关加速修炼\n"
                "━━━━━━━━━━━━━━━\n"
                "💡 使用「求道侣 @某人」发起请求"
            )
            return
        
        success, msg = await self.mgr.send_partner_request(player, target_id)
        yield event.plain_result(msg)
    
    @player_required
    async def handle_accept_partner(self, player: Player, event: AstrMessageEvent):
        """接受道侣请求"""
        success, msg = await self.mgr.accept_partner_request(player)
        yield event.plain_result(msg)
    
    @player_required
    async def handle_reject_partner(self, player: Player, event: AstrMessageEvent):
        """拒绝道侣请求"""
        success, msg = await self.mgr.reject_partner_request(player.user_id)
        yield event.plain_result(msg)
    
    @player_required
    async def handle_partner_info(self, player: Player, event: AstrMessageEvent):
        """查看道侣信息"""
        success, msg = await self.mgr.get_partner_info(player)
        yield event.plain_result(msg)
    
    @player_required
    async def handle_break_up(self, player: Player, event: AstrMessageEvent, confirm: str = ""):
        """解除道侣关系"""
        is_confirm = confirm.strip() == "确认"
        success, msg = await self.mgr.break_up(player, is_confirm)
        yield event.plain_result(msg)
    
    # ==================== 道侣双修 ====================
    
    @player_required
    async def handle_partner_dual_cultivate(self, player: Player, event: AstrMessageEvent):
        """道侣双修"""
        success, msg = await self.mgr.dual_cultivate(player)
        yield event.plain_result(msg)
    
    # ==================== 共享灵石 ====================
    
    @player_required
    async def handle_shared_gold(self, player: Player, event: AstrMessageEvent):
        """查看共享灵石"""
        success, msg, total = await self.mgr.get_shared_gold(player)
        yield event.plain_result(msg)
    
    # ==================== 共享储物戒 ====================
    
    @player_required
    async def handle_partner_storage(self, player: Player, event: AstrMessageEvent):
        """查看道侣储物戒"""
        success, msg, items = await self.mgr.get_partner_storage_ring(player)
        yield event.plain_result(msg)
    
    @player_required
    async def handle_partner_take(self, player: Player, event: AstrMessageEvent, args: str = ""):
        """从道侣储物戒取出物品"""
        if not args:
            yield event.plain_result(
                "📦 道侣取出\n"
                "━━━━━━━━━━━━━━━\n"
                "从道侣储物戒取出物品\n"
                "━━━━━━━━━━━━━━━\n"
                "💡 使用「道侣取出 物品名」取出1个\n"
                "💡 使用「道侣取出 物品名 数量」取出多个\n"
                "例如：道侣取出 灵草 5"
            )
            return
        
        # 解析参数
        parts = args.strip().split()
        item_name = parts[0]
        count = 1
        if len(parts) > 1:
            try:
                count = int(parts[-1])
                if count <= 0:
                    count = 1
            except ValueError:
                # 最后一个不是数字，可能是物品名的一部分
                item_name = args.strip()
        
        success, msg = await self.mgr.take_from_partner_storage(player, item_name, count)
        yield event.plain_result(msg)
    
    # ==================== 共享丹药 ====================
    
    @player_required
    async def handle_partner_pills(self, player: Player, event: AstrMessageEvent):
        """查看道侣丹药背包"""
        success, msg, pills = await self.mgr.get_partner_pills(player)
        yield event.plain_result(msg)
    
    @player_required
    async def handle_partner_use_pill(self, player: Player, event: AstrMessageEvent, pill_name: str = ""):
        """使用道侣的丹药"""
        if not pill_name:
            yield event.plain_result(
                "💊 道侣服用\n"
                "━━━━━━━━━━━━━━━\n"
                "使用道侣丹药背包中的丹药\n"
                "━━━━━━━━━━━━━━━\n"
                "💡 使用「道侣服用 丹药名」\n"
                "例如：道侣服用 培元丹"
            )
            return
        
        # 调用管理器的方法来使用道侣丹药
        success, result = await self.mgr.use_partner_pill_with_effect(player, pill_name, self.pill_mgr)
        yield event.plain_result(result)
    
    # ==================== 普通双修 ====================
    
    @player_required
    async def handle_dual_request(self, player: Player, event: AstrMessageEvent, target: str = ""):
        """发起普通双修请求"""
        target_id = self._extract_target_id(event, target)
        
        if not target_id:
            if player.has_partner():
                yield event.plain_result(
                    "💕 双修系统\n"
                    "━━━━━━━━━━━━━━━\n"
                    "你已有道侣，请使用「道侣双修」指令\n"
                    "与道侣双修可获得更多功能！"
                )
                return
            
            yield event.plain_result(
                "💕 双修系统\n"
                "━━━━━━━━━━━━━━━\n"
                "与他人双修可获得对方10%的修为！\n"
                "冷却时间：1小时\n"
                "━━━━━━━━━━━━━━━\n"
                "💡 使用「双修 @某人」发起请求\n"
                "💡 结为道侣后可解锁共享功能哦~"
            )
            return
        
        success, msg = await self.mgr.send_dual_request(player, target_id)
        yield event.plain_result(msg)
    
    @player_required
    async def handle_accept(self, player: Player, event: AstrMessageEvent):
        """接受双修"""
        success, msg = await self.mgr.accept_dual_request(player)
        yield event.plain_result(msg)
    
    @player_required
    async def handle_reject(self, player: Player, event: AstrMessageEvent):
        """拒绝双修"""
        success, msg = await self.mgr.reject_dual_request(player.user_id)
        yield event.plain_result(msg)
    
    # ==================== 工具方法 ====================
    
    def _extract_target_id(self, event: AstrMessageEvent, target: str) -> str:
        """从消息中提取目标用户ID"""
        target_id = None
        for component in event.message_obj.message:
            if isinstance(component, At):
                target_id = str(component.qq)
                break
        
        if not target_id:
            target_id = self._extract_user_id(target)
        
        return target_id or ""
    
    def _extract_user_id(self, msg: str) -> str:
        """提取用户ID"""
        if not msg:
            return ""
        at_match = re.search(r'\[CQ:at,qq=(\d+)\]', msg)
        if at_match:
            return at_match.group(1)
        num_match = re.search(r'(\d{5,12})', msg)
        if num_match:
            return num_match.group(1)
        return ""
