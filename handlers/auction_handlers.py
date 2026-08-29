# handlers/auction_handlers.py
"""
拍卖系统处理器
"""

from astrbot.api.event import AstrMessageEvent
from ..data import DataBase
from ..models import Player
from ..config_manager import ConfigManager
from ..managers.auction_manager import AuctionManager, AuctionStatus
from ..core import StorageRingManager
from .utils import player_required

# 指令定义
CMD_AUCTION_LIST = "拍卖行"
CMD_AUCTION_CREATE = "上架拍卖"
CMD_AUCTION_BID = "竞拍"
CMD_AUCTION_BUYOUT = "一口价"
CMD_AUCTION_CANCEL = "取消拍卖"
CMD_AUCTION_MY = "我的拍卖"
CMD_AUCTION_CLAIM = "领取拍卖"
CMD_AUCTION_ROBBERY = "抢夺拍卖"
CMD_AUCTION_ROBBERY_LIST = "可抢夺"
CMD_AUCTION_INFO = "拍卖详情"

__all__ = ["AuctionHandlers"]


class AuctionHandlers:
    """拍卖系统处理器"""
    
    def __init__(
        self,
        db: DataBase,
        auction_manager: AuctionManager,
        storage_ring_manager: StorageRingManager,
        config_manager: ConfigManager,
        battle_manager,
        equipment_manager,
        skill_manager
    ):
        self.db = db
        self.auction_mgr = auction_manager
        self.storage_ring_mgr = storage_ring_manager
        self.config_manager = config_manager
        self.battle_mgr = battle_manager
        self.equipment_mgr = equipment_manager
        self.skill_mgr = skill_manager
    
    async def _apply_duel_damage(self, user_id: str, final_hp: int, max_hp: int):
        """应用决斗伤害到玩家实际HP
        
        决斗模式下，战斗结束后的HP会同步到玩家数据
        """
        player = await self.db.get_player_by_id(user_id)
        if player:
            # 按比例计算实际HP损失
            hp_ratio = final_hp / max_hp if max_hp > 0 else 1.0
            player.hp = max(1, int(player.max_hp * hp_ratio))
            player.mp = player.max_mp  # MP恢复满
            await self.db.update_player(player)
    
    @player_required
    async def handle_auction_list(self, player: Player, event: AstrMessageEvent):
        """查看拍卖列表"""
        auctions = await self.auction_mgr.get_active_auctions(limit=15)
        msg = self.auction_mgr.format_auction_list(auctions)
        yield event.plain_result(msg)
    
    @player_required
    async def handle_auction_create(
        self,
        player: Player,
        event: AstrMessageEvent,
        item_name: str = "",
        starting_price: int = 0,
        buyout_price: int = 0,
        duration: int = 120
    ):
        """上架物品到拍卖行
        
        用法：/上架拍卖 物品名 起拍价 [一口价] [时长(分钟)]
        """
        if not item_name:
            yield event.plain_result(
                f"📦 上架拍卖帮助\n"
                f"━━━━━━━━━━━━━━━\n"
                f"用法：{CMD_AUCTION_CREATE} 物品名 起拍价 [一口价] [时长]\n"
                f"示例：{CMD_AUCTION_CREATE} 精铁剑 1000 2000 120\n"
                f"━━━━━━━━━━━━━━━\n"
                f"• 起拍价：必填，最低竞拍价格\n"
                f"• 一口价：选填，直接购买价格（0表示无）\n"
                f"• 时长：选填，拍卖时长（分钟），默认120\n"
                f"• 手续费：成交价的5%\n"
                f"• 支持储物戒和丹药背包中的物品"
            )
            return
        
        if starting_price <= 0:
            yield event.plain_result("起拍价必须大于0")
            return
        
        # 检查物品来源
        source_type = None
        item_count = 1
        
        # 先检查储物戒
        storage_count = self.storage_ring_mgr.get_item_count(player, item_name)
        if storage_count > 0:
            source_type = "storage"
            item_count = 1  # 默认上架1个
        else:
            # 检查丹药背包
            pills = player.get_pills_inventory()
            if item_name in pills and pills[item_name] > 0:
                source_type = "pill"
                item_count = 1
        
        if not source_type:
            yield event.plain_result(
                f"你没有【{item_name}】！\n"
                f"请检查储物戒或丹药背包。"
            )
            return
        
        # 从背包中扣除物品
        if source_type == "storage":
            success, msg = await self.storage_ring_mgr.retrieve_item(player, item_name, item_count)
            if not success:
                yield event.plain_result(f"上架失败：{msg}")
                return
        else:
            pills = player.get_pills_inventory()
            pills[item_name] -= item_count
            if pills[item_name] <= 0:
                del pills[item_name]
            player.set_pills_inventory(pills)
            await self.db.update_player(player)
        
        # 创建拍卖
        success, msg, auction = await self.auction_mgr.create_auction(
            player=player,
            item_name=item_name,
            item_count=item_count,
            source_type=source_type,
            starting_price=starting_price,
            buyout_price=buyout_price,
            duration_minutes=duration
        )
        
        if success:
            hours = duration // 60
            minutes = duration % 60
            time_str = f"{hours}小时{minutes}分钟" if hours > 0 else f"{minutes}分钟"
            
            result_msg = (
                f"✅ 上架成功！\n"
                f"━━━━━━━━━━━━━━━\n"
                f"物品：【{item_name}】x{item_count}\n"
                f"起拍价：{starting_price} 灵石\n"
            )
            if buyout_price > 0:
                result_msg += f"一口价：{buyout_price} 灵石\n"
            result_msg += (
                f"拍卖时长：{time_str}\n"
                f"━━━━━━━━━━━━━━━\n"
                f"💡 手续费：成交价的5%"
            )
            yield event.plain_result(result_msg)
        else:
            # 上架失败，返还物品
            if source_type == "storage":
                await self.storage_ring_mgr.store_item(player, item_name, item_count, silent=True)
            else:
                pills = player.get_pills_inventory()
                pills[item_name] = pills.get(item_name, 0) + item_count
                player.set_pills_inventory(pills)
                await self.db.update_player(player)
            
            yield event.plain_result(f"❌ 上架失败：{msg}")
    
    @player_required
    async def handle_auction_bid(
        self,
        player: Player,
        event: AstrMessageEvent,
        auction_id: int = 0,
        bid_amount: int = 0
    ):
        """竞拍物品
        
        用法：/竞拍 拍卖ID 金额
        """
        if auction_id <= 0 or bid_amount <= 0:
            yield event.plain_result(
                f"📦 竞拍帮助\n"
                f"━━━━━━━━━━━━━━━\n"
                f"用法：{CMD_AUCTION_BID} 拍卖ID 金额\n"
                f"示例：{CMD_AUCTION_BID} 1 1500\n"
                f"━━━━━━━━━━━━━━━\n"
                f"• 出价必须比当前价格高10%以上\n"
                f"• 如果被超过，灵石会自动退还\n"
                f"• 出价达到一口价会直接成交"
            )
            return
        
        success, msg = await self.auction_mgr.place_bid(player, auction_id, bid_amount)
        
        if success:
            yield event.plain_result(msg)
        else:
            yield event.plain_result(f"❌ 竞拍失败：{msg}")
    
    @player_required
    async def handle_auction_cancel(
        self,
        player: Player,
        event: AstrMessageEvent,
        auction_id: int = 0
    ):
        """取消拍卖"""
        if auction_id <= 0:
            yield event.plain_result(
                f"用法：{CMD_AUCTION_CANCEL} 拍卖ID\n"
                f"注意：只能取消无人出价的拍卖"
            )
            return
        
        # 获取拍卖信息
        auction = await self.auction_mgr.get_auction_by_id(auction_id)
        if not auction:
            yield event.plain_result("拍卖不存在")
            return
        
        success, msg = await self.auction_mgr.cancel_auction(player, auction_id)
        
        if success:
            # 返还物品
            if auction.source_type == "pill":
                pills = player.get_pills_inventory()
                pills[auction.item_name] = pills.get(auction.item_name, 0) + auction.item_count
                player.set_pills_inventory(pills)
                await self.db.update_player(player)
            else:
                await self.storage_ring_mgr.store_item(
                    player, auction.item_name, auction.item_count, silent=True
                )
            
            yield event.plain_result(
                f"✅ {msg}\n"
                f"物品已返还到你的背包"
            )
        else:
            yield event.plain_result(f"❌ {msg}")
    
    @player_required
    async def handle_my_auctions(self, player: Player, event: AstrMessageEvent):
        """查看我的拍卖"""
        # 获取上架的拍卖
        my_auctions = await self.auction_mgr.get_player_auctions(player.user_id)
        # 获取参与竞拍的
        my_bids = await self.auction_mgr.get_player_bids(player.user_id)
        # 获取可领取的
        claimable = await self.auction_mgr.get_claimable_items(player.user_id)
        
        lines = ["📦 我的拍卖\n", "━━━━━━━━━━━━━━━\n"]
        
        if claimable:
            lines.append("【待领取】\n")
            for item in claimable:
                if item.status == AuctionStatus.CANCELLED:
                    lines.append(f"  📦 [{item.id}] 【{item.item_name}】x{item.item_count} (流拍)\n")
                elif item.robber_id == player.user_id:
                    lines.append(f"  ⚔️ [{item.id}] 【{item.item_name}】x{item.item_count} (抢夺)\n")
                else:
                    lines.append(f"  🎉 [{item.id}] 【{item.item_name}】x{item.item_count} (拍得)\n")
            lines.append("\n")
        
        if my_auctions:
            lines.append("【我上架的】\n")
            for auction in my_auctions[:5]:
                status_str = self._get_status_str(auction)
                lines.append(
                    f"  [{auction.id}] 【{auction.item_name}】{status_str}\n"
                    f"      当前价：{auction.current_price} | 出价：{auction.bid_count}次\n"
                )
            lines.append("\n")
        
        if my_bids:
            lines.append("【我竞拍的】\n")
            for auction in my_bids[:5]:
                is_winning = auction.highest_bidder_id == player.user_id
                status_str = self._get_status_str(auction)
                winning_str = "👑" if is_winning else "  "
                lines.append(
                    f"  {winning_str}[{auction.id}] 【{auction.item_name}】{status_str}\n"
                    f"      当前价：{auction.current_price}\n"
                )
        
        if not claimable and not my_auctions and not my_bids:
            lines.append("暂无拍卖记录\n")
        
        lines.append("━━━━━━━━━━━━━━━\n")
        lines.append(f"💡 领取物品：{CMD_AUCTION_CLAIM} 拍卖ID")
        
        yield event.plain_result("".join(lines))
    
    @player_required
    async def handle_claim_auction(
        self,
        player: Player,
        event: AstrMessageEvent,
        auction_id: int = 0
    ):
        """领取拍卖物品"""
        if auction_id <= 0:
            yield event.plain_result(f"用法：{CMD_AUCTION_CLAIM} 拍卖ID")
            return
        
        auction = await self.auction_mgr.get_auction_by_id(auction_id)
        if not auction:
            yield event.plain_result("拍卖不存在")
            return
        
        # 判断领取类型
        if auction.status == AuctionStatus.CANCELLED and auction.seller_id == player.user_id:
            # 流拍取回
            success, msg, source_type = await self.auction_mgr.claim_unsold_item(player, auction_id)
        else:
            # 拍得/抢夺领取
            success, msg, source_type = await self.auction_mgr.claim_auction_item(player, auction_id)
        
        if not success:
            yield event.plain_result(f"❌ {msg}")
            return
        
        # 将物品存入背包
        if source_type == "pill" or self.storage_ring_mgr.is_pill(auction.item_name):
            pills = player.get_pills_inventory()
            pills[auction.item_name] = pills.get(auction.item_name, 0) + auction.item_count
            player.set_pills_inventory(pills)
            await self.db.update_player(player)
            location = "丹药背包"
        else:
            store_success, store_msg = await self.storage_ring_mgr.store_item(
                player, auction.item_name, auction.item_count
            )
            if not store_success:
                yield event.plain_result(f"❌ 领取失败：{store_msg}")
                return
            location = "储物戒"
        
        # 删除拍卖记录（或标记为已领取）
        await self.db.conn.execute(
            "DELETE FROM auction_items WHERE id = ?",
            (auction_id,)
        )
        await self.db.conn.commit()
        
        yield event.plain_result(
            f"✅ {msg}\n"
            f"已存入{location}"
        )
    
    @player_required
    async def handle_robbery_list(self, player: Player, event: AstrMessageEvent):
        """查看可抢夺的拍卖"""
        auctions = await self.auction_mgr.get_robbery_window_auctions()
        msg = self.auction_mgr.format_robbery_list(auctions)
        yield event.plain_result(msg)
    
    @player_required
    async def handle_robbery(
        self,
        player: Player,
        event: AstrMessageEvent,
        auction_id: int = 0
    ):
        """抢夺拍卖物品"""
        if auction_id <= 0:
            yield event.plain_result(
                f"⚔️ 抢夺拍卖帮助\n"
                f"━━━━━━━━━━━━━━━\n"
                f"用法：{CMD_AUCTION_ROBBERY} 拍卖ID\n"
                f"━━━━━━━━━━━━━━━\n"
                f"• 只能抢夺处于抢夺窗口的拍卖\n"
                f"• 需要与获得者进行决斗\n"
                f"• 抢夺成功后将被禁止使用拍卖行24小时\n"
                f"• 被抢者会获得灵石退款（扣除手续费）\n"
                f"• ⚠️ 抢夺战斗会扣除双方实际HP！"
            )
            return
        
        # 检查抢夺者HP是否足够
        if player.hp < player.max_hp * 0.3:
            yield event.plain_result(
                f"❌ 你的HP过低（{player.hp}/{player.max_hp}），无法发起抢夺！\n"
                f"请先恢复HP后再战"
            )
            return
        
        # 获取拍卖信息，检查被抢者HP
        auction = await self.auction_mgr.get_auction_by_id(auction_id)
        if auction and auction.highest_bidder_id:
            victim = await self.db.get_player_by_id(auction.highest_bidder_id)
            if victim and victim.hp < victim.max_hp * 0.3:
                yield event.plain_result(f"❌ 对方HP过低，无法进行抢夺战斗")
                return
        
        success, msg, battle_result = await self.auction_mgr.attempt_robbery(
            robber=player,
            auction_id=auction_id,
            battle_manager=self.battle_mgr,
            equipment_manager=self.equipment_mgr,
            skill_manager=self.skill_mgr
        )
        
        # 应用战斗伤害（与决斗一致）
        if battle_result:
            # 抢夺者HP扣除
            p1_final = battle_result.get("p1_final", {})
            if p1_final:
                await self._apply_duel_damage(
                    player.user_id,
                    p1_final.get("hp", 0),
                    p1_final.get("max_hp", 1)
                )
            
            # 被抢者HP扣除
            p2_final = battle_result.get("p2_final", {})
            if p2_final and auction and auction.highest_bidder_id:
                await self._apply_duel_damage(
                    auction.highest_bidder_id,
                    p2_final.get("hp", 0),
                    p2_final.get("max_hp", 1)
                )
        
        if success and battle_result:
            # 抢夺成功，将物品存入抢夺者背包
            # 重新获取最新的player数据（因为HP已更新）
            player = await self.db.get_player_by_id(player.user_id)
            auction = await self.auction_mgr.get_auction_by_id(auction_id)
            if auction and player:
                if auction.source_type == "pill" or self.storage_ring_mgr.is_pill(auction.item_name):
                    pills = player.get_pills_inventory()
                    pills[auction.item_name] = pills.get(auction.item_name, 0) + auction.item_count
                    player.set_pills_inventory(pills)
                    await self.db.update_player(player)
                else:
                    await self.storage_ring_mgr.store_item(
                        player, auction.item_name, auction.item_count, silent=True
                    )
            
            # 添加HP扣除提示
            msg += "\n\n⚠️ 决斗模式：双方HP已实际扣除"
        
        yield event.plain_result(msg)
    
    @player_required
    async def handle_auction_info(
        self,
        player: Player,
        event: AstrMessageEvent,
        auction_id: int = 0
    ):
        """查看拍卖详情"""
        if auction_id <= 0:
            yield event.plain_result(f"用法：{CMD_AUCTION_INFO} 拍卖ID")
            return
        
        auction = await self.auction_mgr.get_auction_by_id(auction_id)
        if not auction:
            yield event.plain_result("拍卖不存在")
            return
        
        import time
        now = int(time.time())
        
        # 计算剩余时间
        if auction.status == AuctionStatus.ACTIVE:
            remaining = auction.end_time - now
            if remaining <= 0:
                time_str = "即将结束"
            elif remaining < 3600:
                time_str = f"{remaining // 60}分钟"
            else:
                time_str = f"{remaining // 3600}小时{(remaining % 3600) // 60}分"
        elif auction.status == AuctionStatus.ROBBERY_WINDOW:
            remaining = auction.robbery_end_time - now
            time_str = f"抢夺窗口：{remaining // 60}分{remaining % 60}秒"
        else:
            time_str = self._get_status_str(auction)
        
        lines = [
            f"📦 拍卖详情 #{auction.id}\n",
            f"━━━━━━━━━━━━━━━\n",
            f"物品：【{auction.item_name}】x{auction.item_count}\n",
            f"卖家：{auction.seller_name}\n",
            f"━━━━━━━━━━━━━━━\n",
            f"起拍价：{auction.starting_price} 灵石\n",
            f"当前价：{auction.current_price} 灵石\n",
        ]
        
        if auction.buyout_price > 0:
            lines.append(f"一口价：{auction.buyout_price} 灵石\n")
        
        lines.append(f"出价次数：{auction.bid_count}\n")
        
        if auction.highest_bidder_name:
            lines.append(f"最高出价：{auction.highest_bidder_name}\n")
        
        lines.append(f"━━━━━━━━━━━━━━━\n")
        lines.append(f"状态：{time_str}\n")
        
        if auction.status == AuctionStatus.ACTIVE:
            lines.append(f"\n💡 竞拍：{CMD_AUCTION_BID} {auction.id} 金额")
        elif auction.status == AuctionStatus.ROBBERY_WINDOW:
            lines.append(f"\n⚔️ 抢夺：{CMD_AUCTION_ROBBERY} {auction.id}")
            lines.append(f"\n⚠️ 抢夺战斗会扣除双方实际HP！")
        
        yield event.plain_result("".join(lines))
    
    def _get_status_str(self, auction) -> str:
        """获取拍卖状态字符串"""
        if auction.status == AuctionStatus.ACTIVE:
            return "进行中"
        elif auction.status == AuctionStatus.ROBBERY_WINDOW:
            return "⚔️抢夺窗口"
        elif auction.status == AuctionStatus.COMPLETED:
            if auction.robber_id:
                return "已被抢夺"
            return "已成交"
        elif auction.status == AuctionStatus.CANCELLED:
            return "已流拍"
        else:
            return "未知"
