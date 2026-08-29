# handlers/blessed_land_handlers.py
"""洞天福地处理器"""
from astrbot.api.event import AstrMessageEvent
from ..data import DataBase
from ..managers.blessed_land_manager import BlessedLandManager, BLESSED_LANDS, get_realm_name
from ..models import Player
from .utils import player_required

__all__ = ["BlessedLandHandlers"]


class BlessedLandHandlers:
    """洞天福地处理器"""
    
    def __init__(self, db: DataBase, blessed_land_mgr: BlessedLandManager):
        self.db = db
        self.mgr = blessed_land_mgr
    
    @player_required
    async def handle_blessed_land_info(self, player: Player, event: AstrMessageEvent):
        """查看洞天信息"""
        info = await self.mgr.get_blessed_land_info(player.user_id, player)
        yield event.plain_result(info)
    
    @player_required
    async def handle_purchase(self, player: Player, event: AstrMessageEvent, land_type: int = 0):
        """购买洞天"""
        if land_type <= 0:
            # 显示购买帮助，包含境界要求
            lines = [
                "🏔️ 购买洞天",
                "━━━━━━━━━━━━━━━",
                "初始只能购买小洞天，通过进阶系统提升洞天品质。\n",
            ]
            
            for lt, config in BLESSED_LANDS.items():
                required_realm = get_realm_name(config["required_level_index"])
                can_buy = player.level_index >= config["required_level_index"]
                status = "✅ 可购买" if can_buy else f"🔒 需{required_realm}"
                bonus = f"+{config['exp_bonus']:.0%}修炼"
                lines.append(f"{lt}. {config['name']} - {config['price']:,}灵石 ({bonus}) {status}")
            
            lines.extend([
                "",
                "━━━━━━━━━━━━━━━",
                "💡 使用 /购买洞天 1",
                "⚠️ 初始只能购买小洞天"
            ])
            
            yield event.plain_result("\n".join(lines))
            return
        
        success, msg = await self.mgr.purchase_blessed_land(player, land_type)
        yield event.plain_result(msg)
    
    @player_required
    async def handle_upgrade(self, player: Player, event: AstrMessageEvent):
        """升级洞天"""
        success, msg = await self.mgr.upgrade_blessed_land(player)
        yield event.plain_result(msg)
    
    @player_required
    async def handle_collect(self, player: Player, event: AstrMessageEvent):
        """收取洞天产出"""
        success, msg = await self.mgr.collect_income(player)
        yield event.plain_result(msg)
    
    @player_required
    async def handle_advance(self, player: Player, event: AstrMessageEvent, target_type: int = 0):
        """进阶洞天"""
        if target_type <= 0:
            # 显示进阶帮助，包含境界要求
            lines = [
                "🏔️ 进阶洞天",
                "━━━━━━━━━━━━━━━",
                "请指定目标洞天类型：\n",
            ]
            
            for lt in range(2, 6):
                config = BLESSED_LANDS[lt]
                required_realm = get_realm_name(config["required_level_index"])
                can_advance = player.level_index >= config["required_level_index"]
                status = "✅" if can_advance else f"🔒 需{required_realm}"
                from_land = BLESSED_LANDS[lt - 1]["name"]
                lines.append(f"{lt}. {config['name']} (从{from_land}进阶) {status}")
            
            lines.extend([
                "",
                "━━━━━━━━━━━━━━━",
                "💡 使用 /进阶洞天 <编号>",
                "⚠️ 需要当前洞天满级才能进阶"
            ])
            
            yield event.plain_result("\n".join(lines))
            return
        
        success, msg = await self.mgr.advance_blessed_land(player, target_type)
        yield event.plain_result(msg)
