# handlers/adventure_handlers.py
from astrbot.api.event import AstrMessageEvent
from ..managers.adventure_manager import AdventureManager
from ..data.data_manager import DataBase

class AdventureHandlers:
    def __init__(self, db: DataBase, adv_mgr: AdventureManager):
        self.db = db
        self.adv_mgr = adv_mgr

    async def handle_adventure_info(self, event: AstrMessageEvent):
        """历练信息 - 显示概率和奖励"""
        info = (
            "📖 历练系统说明\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "\n"
            "⏱️ 历练时长：\n"
            "  • 短途历练：30分钟\n"
            "  • 中途历练：60分钟（默认）\n"
            "  • 长途历练：120分钟\n"
            "\n"
            "🎲 事件概率：\n"
            "  ✨ 好事（30%）：奖励 ×1.5~2.0\n"
            "     - 修为感悟、秘宝发现\n"
            "     - 突破瓶颈、前辈传承\n"
            "  📌 普通（50%）：奖励 ×1.0~1.2\n"
            "     - 顺利完成、击败妖兽\n"
            "  ⚠️ 坏事（20%）：奖励 ×0.5~0.8\n"
            "     - 遭遇埋伏、迷路、被劫\n"
            "\n"
            "💰 奖励计算：\n"
            "  修为 = 当前修为×5%×时长(小时)×事件倍率\n"
            "  灵石 = 当前修为×2%×时长(小时)×事件倍率\n"
            "\n"
            "💡 指令：\n"
            "  /开始历练 [短途/中途/长途]\n"
            "  /历练状态 - 查看进度\n"
            "  /完成历练 - 领取奖励\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        yield event.plain_result(info)

    async def handle_start_adventure(self, event: AstrMessageEvent, type_: str = "medium"):
        """开始历练"""
        user_id = event.get_sender_id()
        success, msg = await self.adv_mgr.start_adventure(user_id, type_)
        yield event.plain_result(msg)

    async def handle_complete_adventure(self, event: AstrMessageEvent):
        """完成历练"""
        user_id = event.get_sender_id()
        success, msg, _ = await self.adv_mgr.finish_adventure(user_id)
        yield event.plain_result(msg)
    
    async def handle_adventure_status(self, event: AstrMessageEvent):
        """历练状态"""
        user_id = event.get_sender_id()
        success, msg = await self.adv_mgr.check_adventure_status(user_id)
        yield event.plain_result(msg)

