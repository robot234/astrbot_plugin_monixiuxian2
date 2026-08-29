# managers/auction_manager.py
"""
拍卖系统管理器
- 玩家寄卖物品
- 系统随机上架物品
- 竞拍机制
- 抢夺机制（拍卖结束后5分钟内可决斗抢夺）
- 惩罚机制（抢夺者被禁止使用拍卖行）
"""

import time
import random
import json
from typing import Optional, Tuple, List, Dict, Any
from dataclasses import dataclass, field, asdict
from enum import IntEnum

from astrbot.api import logger

from ..data import DataBase
from ..config_manager import ConfigManager
from ..models import Player


class AuctionStatus(IntEnum):
    """拍卖状态"""
    ACTIVE = 1          # 进行中
    ENDED = 2           # 已结束（等待领取）
    COMPLETED = 3       # 已完成（物品已领取）
    CANCELLED = 4       # 已取消
    ROBBERY_WINDOW = 5  # 抢夺窗口期（结束后5分钟内）


@dataclass
class AuctionItem:
    """拍卖物品"""
    id: int = 0
    item_name: str = ""
    item_count: int = 1
    source_type: str = "storage"  # storage=储物戒, pill=丹药背包, system=系统
    seller_id: str = ""           # 卖家ID，system表示系统上架
    seller_name: str = ""
    starting_price: int = 0       # 起拍价
    current_price: int = 0        # 当前价格
    buyout_price: int = 0         # 一口价（0表示无一口价）
    highest_bidder_id: str = ""   # 最高出价者ID
    highest_bidder_name: str = ""
    bid_count: int = 0            # 出价次数
    start_time: int = 0           # 开始时间
    end_time: int = 0             # 结束时间
    status: int = AuctionStatus.ACTIVE
    robbery_end_time: int = 0     # 抢夺窗口结束时间
    robber_id: str = ""           # 抢夺者ID（如果被抢）
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> "AuctionItem":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class AuctionManager:
    """拍卖系统管理器"""
    
    # 配置常量
    MIN_AUCTION_DURATION = 30 * 60      # 最短拍卖时间：30分钟
    MAX_AUCTION_DURATION = 24 * 60 * 60 # 最长拍卖时间：24小时
    DEFAULT_AUCTION_DURATION = 2 * 60 * 60  # 默认拍卖时间：2小时
    ROBBERY_WINDOW = 5 * 60             # 抢夺窗口：5分钟
    BAN_DURATION = 24 * 60 * 60         # 抢夺惩罚：禁止使用拍卖行24小时
    COMMISSION_RATE = 0.05              # 手续费：5%
    MIN_BID_INCREMENT = 0.1             # 最低加价幅度：10%
    MAX_ACTIVE_AUCTIONS_PER_PLAYER = 5  # 每个玩家最多同时上架5个物品
    
    # 系统上架配置
    SYSTEM_AUCTION_INTERVAL = 60 * 60   # 系统每小时上架一次
    SYSTEM_ITEMS_PER_BATCH = 3          # 每次上架3个物品
    
    def __init__(self, db: DataBase, config_manager: ConfigManager):
        self.db = db
        self.config_manager = config_manager
    
    async def ensure_auction_tables(self):
        """确保拍卖系统表存在"""
        # 拍卖物品表
        await self.db.conn.execute("""
            CREATE TABLE IF NOT EXISTS auction_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_name TEXT NOT NULL,
                item_count INTEGER NOT NULL DEFAULT 1,
                source_type TEXT NOT NULL DEFAULT 'storage',
                seller_id TEXT NOT NULL,
                seller_name TEXT NOT NULL,
                starting_price INTEGER NOT NULL,
                current_price INTEGER NOT NULL,
                buyout_price INTEGER NOT NULL DEFAULT 0,
                highest_bidder_id TEXT DEFAULT '',
                highest_bidder_name TEXT DEFAULT '',
                bid_count INTEGER NOT NULL DEFAULT 0,
                start_time INTEGER NOT NULL,
                end_time INTEGER NOT NULL,
                status INTEGER NOT NULL DEFAULT 1,
                robbery_end_time INTEGER NOT NULL DEFAULT 0,
                robber_id TEXT DEFAULT ''
            )
        """)
        await self.db.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_auction_status ON auction_items(status)"
        )
        await self.db.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_auction_seller ON auction_items(seller_id)"
        )
        await self.db.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_auction_end_time ON auction_items(end_time)"
        )
        
        # 竞拍记录表
        await self.db.conn.execute("""
            CREATE TABLE IF NOT EXISTS auction_bids (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                auction_id INTEGER NOT NULL,
                bidder_id TEXT NOT NULL,
                bidder_name TEXT NOT NULL,
                bid_amount INTEGER NOT NULL,
                bid_time INTEGER NOT NULL,
                FOREIGN KEY (auction_id) REFERENCES auction_items(id)
            )
        """)
        await self.db.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_bid_auction ON auction_bids(auction_id)"
        )
        
        # 拍卖行封禁表
        await self.db.conn.execute("""
            CREATE TABLE IF NOT EXISTS auction_bans (
                user_id TEXT PRIMARY KEY,
                ban_until INTEGER NOT NULL,
                reason TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
        """)
        
        await self.db.conn.commit()
    
    async def is_banned(self, user_id: str) -> Tuple[bool, int]:
        """检查玩家是否被禁止使用拍卖行
        
        Returns:
            (是否被禁, 剩余秒数)
        """
        await self.ensure_auction_tables()
        
        async with self.db.conn.execute(
            "SELECT ban_until FROM auction_bans WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                ban_until = row[0]
                now = int(time.time())
                if now < ban_until:
                    return True, ban_until - now
                else:
                    # 已过期，删除记录
                    await self.db.conn.execute(
                        "DELETE FROM auction_bans WHERE user_id = ?",
                        (user_id,)
                    )
                    await self.db.conn.commit()
        return False, 0
    
    async def ban_player(self, user_id: str, reason: str, duration: int = None):
        """禁止玩家使用拍卖行"""
        if duration is None:
            duration = self.BAN_DURATION
        
        now = int(time.time())
        ban_until = now + duration
        
        await self.db.conn.execute(
            """
            INSERT INTO auction_bans (user_id, ban_until, reason, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET 
                ban_until = excluded.ban_until,
                reason = excluded.reason
            """,
            (user_id, ban_until, reason, now)
        )
        await self.db.conn.commit()
    
    async def create_auction(
        self,
        player: Player,
        item_name: str,
        item_count: int,
        source_type: str,
        starting_price: int,
        buyout_price: int = 0,
        duration_minutes: int = 120
    ) -> Tuple[bool, str, Optional[AuctionItem]]:
        """创建拍卖
        
        Args:
            player: 卖家
            item_name: 物品名称
            item_count: 物品数量
            source_type: 来源类型 (storage/pill)
            starting_price: 起拍价
            buyout_price: 一口价（0表示无）
            duration_minutes: 拍卖时长（分钟）
            
        Returns:
            (成功, 消息, 拍卖物品)
        """
        await self.ensure_auction_tables()
        
        # 检查是否被禁
        is_banned, remaining = await self.is_banned(player.user_id)
        if is_banned:
            hours = remaining // 3600
            minutes = (remaining % 3600) // 60
            return False, f"你已被拍卖行禁止使用！剩余时间：{hours}小时{minutes}分钟", None
        
        # 检查上架数量限制
        active_count = await self._get_player_active_auction_count(player.user_id)
        if active_count >= self.MAX_ACTIVE_AUCTIONS_PER_PLAYER:
            return False, f"你已有{active_count}个物品在拍卖中，最多同时上架{self.MAX_ACTIVE_AUCTIONS_PER_PLAYER}个", None
        
        # 验证价格
        if starting_price <= 0:
            return False, "起拍价必须大于0", None
        
        if buyout_price > 0 and buyout_price <= starting_price:
            return False, "一口价必须高于起拍价", None
        
        # 验证时长
        duration_seconds = duration_minutes * 60
        if duration_seconds < self.MIN_AUCTION_DURATION:
            return False, f"拍卖时长不能少于{self.MIN_AUCTION_DURATION // 60}分钟", None
        if duration_seconds > self.MAX_AUCTION_DURATION:
            return False, f"拍卖时长不能超过{self.MAX_AUCTION_DURATION // 3600}小时", None
        
        now = int(time.time())
        end_time = now + duration_seconds
        
        # 创建拍卖记录
        seller_name = player.user_name if player.user_name else f"道友{player.user_id[:6]}"
        
        await self.db.conn.execute(
            """
            INSERT INTO auction_items (
                item_name, item_count, source_type, seller_id, seller_name,
                starting_price, current_price, buyout_price,
                highest_bidder_id, highest_bidder_name, bid_count,
                start_time, end_time, status, robbery_end_time, robber_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', '', 0, ?, ?, ?, 0, '')
            """,
            (
                item_name, item_count, source_type, player.user_id, seller_name,
                starting_price, starting_price, buyout_price,
                now, end_time, AuctionStatus.ACTIVE
            )
        )
        await self.db.conn.commit()
        
        # 获取新创建的拍卖ID
        async with self.db.conn.execute("SELECT last_insert_rowid()") as cursor:
            row = await cursor.fetchone()
            auction_id = row[0] if row else 0
        
        auction = AuctionItem(
            id=auction_id,
            item_name=item_name,
            item_count=item_count,
            source_type=source_type,
            seller_id=player.user_id,
            seller_name=seller_name,
            starting_price=starting_price,
            current_price=starting_price,
            buyout_price=buyout_price,
            start_time=now,
            end_time=end_time,
            status=AuctionStatus.ACTIVE
        )
        
        return True, f"成功上架【{item_name}】x{item_count}，拍卖ID：{auction_id}", auction
    
    async def create_system_auction(
        self,
        item_name: str,
        item_count: int,
        source_type: str,
        starting_price: int,
        buyout_price: int = 0,
        duration_minutes: int = 120
    ) -> Tuple[bool, str, Optional[AuctionItem]]:
        """系统创建拍卖"""
        await self.ensure_auction_tables()
        
        now = int(time.time())
        duration_seconds = duration_minutes * 60
        end_time = now + duration_seconds
        
        await self.db.conn.execute(
            """
            INSERT INTO auction_items (
                item_name, item_count, source_type, seller_id, seller_name,
                starting_price, current_price, buyout_price,
                highest_bidder_id, highest_bidder_name, bid_count,
                start_time, end_time, status, robbery_end_time, robber_id
            ) VALUES (?, ?, ?, 'system', '拍卖行', ?, ?, ?, '', '', 0, ?, ?, ?, 0, '')
            """,
            (
                item_name, item_count, source_type,
                starting_price, starting_price, buyout_price,
                now, end_time, AuctionStatus.ACTIVE
            )
        )
        await self.db.conn.commit()
        
        async with self.db.conn.execute("SELECT last_insert_rowid()") as cursor:
            row = await cursor.fetchone()
            auction_id = row[0] if row else 0
        
        logger.info(f"【拍卖系统】系统上架物品：{item_name} x{item_count}，起拍价：{starting_price}")
        
        # 返回创建的拍卖对象
        auction = AuctionItem(
            id=auction_id,
            item_name=item_name,
            item_count=item_count,
            source_type=source_type,
            seller_id="system",
            seller_name="拍卖行",
            starting_price=starting_price,
            current_price=starting_price,
            buyout_price=buyout_price,
            start_time=now,
            end_time=end_time,
            status=AuctionStatus.ACTIVE
        )
        
        return True, f"系统上架【{item_name}】x{item_count}", auction
    
    async def place_bid(
        self,
        player: Player,
        auction_id: int,
        bid_amount: int
    ) -> Tuple[bool, str]:
        """出价竞拍
        
        Args:
            player: 竞拍者
            auction_id: 拍卖ID
            bid_amount: 出价金额
            
        Returns:
            (成功, 消息)
        """
        await self.ensure_auction_tables()
        
        # 检查是否被禁
        is_banned, remaining = await self.is_banned(player.user_id)
        if is_banned:
            hours = remaining // 3600
            minutes = (remaining % 3600) // 60
            return False, f"你已被拍卖行禁止使用！剩余时间：{hours}小时{minutes}分钟"
        
        # 获取拍卖信息
        auction = await self.get_auction_by_id(auction_id)
        if not auction:
            return False, "拍卖不存在"
        
        if auction.status != AuctionStatus.ACTIVE:
            return False, "该拍卖已结束"
        
        now = int(time.time())
        if now >= auction.end_time:
            return False, "该拍卖已结束"
        
        # 不能竞拍自己的物品
        if auction.seller_id == player.user_id:
            return False, "不能竞拍自己的物品"
        
        # 检查出价是否足够
        min_bid = int(auction.current_price * (1 + self.MIN_BID_INCREMENT))
        if auction.bid_count == 0:
            min_bid = auction.starting_price
        
        if bid_amount < min_bid:
            return False, f"出价必须至少为 {min_bid} 灵石（当前价格的110%）"
        
        # 检查玩家灵石
        if player.gold < bid_amount:
            return False, f"灵石不足！需要 {bid_amount}，你只有 {player.gold}"
        
        # 检查是否为一口价
        is_buyout = auction.buyout_price > 0 and bid_amount >= auction.buyout_price
        if is_buyout:
            bid_amount = auction.buyout_price
        
        # 退还上一个最高出价者的灵石
        if auction.highest_bidder_id and auction.highest_bidder_id != player.user_id:
            prev_bidder = await self.db.get_player_by_id(auction.highest_bidder_id)
            if prev_bidder:
                prev_bidder.gold += auction.current_price
                await self.db.update_player(prev_bidder)
        
        # 扣除当前竞拍者的灵石
        player.gold -= bid_amount
        await self.db.update_player(player)
        
        # 更新拍卖信息
        bidder_name = player.user_name if player.user_name else f"道友{player.user_id[:6]}"
        
        if is_buyout:
            # 一口价直接结束拍卖
            await self.db.conn.execute(
                """
                UPDATE auction_items SET
                    current_price = ?,
                    highest_bidder_id = ?,
                    highest_bidder_name = ?,
                    bid_count = bid_count + 1,
                    status = ?,
                    robbery_end_time = ?
                WHERE id = ?
                """,
                (
                    bid_amount, player.user_id, bidder_name,
                    AuctionStatus.ROBBERY_WINDOW, now + self.ROBBERY_WINDOW,
                    auction_id
                )
            )
        else:
            await self.db.conn.execute(
                """
                UPDATE auction_items SET
                    current_price = ?,
                    highest_bidder_id = ?,
                    highest_bidder_name = ?,
                    bid_count = bid_count + 1
                WHERE id = ?
                """,
                (bid_amount, player.user_id, bidder_name, auction_id)
            )
        
        # 记录竞拍历史
        await self.db.conn.execute(
            """
            INSERT INTO auction_bids (auction_id, bidder_id, bidder_name, bid_amount, bid_time)
            VALUES (?, ?, ?, ?, ?)
            """,
            (auction_id, player.user_id, bidder_name, bid_amount, now)
        )
        
        await self.db.conn.commit()
        
        if is_buyout:
            return True, (
                f"🎉 一口价成交！\n"
                f"【{auction.item_name}】x{auction.item_count}\n"
                f"成交价：{bid_amount} 灵石\n"
                f"⚠️ 注意：5分钟内可能被其他玩家抢夺！"
            )
        else:
            return True, (
                f"✅ 出价成功！\n"
                f"【{auction.item_name}】x{auction.item_count}\n"
                f"你的出价：{bid_amount} 灵石\n"
                f"当前最高出价者：{bidder_name}"
            )
    
    async def attempt_robbery(
        self,
        robber: Player,
        auction_id: int,
        battle_manager,
        equipment_manager,
        skill_manager
    ) -> Tuple[bool, str, Optional[dict]]:
        """尝试抢夺拍卖物品
        
        Args:
            robber: 抢夺者
            auction_id: 拍卖ID
            battle_manager: 战斗管理器
            equipment_manager: 装备管理器
            skill_manager: 技能管理器
            
        Returns:
            (成功, 消息, 战斗结果)
        """
        await self.ensure_auction_tables()
        
        # 获取拍卖信息
        auction = await self.get_auction_by_id(auction_id)
        if not auction:
            return False, "拍卖不存在", None
        
        if auction.status != AuctionStatus.ROBBERY_WINDOW:
            if auction.status == AuctionStatus.ACTIVE:
                return False, "该拍卖尚未结束，无法抢夺", None
            else:
                return False, "该拍卖的抢夺窗口已关闭", None
        
        now = int(time.time())
        if now >= auction.robbery_end_time:
            return False, "抢夺窗口已关闭", None
        
        # 不能抢夺自己的物品
        if auction.highest_bidder_id == robber.user_id:
            return False, "不能抢夺自己拍得的物品", None
        
        if auction.seller_id == robber.user_id:
            return False, "不能抢夺自己上架的物品", None
        
        # 获取被抢夺者
        victim = await self.db.get_player_by_id(auction.highest_bidder_id)
        if not victim:
            return False, "拍卖获得者不存在", None
        
        # 准备战斗
        robber_stats = battle_manager.prepare_combat_stats(robber, equipment_manager, skill_manager)
        victim_stats = battle_manager.prepare_combat_stats(victim, equipment_manager, skill_manager)
        
        # 执行战斗
        battle_result = battle_manager.execute_battle(robber_stats, victim_stats, battle_type="duel")
        
        robber_name = robber.user_name if robber.user_name else f"道友{robber.user_id[:6]}"
        victim_name = victim.user_name if victim.user_name else f"道友{victim.user_id[:6]}"
        
        if battle_result.get("winner") == robber.user_id:
            # 抢夺成功
            await self.db.conn.execute(
                """
                UPDATE auction_items SET
                    robber_id = ?,
                    status = ?
                WHERE id = ?
                """,
                (robber.user_id, AuctionStatus.COMPLETED, auction_id)
            )
            await self.db.conn.commit()
            
            # 禁止抢夺者使用拍卖行
            await self.ban_player(
                robber.user_id,
                f"抢夺拍卖物品【{auction.item_name}】",
                self.BAN_DURATION
            )
            
            # 退还被抢者的灵石（扣除手续费）
            refund = int(auction.current_price * (1 - self.COMMISSION_RATE))
            victim.gold += refund
            await self.db.update_player(victim)
            
            msg = (
                f"⚔️ 抢夺成功！\n"
                f"━━━━━━━━━━━━━━━\n"
                f"【{robber_name}】击败了【{victim_name}】\n"
                f"抢得：【{auction.item_name}】x{auction.item_count}\n"
                f"━━━━━━━━━━━━━━━\n"
                f"⚠️ 惩罚：你已被拍卖行禁止使用24小时！\n"
                f"💰 【{victim_name}】获得退款：{refund} 灵石"
            )
            
            return True, msg, battle_result
        else:
            # 抢夺失败
            msg = (
                f"⚔️ 抢夺失败！\n"
                f"━━━━━━━━━━━━━━━\n"
                f"【{robber_name}】被【{victim_name}】击败\n"
                f"【{auction.item_name}】仍归【{victim_name}】所有\n"
                f"━━━━━━━━━━━━━━━"
            )
            
            return False, msg, battle_result
    
    async def process_ended_auctions(self) -> List[dict]:
        """处理已结束的拍卖（定时任务调用）
        
        Returns:
            处理结果列表
        """
        await self.ensure_auction_tables()
        
        now = int(time.time())
        results = []
        
        # 查找已结束但未处理的拍卖
        async with self.db.conn.execute(
            """
            SELECT * FROM auction_items 
            WHERE status = ? AND end_time <= ?
            """,
            (AuctionStatus.ACTIVE, now)
        ) as cursor:
            rows = await cursor.fetchall()
        
        for row in rows:
            auction = AuctionItem.from_dict(dict(row))
            
            if auction.bid_count > 0:
                # 有人出价，进入抢夺窗口
                await self.db.conn.execute(
                    """
                    UPDATE auction_items SET
                        status = ?,
                        robbery_end_time = ?
                    WHERE id = ?
                    """,
                    (AuctionStatus.ROBBERY_WINDOW, now + self.ROBBERY_WINDOW, auction.id)
                )
                results.append({
                    "auction_id": auction.id,
                    "item_name": auction.item_name,
                    "action": "robbery_window",
                    "winner_id": auction.highest_bidder_id,
                    "winner_name": auction.highest_bidder_name,
                    "price": auction.current_price
                })
            else:
                # 无人出价，流拍
                await self.db.conn.execute(
                    """
                    UPDATE auction_items SET status = ? WHERE id = ?
                    """,
                    (AuctionStatus.CANCELLED, auction.id)
                )
                results.append({
                    "auction_id": auction.id,
                    "item_name": auction.item_name,
                    "action": "cancelled",
                    "seller_id": auction.seller_id
                })
        
        # 处理抢夺窗口已过期的拍卖
        async with self.db.conn.execute(
            """
            SELECT * FROM auction_items 
            WHERE status = ? AND robbery_end_time <= ?
            """,
            (AuctionStatus.ROBBERY_WINDOW, now)
        ) as cursor:
            rows = await cursor.fetchall()
        
        for row in rows:
            auction = AuctionItem.from_dict(dict(row))
            
            # 抢夺窗口结束，正式完成交易
            await self.db.conn.execute(
                """
                UPDATE auction_items SET status = ? WHERE id = ?
                """,
                (AuctionStatus.COMPLETED, auction.id)
            )
            
            # 给卖家结算灵石（扣除手续费）
            if auction.seller_id != "system":
                seller = await self.db.get_player_by_id(auction.seller_id)
                if seller:
                    earnings = int(auction.current_price * (1 - self.COMMISSION_RATE))
                    seller.gold += earnings
                    await self.db.update_player(seller)
            
            results.append({
                "auction_id": auction.id,
                "item_name": auction.item_name,
                "action": "completed",
                "winner_id": auction.highest_bidder_id,
                "winner_name": auction.highest_bidder_name,
                "price": auction.current_price
            })
        
        await self.db.conn.commit()
        return results
    
    async def claim_auction_item(
        self,
        player: Player,
        auction_id: int
    ) -> Tuple[bool, str, Optional[str]]:
        """领取拍卖获得的物品
        
        Returns:
            (成功, 消息, 物品来源类型)
        """
        await self.ensure_auction_tables()
        
        auction = await self.get_auction_by_id(auction_id)
        if not auction:
            return False, "拍卖不存在", None
        
        # 检查是否是获胜者
        is_winner = (
            auction.status == AuctionStatus.COMPLETED and
            auction.highest_bidder_id == player.user_id and
            not auction.robber_id
        )
        
        # 检查是否是抢夺者
        is_robber = (
            auction.status == AuctionStatus.COMPLETED and
            auction.robber_id == player.user_id
        )
        
        if not is_winner and not is_robber:
            return False, "你没有权限领取该物品", None
        
        # 标记为已领取（通过删除记录或添加标记）
        # 这里我们保留记录用于历史查询
        
        return True, f"成功领取【{auction.item_name}】x{auction.item_count}", auction.source_type
    
    async def claim_unsold_item(
        self,
        player: Player,
        auction_id: int
    ) -> Tuple[bool, str, Optional[str]]:
        """领取流拍的物品
        
        Returns:
            (成功, 消息, 物品来源类型)
        """
        await self.ensure_auction_tables()
        
        auction = await self.get_auction_by_id(auction_id)
        if not auction:
            return False, "拍卖不存在", None
        
        if auction.status != AuctionStatus.CANCELLED:
            return False, "该拍卖未流拍", None
        
        if auction.seller_id != player.user_id:
            return False, "你不是该物品的卖家", None
        
        return True, f"成功取回【{auction.item_name}】x{auction.item_count}", auction.source_type
    
    async def cancel_auction(
        self,
        player: Player,
        auction_id: int
    ) -> Tuple[bool, str]:
        """取消拍卖（仅限无人出价时）"""
        await self.ensure_auction_tables()
        
        auction = await self.get_auction_by_id(auction_id)
        if not auction:
            return False, "拍卖不存在"
        
        if auction.seller_id != player.user_id:
            return False, "你不是该物品的卖家"
        
        if auction.status != AuctionStatus.ACTIVE:
            return False, "该拍卖已结束，无法取消"
        
        if auction.bid_count > 0:
            return False, "已有人出价，无法取消拍卖"
        
        await self.db.conn.execute(
            "UPDATE auction_items SET status = ? WHERE id = ?",
            (AuctionStatus.CANCELLED, auction_id)
        )
        await self.db.conn.commit()
        
        return True, f"已取消拍卖【{auction.item_name}】x{auction.item_count}"
    
    async def get_auction_by_id(self, auction_id: int) -> Optional[AuctionItem]:
        """根据ID获取拍卖信息"""
        await self.ensure_auction_tables()
        
        async with self.db.conn.execute(
            "SELECT * FROM auction_items WHERE id = ?",
            (auction_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return AuctionItem.from_dict(dict(row))
        return None
    
    async def get_active_auctions(self, limit: int = 20, offset: int = 0) -> List[AuctionItem]:
        """获取进行中的拍卖列表"""
        await self.ensure_auction_tables()
        
        now = int(time.time())
        auctions = []
        
        async with self.db.conn.execute(
            """
            SELECT * FROM auction_items 
            WHERE status = ? AND end_time > ?
            ORDER BY end_time ASC
            LIMIT ? OFFSET ?
            """,
            (AuctionStatus.ACTIVE, now, limit, offset)
        ) as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                auctions.append(AuctionItem.from_dict(dict(row)))
        
        return auctions
    
    async def get_robbery_window_auctions(self) -> List[AuctionItem]:
        """获取处于抢夺窗口的拍卖"""
        await self.ensure_auction_tables()
        
        now = int(time.time())
        auctions = []
        
        async with self.db.conn.execute(
            """
            SELECT * FROM auction_items 
            WHERE status = ? AND robbery_end_time > ?
            ORDER BY robbery_end_time ASC
            """,
            (AuctionStatus.ROBBERY_WINDOW, now)
        ) as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                auctions.append(AuctionItem.from_dict(dict(row)))
        
        return auctions
    
    async def get_player_auctions(self, user_id: str) -> List[AuctionItem]:
        """获取玩家的拍卖（包括上架和竞拍）"""
        await self.ensure_auction_tables()
        
        auctions = []
        
        # 玩家上架的
        async with self.db.conn.execute(
            """
            SELECT * FROM auction_items 
            WHERE seller_id = ?
            ORDER BY start_time DESC
            LIMIT 20
            """,
            (user_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                auctions.append(AuctionItem.from_dict(dict(row)))
        
        return auctions
    
    async def get_player_bids(self, user_id: str) -> List[AuctionItem]:
        """获取玩家参与竞拍的拍卖"""
        await self.ensure_auction_tables()
        
        auctions = []
        
        async with self.db.conn.execute(
            """
            SELECT DISTINCT a.* FROM auction_items a
            INNER JOIN auction_bids b ON a.id = b.auction_id
            WHERE b.bidder_id = ?
            ORDER BY a.end_time DESC
            LIMIT 20
            """,
            (user_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                auctions.append(AuctionItem.from_dict(dict(row)))
        
        return auctions
    
    async def get_claimable_items(self, user_id: str) -> List[AuctionItem]:
        """获取玩家可领取的物品"""
        await self.ensure_auction_tables()
        
        items = []
        
        # 获胜的拍卖
        async with self.db.conn.execute(
            """
            SELECT * FROM auction_items 
            WHERE status = ? AND highest_bidder_id = ? AND robber_id = ''
            """,
            (AuctionStatus.COMPLETED, user_id)
        ) as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                items.append(AuctionItem.from_dict(dict(row)))
        
        # 抢夺成功的
        async with self.db.conn.execute(
            """
            SELECT * FROM auction_items 
            WHERE status = ? AND robber_id = ?
            """,
            (AuctionStatus.COMPLETED, user_id)
        ) as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                items.append(AuctionItem.from_dict(dict(row)))
        
        # 流拍需要取回的
        async with self.db.conn.execute(
            """
            SELECT * FROM auction_items 
            WHERE status = ? AND seller_id = ?
            """,
            (AuctionStatus.CANCELLED, user_id)
        ) as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                items.append(AuctionItem.from_dict(dict(row)))
        
        return items
    
    async def _get_player_active_auction_count(self, user_id: str) -> int:
        """获取玩家当前进行中的拍卖数量"""
        async with self.db.conn.execute(
            """
            SELECT COUNT(*) FROM auction_items 
            WHERE seller_id = ? AND status = ?
            """,
            (user_id, AuctionStatus.ACTIVE)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0
    
    async def spawn_system_auctions(self) -> List[AuctionItem]:
        """系统随机上架物品"""
        await self.ensure_auction_tables()
        
        spawned = []
        
        # 从各种配置中随机选择物品
        all_items = []
        
        # 武器
        for name, config in self.config_manager.weapons_data.items():
            if config.get("price", 0) > 0:
                all_items.append({
                    "name": name,
                    "type": "storage",
                    "price": config.get("price", 100),
                    "rank": config.get("rank", "凡品")
                })
        
        # 防具
        for name, config in self.config_manager.items_data.items():
            if config.get("price", 0) <= 0:
                continue
            if config.get("type") != "法器":
                continue
            if config.get("subtype") not in {"防具", "饰品"}:
                continue
            all_items.append({
                    "name": name,
                    "type": "storage",
                    "price": config.get("price", 100),
                    "rank": config.get("rank", "凡品")
                })
        
        # 丹药
        for name, config in self.config_manager.pills_data.items():
            if config.get("price", 0) > 0:
                all_items.append({
                    "name": name,
                    "type": "pill",
                    "price": config.get("price", 100),
                    "rank": config.get("rank", "凡品")
                })
        
        for name, config in self.config_manager.exp_pills_data.items():
            if config.get("price", 0) > 0:
                all_items.append({
                    "name": name,
                    "type": "pill",
                    "price": config.get("price", 100),
                    "rank": config.get("rank", "凡品")
                })
        
        for name, config in self.config_manager.utility_pills_data.items():
            if config.get("price", 0) > 0:
                all_items.append({
                    "name": name,
                    "type": "pill",
                    "price": config.get("price", 100),
                    "rank": config.get("rank", "凡品")
                })
        
        # 功法
        for name, config in self.config_manager.techniques_data.items():
            if config.get("price", 0) > 0:
                all_items.append({
                    "name": name,
                    "type": "storage",
                    "price": config.get("price", 100),
                    "rank": config.get("rank", "凡品")
                })
        
        if not all_items:
            return spawned
        
        # 随机选择物品上架
        items_to_spawn = random.sample(
            all_items,
            min(self.SYSTEM_ITEMS_PER_BATCH, len(all_items))
        )
        
        for item in items_to_spawn:
            # 起拍价为原价的50%-80%
            starting_price = int(item["price"] * random.uniform(0.5, 0.8))
            # 一口价为原价的100%-150%
            buyout_price = int(item["price"] * random.uniform(1.0, 1.5))
            # 随机数量（大部分为1）
            count = 1 if random.random() > 0.2 else random.randint(2, 5)
            # 随机时长（1-4小时）
            duration = random.randint(60, 240)
            
            success, msg, auction = await self.create_system_auction(
                item_name=item["name"],
                item_count=count,
                source_type=item["type"],
                starting_price=starting_price,
                buyout_price=buyout_price,
                duration_minutes=duration
            )
            
            if success and auction:
                spawned.append(auction)
        
        return spawned
    
    def format_auction_list(self, auctions: List[AuctionItem]) -> str:
        """格式化拍卖列表显示"""
        if not auctions:
            return "当前没有进行中的拍卖"
        
        lines = ["📦 拍卖行 - 当前拍卖\n", "━━━━━━━━━━━━━━━\n"]
        
        now = int(time.time())
        
        for auction in auctions:
            remaining = auction.end_time - now
            if remaining <= 0:
                time_str = "即将结束"
            elif remaining < 3600:
                time_str = f"{remaining // 60}分钟"
            else:
                time_str = f"{remaining // 3600}小时{(remaining % 3600) // 60}分"
            
            status_icon = "🔥" if auction.bid_count > 5 else "📦"
            
            lines.append(
                f"{status_icon} [{auction.id}] 【{auction.item_name}】x{auction.item_count}\n"
                f"   💰 当前价：{auction.current_price} | "
            )
            
            if auction.buyout_price > 0:
                lines.append(f"一口价：{auction.buyout_price}\n")
            else:
                lines.append("\n")
            
            lines.append(
                f"   👤 卖家：{auction.seller_name} | ⏱️ 剩余：{time_str}\n"
                f"   📊 出价次数：{auction.bid_count}"
            )
            
            if auction.highest_bidder_name:
                lines.append(f" | 最高：{auction.highest_bidder_name}\n")
            else:
                lines.append("\n")
            
            lines.append("\n")
        
        lines.append("━━━━━━━━━━━━━━━\n")
        lines.append("💡 竞拍：竞拍 拍卖ID 金额\n")
        lines.append("💡 上架：上架拍卖 物品名 起拍价 [一口价] [时长]")
        
        return "".join(lines)
    
    def format_robbery_list(self, auctions: List[AuctionItem]) -> str:
        """格式化可抢夺列表"""
        if not auctions:
            return "当前没有可抢夺的拍卖"
        
        lines = ["⚔️ 可抢夺的拍卖\n", "━━━━━━━━━━━━━━━\n"]
        
        now = int(time.time())
        
        for auction in auctions:
            remaining = auction.robbery_end_time - now
            if remaining <= 0:
                time_str = "即将关闭"
            else:
                time_str = f"{remaining // 60}分{remaining % 60}秒"
            
            lines.append(
                f"⚔️ [{auction.id}] 【{auction.item_name}】x{auction.item_count}\n"
                f"   💰 成交价：{auction.current_price}\n"
                f"   👤 获得者：{auction.highest_bidder_name}\n"
                f"   ⏱️ 抢夺窗口：{time_str}\n\n"
            )
        
        lines.append("━━━━━━━━━━━━━━━\n")
        lines.append("⚠️ 抢夺成功后将被禁止使用拍卖行24小时！\n")
        lines.append("💡 抢夺：抢夺拍卖 拍卖ID")
        
        return "".join(lines)
