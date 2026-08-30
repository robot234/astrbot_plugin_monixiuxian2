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


class _AuctionAbort(RuntimeError):
    """Expected conflict that must abort the surrounding SQLite transaction."""


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

    def _storage_capacity(self, player: Player) -> int:
        rings = getattr(self.config_manager, "storage_rings_data", {}) or {}
        config = rings.get(player.storage_ring, {}) if isinstance(rings, dict) else {}
        try:
            return max(0, int(config.get("capacity", 20)))
        except (TypeError, ValueError):
            return 20

    @staticmethod
    def _inventory_column(source_type: str) -> str:
        if source_type == "pill":
            return "pills_inventory"
        if source_type == "storage":
            return "storage_ring_items"
        raise _AuctionAbort("不支持的物品来源")

    async def _fetch_auction_locked(self, auction_id: int) -> Optional[AuctionItem]:
        async with self.db.conn.execute(
            "SELECT * FROM auction_items WHERE id = ?", (auction_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return AuctionItem.from_dict(dict(row)) if row else None

    async def _read_inventory_locked(self, user_id: str, source_type: str):
        column = self._inventory_column(source_type)
        async with self.db.conn.execute(
            f"SELECT {column} FROM players WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
        if not row:
            raise _AuctionAbort("玩家不存在或已被删除")
        return column, row[0] if row[0] is not None else "{}"

    async def _mutate_inventory_locked(
        self,
        user_id: str,
        source_type: str,
        item_name: str,
        count: int,
        *,
        adding: bool,
    ) -> str:
        """CAS-update one inventory column while the task owns the transaction."""
        player = await self.db.get_player_by_id(user_id)
        if not player:
            raise _AuctionAbort("玩家不存在或已被删除")

        column, old_raw = await self._read_inventory_locked(user_id, source_type)
        try:
            inventory = json.loads(old_raw or "{}")
        except (TypeError, json.JSONDecodeError) as exc:
            raise _AuctionAbort("玩家物品数据损坏") from exc
        if not isinstance(inventory, dict):
            raise _AuctionAbort("玩家物品数据损坏")

        value = inventory.get(item_name, 0)
        nested = isinstance(value, dict)
        if nested:
            quantity = value.get("count")
        else:
            quantity = value
        if isinstance(quantity, bool) or not isinstance(quantity, int):
            raise _AuctionAbort("玩家物品数量无效")

        if adding:
            if source_type == "storage" and item_name not in inventory:
                if len(inventory) >= self._storage_capacity(player):
                    raise _AuctionAbort("储物戒空间不足")
            new_quantity = quantity + count
            if nested:
                updated = dict(value)
                updated["count"] = new_quantity
                inventory[item_name] = updated
            else:
                inventory[item_name] = new_quantity
        else:
            if item_name not in inventory or quantity < count:
                raise _AuctionAbort(f"物品【{item_name}】数量不足")
            if count == quantity:
                del inventory[item_name]
            elif nested:
                updated = dict(value)
                updated["count"] = quantity - count
                inventory[item_name] = updated
            else:
                inventory[item_name] = quantity - count

        new_raw = json.dumps(inventory, ensure_ascii=False)
        if old_raw is None:
            cursor = await self.db.conn.execute(
                f"UPDATE players SET {column} = ? WHERE user_id = ? AND {column} IS NULL",
                (new_raw, user_id),
                commit=False,
            )
        else:
            cursor = await self.db.conn.execute(
                f"UPDATE players SET {column} = ? WHERE user_id = ? AND {column} = ?",
                (new_raw, user_id, old_raw),
                commit=False,
            )
        if cursor.rowcount != 1:
            raise _AuctionAbort("玩家物品状态已变化，请重试")
        return new_raw

    async def _is_banned_locked(self, user_id: str) -> Tuple[bool, int]:
        async with self.db.conn.execute(
            "SELECT ban_until FROM auction_bans WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
        if not row:
            return False, 0
        ban_until = int(row[0])
        now = int(time.time())
        if now < ban_until:
            return True, ban_until - now
        cursor = await self.db.conn.execute(
            "DELETE FROM auction_bans WHERE user_id = ? AND ban_until = ?",
            (user_id, ban_until),
            commit=False,
        )
        if cursor.rowcount != 1:
            raise _AuctionAbort("封禁状态已变化，请重试")
        return False, 0

    async def _ban_player_locked(self, user_id: str, reason: str, duration: int) -> None:
        now = int(time.time())
        cursor = await self.db.conn.execute(
            """
            INSERT INTO auction_bans (user_id, ban_until, reason, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                ban_until = excluded.ban_until,
                reason = excluded.reason
            """,
            (user_id, now + duration, reason, now),
            commit=False,
        )
        if cursor.rowcount != 1:
            raise _AuctionAbort("拍卖行封禁状态更新失败")

    async def _delete_claimed_auction_locked(self, auction_id: int, where_sql: str, params: tuple) -> None:
        # auction_bids has no ON DELETE CASCADE, so remove children in the same
        # transaction before the conditional parent delete.
        await self.db.conn.execute(
            "DELETE FROM auction_bids WHERE auction_id = ?",
            (auction_id,),
            commit=False,
        )
        cursor = await self.db.conn.execute(
            f"DELETE FROM auction_items WHERE id = ? AND {where_sql}",
            (auction_id, *params),
            commit=False,
        )
        if cursor.rowcount != 1:
            raise _AuctionAbort("拍卖已被领取或状态已变化")
    
    async def ensure_auction_tables(self):
        """确保拍卖系统表存在"""
        async with self.db.transaction():
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
            """, commit=False)
            await self.db.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_auction_status ON auction_items(status)",
                commit=False,
            )
            await self.db.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_auction_seller ON auction_items(seller_id)",
                commit=False,
            )
            await self.db.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_auction_end_time ON auction_items(end_time)",
                commit=False,
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
            """, commit=False)
            await self.db.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_bid_auction ON auction_bids(auction_id)",
                commit=False,
            )

            # 拍卖行封禁表
            await self.db.conn.execute("""
                CREATE TABLE IF NOT EXISTS auction_bans (
                    user_id TEXT PRIMARY KEY,
                    ban_until INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                )
            """, commit=False)
    
    async def is_banned(self, user_id: str) -> Tuple[bool, int]:
        """检查玩家是否被禁止使用拍卖行
        
        Returns:
            (是否被禁, 剩余秒数)
        """
        await self.ensure_auction_tables()
        
        async with self.db.transaction():
            return await self._is_banned_locked(user_id)
    
    async def ban_player(self, user_id: str, reason: str, duration: int = None):
        """禁止玩家使用拍卖行"""
        if duration is None:
            duration = self.BAN_DURATION
        
        if isinstance(duration, bool) or not isinstance(duration, int) or duration <= 0:
            raise ValueError("duration must be a positive integer")
        await self.ensure_auction_tables()
        async with self.db.transaction():
            await self._ban_player_locked(user_id, reason, duration)
    
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
        if isinstance(item_count, bool) or not isinstance(item_count, int) or item_count <= 0:
            return False, "上架数量必须是大于0的整数", None
        if source_type not in {"storage", "pill", "auto"}:
            return False, "不支持的物品来源", None
        if isinstance(starting_price, bool) or not isinstance(starting_price, int) or starting_price <= 0:
            return False, "起拍价必须大于0", None
        if isinstance(buyout_price, bool) or not isinstance(buyout_price, int) or buyout_price < 0:
            return False, "一口价必须是非负整数", None
        if buyout_price > 0 and buyout_price <= starting_price:
            return False, "一口价必须高于起拍价", None
        if isinstance(duration_minutes, bool) or not isinstance(duration_minutes, int):
            return False, "拍卖时长必须是整数", None

        duration_seconds = duration_minutes * 60
        if duration_seconds < self.MIN_AUCTION_DURATION:
            return False, f"拍卖时长不能少于{self.MIN_AUCTION_DURATION // 60}分钟", None
        if duration_seconds > self.MAX_AUCTION_DURATION:
            return False, f"拍卖时长不能超过{self.MAX_AUCTION_DURATION // 3600}小时", None

        await self.ensure_auction_tables()
        try:
            async with self.db.transaction():
                is_banned, remaining = await self._is_banned_locked(player.user_id)
                if is_banned:
                    hours = remaining // 3600
                    minutes = (remaining % 3600) // 60
                    return False, f"你已被拍卖行禁止使用！剩余时间：{hours}小时{minutes}分钟", None

                current_player = await self.db.get_player_by_id(player.user_id)
                if not current_player:
                    return False, "玩家不存在或已被删除", None
                active_count = await self._get_player_active_auction_count(player.user_id)
                if active_count >= self.MAX_ACTIVE_AUCTIONS_PER_PLAYER:
                    return False, f"你已有{active_count}个物品在拍卖中，最多同时上架{self.MAX_ACTIVE_AUCTIONS_PER_PLAYER}个", None

                chosen_source = source_type
                if chosen_source == "auto":
                    _, storage_raw = await self._read_inventory_locked(player.user_id, "storage")
                    storage_items = json.loads(storage_raw or "{}")
                    storage_value = storage_items.get(item_name, 0) if isinstance(storage_items, dict) else 0
                    storage_count = storage_value.get("count", 0) if isinstance(storage_value, dict) else storage_value
                    chosen_source = "storage" if isinstance(storage_count, int) and not isinstance(storage_count, bool) and storage_count > 0 else "pill"

                new_inventory = await self._mutate_inventory_locked(
                    player.user_id, chosen_source, item_name, item_count, adding=False
                )
                now = int(time.time())
                end_time = now + duration_seconds
                seller_name = current_player.user_name or f"道友{player.user_id[:6]}"
                cursor = await self.db.conn.execute(
                    """
                    INSERT INTO auction_items (
                        item_name, item_count, source_type, seller_id, seller_name,
                        starting_price, current_price, buyout_price,
                        highest_bidder_id, highest_bidder_name, bid_count,
                        start_time, end_time, status, robbery_end_time, robber_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', '', 0, ?, ?, ?, 0, '')
                    """,
                    (
                        item_name, item_count, chosen_source, player.user_id, seller_name,
                        starting_price, starting_price, buyout_price,
                        now, end_time, AuctionStatus.ACTIVE,
                    ),
                    commit=False,
                )
                if cursor.rowcount != 1 or not cursor.lastrowid:
                    raise _AuctionAbort("拍卖记录创建失败")
                auction_id = cursor.lastrowid
                auction = AuctionItem(
                    id=auction_id,
                    item_name=item_name,
                    item_count=item_count,
                    source_type=chosen_source,
                    seller_id=player.user_id,
                    seller_name=seller_name,
                    starting_price=starting_price,
                    current_price=starting_price,
                    buyout_price=buyout_price,
                    start_time=now,
                    end_time=end_time,
                    status=AuctionStatus.ACTIVE,
                )
        except _AuctionAbort as exc:
            return False, str(exc), None

        if chosen_source == "pill":
            player.pills_inventory = new_inventory
        else:
            player.storage_ring_items = new_inventory
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
        if isinstance(item_count, bool) or not isinstance(item_count, int) or item_count <= 0:
            return False, "上架数量必须是大于0的整数", None
        if source_type not in {"storage", "pill"}:
            return False, "不支持的物品来源", None
        if isinstance(starting_price, bool) or not isinstance(starting_price, int) or starting_price <= 0:
            return False, "起拍价必须大于0", None
        if isinstance(buyout_price, bool) or not isinstance(buyout_price, int) or buyout_price < 0:
            return False, "一口价必须是非负整数", None
        if buyout_price > 0 and buyout_price <= starting_price:
            return False, "一口价必须高于起拍价", None
        if isinstance(duration_minutes, bool) or not isinstance(duration_minutes, int):
            return False, "拍卖时长必须是整数", None
        duration_seconds = duration_minutes * 60
        if duration_seconds < self.MIN_AUCTION_DURATION:
            return False, f"拍卖时长不能少于{self.MIN_AUCTION_DURATION // 60}分钟", None
        if duration_seconds > self.MAX_AUCTION_DURATION:
            return False, f"拍卖时长不能超过{self.MAX_AUCTION_DURATION // 3600}小时", None

        await self.ensure_auction_tables()
        async with self.db.transaction():
            now = int(time.time())
            end_time = now + duration_seconds
            cursor = await self.db.conn.execute(
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
                    now, end_time, AuctionStatus.ACTIVE,
                ),
                commit=False,
            )
            if cursor.rowcount != 1 or not cursor.lastrowid:
                raise _AuctionAbort("拍卖记录创建失败")
            auction_id = cursor.lastrowid
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
                status=AuctionStatus.ACTIVE,
            )

        logger.info(f"【拍卖系统】系统上架物品：{item_name} x{item_count}，起拍价：{starting_price}")
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
        if isinstance(bid_amount, bool) or not isinstance(bid_amount, int) or bid_amount <= 0:
            return False, "出价必须是大于0的整数"
        await self.ensure_auction_tables()
        try:
            async with self.db.transaction():
                is_banned, remaining = await self._is_banned_locked(player.user_id)
                if is_banned:
                    hours = remaining // 3600
                    minutes = (remaining % 3600) // 60
                    return False, f"你已被拍卖行禁止使用！剩余时间：{hours}小时{minutes}分钟"

                auction = await self._fetch_auction_locked(auction_id)
                if not auction:
                    return False, "拍卖不存在"
                now = int(time.time())
                if auction.status != AuctionStatus.ACTIVE or now >= auction.end_time:
                    return False, "该拍卖已结束"
                if auction.seller_id == player.user_id:
                    return False, "不能竞拍自己的物品"

                min_bid = int(auction.current_price * (1 + self.MIN_BID_INCREMENT))
                if auction.bid_count == 0:
                    min_bid = auction.starting_price
                if bid_amount < min_bid:
                    return False, f"出价必须至少为 {min_bid} 灵石（当前价格的110%）"

                is_buyout = auction.buyout_price > 0 and bid_amount >= auction.buyout_price
                effective_bid = auction.buyout_price if is_buyout else bid_amount
                bidder = await self.db.get_player_by_id(player.user_id)
                if not bidder:
                    return False, "玩家不存在或已被删除"
                previous_id = auction.highest_bidder_id or ""
                same_bidder = previous_id == player.user_id
                charge = effective_bid - auction.current_price if same_bidder else effective_bid
                if charge <= 0:
                    return False, "出价必须高于你当前的最高出价"
                if bidder.gold < charge:
                    return False, f"灵石不足！需要 {charge}，你只有 {bidder.gold}"

                previous = None
                if previous_id and not same_bidder:
                    previous = await self.db.get_player_by_id(previous_id)
                    if not previous:
                        return False, "上一位出价者不存在，暂时无法继续竞拍"

                if previous is not None:
                    refund_cursor = await self.db.conn.execute(
                        "UPDATE players SET gold = gold + ? WHERE user_id = ?",
                        (auction.current_price, previous_id),
                        commit=False,
                    )
                    if refund_cursor.rowcount != 1:
                        raise _AuctionAbort("上一位出价者状态已变化，请重试")

                charge_cursor = await self.db.conn.execute(
                    "UPDATE players SET gold = gold - ? WHERE user_id = ? AND gold >= ?",
                    (charge, player.user_id, charge),
                    commit=False,
                )
                if charge_cursor.rowcount != 1:
                    raise _AuctionAbort("灵石状态已变化，请重试")

                bidder_name = bidder.user_name or f"道友{player.user_id[:6]}"
                next_status = AuctionStatus.ROBBERY_WINDOW if is_buyout else AuctionStatus.ACTIVE
                next_robbery_end = now + self.ROBBERY_WINDOW if is_buyout else auction.robbery_end_time
                auction_cursor = await self.db.conn.execute(
                    """
                    UPDATE auction_items SET
                        current_price = ?,
                        highest_bidder_id = ?,
                        highest_bidder_name = ?,
                        bid_count = bid_count + 1,
                        status = ?,
                        robbery_end_time = ?
                    WHERE id = ? AND status = ? AND end_time > ?
                      AND current_price = ? AND bid_count = ?
                      AND COALESCE(highest_bidder_id, '') = ?
                    """,
                    (
                        effective_bid, player.user_id, bidder_name,
                        next_status, next_robbery_end,
                        auction_id, AuctionStatus.ACTIVE, now,
                        auction.current_price, auction.bid_count, previous_id,
                    ),
                    commit=False,
                )
                if auction_cursor.rowcount != 1:
                    raise _AuctionAbort("拍卖状态已变化，请重试")

                bid_cursor = await self.db.conn.execute(
                    """
                    INSERT INTO auction_bids (auction_id, bidder_id, bidder_name, bid_amount, bid_time)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (auction_id, player.user_id, bidder_name, effective_bid, now),
                    commit=False,
                )
                if bid_cursor.rowcount != 1:
                    raise _AuctionAbort("竞拍记录写入失败")
                new_gold = bidder.gold - charge
                item_name = auction.item_name
                item_count = auction.item_count
                if is_buyout:
                    message = (
                        f"🎉 一口价成交！\n"
                        f"【{item_name}】x{item_count}\n"
                        f"成交价：{effective_bid} 灵石\n"
                        f"⚠️ 注意：5分钟内可能被其他玩家抢夺！"
                    )
                else:
                    message = (
                        f"✅ 出价成功！\n"
                        f"【{item_name}】x{item_count}\n"
                        f"你的出价：{effective_bid} 灵石\n"
                        f"当前最高出价者：{bidder_name}"
                    )
        except _AuctionAbort as exc:
            return False, str(exc)

        player.gold = new_gold
        return True, message
    
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
        auction = await self.get_auction_by_id(auction_id)
        if not auction:
            return False, "拍卖不存在", None
        if auction.status != AuctionStatus.ROBBERY_WINDOW:
            if auction.status == AuctionStatus.ACTIVE:
                return False, "该拍卖尚未结束，无法抢夺", None
            return False, "该拍卖的抢夺窗口已关闭", None

        now = int(time.time())
        if now >= auction.robbery_end_time:
            return False, "抢夺窗口已关闭", None
        if auction.highest_bidder_id == robber.user_id:
            return False, "不能抢夺自己拍得的物品", None
        if auction.seller_id == robber.user_id:
            return False, "不能抢夺自己上架的物品", None

        victim = await self.db.get_player_by_id(auction.highest_bidder_id)
        if not victim:
            return False, "拍卖获得者不存在", None
        robber_stats = battle_manager.prepare_combat_stats(robber, equipment_manager, skill_manager)
        victim_stats = battle_manager.prepare_combat_stats(victim, equipment_manager, skill_manager)
        battle_result = battle_manager.execute_battle(robber_stats, victim_stats, battle_type="duel")

        robber_name = robber.user_name or f"道友{robber.user_id[:6]}"
        victim_name = victim.user_name or f"道友{victim.user_id[:6]}"
        if battle_result.get("winner") != robber.user_id:
            return False, (
                f"⚔️ 抢夺失败！\n"
                f"━━━━━━━━━━━━━━━\n"
                f"【{robber_name}】被【{victim_name}】击败\n"
                f"【{auction.item_name}】仍归【{victim_name}】所有\n"
                f"━━━━━━━━━━━━━━━"
            ), battle_result

        try:
            async with self.db.transaction():
                current = await self._fetch_auction_locked(auction_id)
                now = int(time.time())
                if (
                    not current
                    or current.status != AuctionStatus.ROBBERY_WINDOW
                    or current.robber_id
                    or current.highest_bidder_id != auction.highest_bidder_id
                    or now >= current.robbery_end_time
                ):
                    return False, "拍卖状态已变化，抢夺无效", battle_result
                current_victim = await self.db.get_player_by_id(current.highest_bidder_id)
                if not current_victim:
                    return False, "拍卖获得者不存在", battle_result
                state_cursor = await self.db.conn.execute(
                    """
                    UPDATE auction_items SET robber_id = ?, status = ?
                    WHERE id = ? AND status = ? AND robber_id = ''
                      AND highest_bidder_id = ? AND robbery_end_time > ?
                    """,
                    (
                        robber.user_id, AuctionStatus.COMPLETED, auction_id,
                        AuctionStatus.ROBBERY_WINDOW, current.highest_bidder_id, now,
                    ),
                    commit=False,
                )
                if state_cursor.rowcount != 1:
                    raise _AuctionAbort("拍卖状态已变化，抢夺无效")
                await self._ban_player_locked(
                    robber.user_id,
                    f"抢夺拍卖物品【{current.item_name}】",
                    self.BAN_DURATION,
                )
                refund = int(current.current_price * (1 - self.COMMISSION_RATE))
                refund_cursor = await self.db.conn.execute(
                    "UPDATE players SET gold = gold + ? WHERE user_id = ?",
                    (refund, current_victim.user_id),
                    commit=False,
                )
                if refund_cursor.rowcount != 1:
                    raise _AuctionAbort("被抢者状态已变化，抢夺已回滚")
                item_name = current.item_name
                item_count = current.item_count
        except _AuctionAbort as exc:
            return False, str(exc), battle_result

        msg = (
            f"⚔️ 抢夺成功！\n"
            f"━━━━━━━━━━━━━━━\n"
            f"【{robber_name}】击败了【{victim_name}】\n"
            f"抢得：【{item_name}】x{item_count}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"⚠️ 惩罚：你已被拍卖行禁止使用24小时！\n"
            f"💰 【{victim_name}】获得退款：{refund} 灵石"
        )
        return True, msg, battle_result
    
    async def _settle_one_locked(self, auction_id: int, now: int) -> Optional[dict]:
        auction = await self._fetch_auction_locked(auction_id)
        if not auction:
            return None
        if auction.status == AuctionStatus.ACTIVE:
            if auction.end_time > now:
                return None
            if auction.bid_count > 0:
                cursor = await self.db.conn.execute(
                    """
                    UPDATE auction_items SET status = ?, robbery_end_time = ?
                    WHERE id = ? AND status = ? AND end_time <= ? AND bid_count > 0
                    """,
                    (
                        AuctionStatus.ROBBERY_WINDOW, now + self.ROBBERY_WINDOW,
                        auction.id, AuctionStatus.ACTIVE, now,
                    ),
                    commit=False,
                )
                if cursor.rowcount != 1:
                    raise _AuctionAbort("拍卖状态已变化，请重试")
                return {
                    "auction_id": auction.id,
                    "item_name": auction.item_name,
                    "action": "robbery_window",
                    "winner_id": auction.highest_bidder_id,
                    "winner_name": auction.highest_bidder_name,
                    "price": auction.current_price,
                }

            cursor = await self.db.conn.execute(
                """
                UPDATE auction_items SET status = ?
                WHERE id = ? AND status = ? AND end_time <= ? AND bid_count = 0
                """,
                (AuctionStatus.CANCELLED, auction.id, AuctionStatus.ACTIVE, now),
                commit=False,
            )
            if cursor.rowcount != 1:
                raise _AuctionAbort("拍卖状态已变化，请重试")
            return {
                "auction_id": auction.id,
                "item_name": auction.item_name,
                "action": "cancelled",
                "seller_id": auction.seller_id,
            }

        if auction.status != AuctionStatus.ROBBERY_WINDOW or auction.robbery_end_time > now:
            return None
        cursor = await self.db.conn.execute(
            """
            UPDATE auction_items SET status = ?
            WHERE id = ? AND status = ? AND robbery_end_time <= ?
            """,
            (AuctionStatus.COMPLETED, auction.id, AuctionStatus.ROBBERY_WINDOW, now),
            commit=False,
        )
        if cursor.rowcount != 1:
            raise _AuctionAbort("拍卖状态已变化，请重试")

        if auction.seller_id != "system":
            seller = await self.db.get_player_by_id(auction.seller_id)
            if not seller:
                raise _AuctionAbort("卖家不存在，结算已回滚")
            earnings = int(auction.current_price * (1 - self.COMMISSION_RATE))
            seller_cursor = await self.db.conn.execute(
                "UPDATE players SET gold = gold + ? WHERE user_id = ?",
                (earnings, auction.seller_id),
                commit=False,
            )
            if seller_cursor.rowcount != 1:
                raise _AuctionAbort("卖家状态已变化，结算已回滚")
        return {
            "auction_id": auction.id,
            "item_name": auction.item_name,
            "action": "completed",
            "winner_id": auction.highest_bidder_id,
            "winner_name": auction.highest_bidder_name,
            "price": auction.current_price,
        }

    async def settle_auction(self, auction_id: int) -> Tuple[bool, str]:
        """Advance one auction through its time-based terminal transition."""
        await self.ensure_auction_tables()
        try:
            async with self.db.transaction():
                now = int(time.time())
                result = await self._settle_one_locked(auction_id, now)
                if result is None:
                    auction = await self._fetch_auction_locked(auction_id)
                    if not auction:
                        return False, "拍卖不存在"
                    return False, "拍卖尚未到结算时间或已结算"
        except _AuctionAbort as exc:
            return False, str(exc)
        if result["action"] == "robbery_window":
            return True, "拍卖已进入抢夺窗口"
        if result["action"] == "cancelled":
            return True, "拍卖已流拍，卖家可领取物品"
        return True, "拍卖已完成结算"

    async def settle(self, auction_id: int) -> Tuple[bool, str]:
        return await self.settle_auction(auction_id)

    async def process_ended_auctions(self) -> List[dict]:
        """Atomically process all auctions whose current phase has expired."""
        await self.ensure_auction_tables()
        results = []
        async with self.db.transaction():
            now = int(time.time())
            async with self.db.conn.execute(
                """
                SELECT id FROM auction_items
                WHERE (status = ? AND end_time <= ?)
                   OR (status = ? AND robbery_end_time <= ?)
                ORDER BY id
                """,
                (AuctionStatus.ACTIVE, now, AuctionStatus.ROBBERY_WINDOW, now),
            ) as cursor:
                rows = await cursor.fetchall()
            for row in rows:
                result = await self._settle_one_locked(row[0], now)
                if result is not None:
                    results.append(result)
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
        try:
            async with self.db.transaction():
                auction = await self._fetch_auction_locked(auction_id)
                if not auction:
                    return False, "拍卖不存在", None
                if auction.status != AuctionStatus.COMPLETED:
                    return False, "该拍卖尚未完成，暂时无法领取", None
                if auction.robber_id:
                    if auction.robber_id != player.user_id:
                        return False, "你没有权限领取该物品", None
                    condition = "status = ? AND robber_id = ?"
                    condition_params = (AuctionStatus.COMPLETED, player.user_id)
                elif auction.highest_bidder_id == player.user_id:
                    condition = "status = ? AND robber_id = '' AND highest_bidder_id = ?"
                    condition_params = (AuctionStatus.COMPLETED, player.user_id)
                else:
                    return False, "你没有权限领取该物品", None
                new_inventory = await self._mutate_inventory_locked(
                    player.user_id,
                    auction.source_type,
                    auction.item_name,
                    auction.item_count,
                    adding=True,
                )
                await self._delete_claimed_auction_locked(
                    auction.id, condition, condition_params
                )
                item_name = auction.item_name
                item_count = auction.item_count
                source_type = auction.source_type
        except _AuctionAbort as exc:
            return False, str(exc), None
        if source_type == "pill":
            player.pills_inventory = new_inventory
        else:
            player.storage_ring_items = new_inventory
        return True, f"成功领取【{item_name}】x{item_count}", source_type
    
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
        try:
            async with self.db.transaction():
                auction = await self._fetch_auction_locked(auction_id)
                if not auction:
                    return False, "拍卖不存在", None
                if auction.status != AuctionStatus.CANCELLED:
                    return False, "该拍卖未流拍", None
                if auction.seller_id != player.user_id:
                    return False, "你不是该物品的卖家", None
                new_inventory = await self._mutate_inventory_locked(
                    player.user_id,
                    auction.source_type,
                    auction.item_name,
                    auction.item_count,
                    adding=True,
                )
                await self._delete_claimed_auction_locked(
                    auction.id,
                    "status = ? AND seller_id = ?",
                    (AuctionStatus.CANCELLED, player.user_id),
                )
                item_name = auction.item_name
                item_count = auction.item_count
                source_type = auction.source_type
        except _AuctionAbort as exc:
            return False, str(exc), None
        if source_type == "pill":
            player.pills_inventory = new_inventory
        else:
            player.storage_ring_items = new_inventory
        return True, f"成功取回【{item_name}】x{item_count}", source_type

    async def claim_item(
        self, player: Player, auction_id: int
    ) -> Tuple[bool, str, Optional[str]]:
        """Claim any eligible terminal auction exactly once."""
        await self.ensure_auction_tables()
        try:
            async with self.db.transaction():
                auction = await self._fetch_auction_locked(auction_id)
                if not auction:
                    return False, "拍卖不存在", None
                if auction.status == AuctionStatus.CANCELLED:
                    if auction.seller_id != player.user_id:
                        return False, "你没有权限领取该物品", None
                    condition = "status = ? AND seller_id = ?"
                    condition_params = (AuctionStatus.CANCELLED, player.user_id)
                    verb = "取回"
                elif auction.status == AuctionStatus.COMPLETED:
                    if auction.robber_id:
                        if auction.robber_id != player.user_id:
                            return False, "你没有权限领取该物品", None
                        condition = "status = ? AND robber_id = ?"
                        condition_params = (AuctionStatus.COMPLETED, player.user_id)
                    elif auction.highest_bidder_id == player.user_id:
                        condition = "status = ? AND robber_id = '' AND highest_bidder_id = ?"
                        condition_params = (AuctionStatus.COMPLETED, player.user_id)
                    else:
                        return False, "你没有权限领取该物品", None
                    verb = "领取"
                else:
                    return False, "该拍卖尚未完成，暂时无法领取", None
                new_inventory = await self._mutate_inventory_locked(
                    player.user_id,
                    auction.source_type,
                    auction.item_name,
                    auction.item_count,
                    adding=True,
                )
                await self._delete_claimed_auction_locked(
                    auction.id, condition, condition_params
                )
                item_name = auction.item_name
                item_count = auction.item_count
                source_type = auction.source_type
        except _AuctionAbort as exc:
            return False, str(exc), None
        if source_type == "pill":
            player.pills_inventory = new_inventory
        else:
            player.storage_ring_items = new_inventory
        return True, f"成功{verb}【{item_name}】x{item_count}", source_type
    
    async def cancel_auction(
        self,
        player: Player,
        auction_id: int
    ) -> Tuple[bool, str]:
        """取消拍卖（仅限无人出价时）"""
        await self.ensure_auction_tables()
        try:
            async with self.db.transaction():
                auction = await self._fetch_auction_locked(auction_id)
                if not auction:
                    return False, "拍卖不存在"
                if auction.seller_id != player.user_id:
                    return False, "你不是该物品的卖家"
                if auction.status != AuctionStatus.ACTIVE:
                    return False, "该拍卖已结束，无法取消"
                if auction.bid_count > 0:
                    return False, "已有人出价，无法取消拍卖"
                new_inventory = await self._mutate_inventory_locked(
                    player.user_id,
                    auction.source_type,
                    auction.item_name,
                    auction.item_count,
                    adding=True,
                )
                cursor = await self.db.conn.execute(
                    """
                    UPDATE auction_items SET status = ?
                    WHERE id = ? AND seller_id = ? AND status = ? AND bid_count = 0
                    """,
                    (
                        AuctionStatus.CANCELLED, auction_id, player.user_id,
                        AuctionStatus.ACTIVE,
                    ),
                    commit=False,
                )
                if cursor.rowcount != 1:
                    raise _AuctionAbort("拍卖状态已变化，请重试")
                item_name = auction.item_name
                item_count = auction.item_count
                source_type = auction.source_type
        except _AuctionAbort as exc:
            return False, str(exc)
        if source_type == "pill":
            player.pills_inventory = new_inventory
        else:
            player.storage_ring_items = new_inventory
        return True, f"已取消拍卖【{item_name}】x{item_count}，物品已返还"
    
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
