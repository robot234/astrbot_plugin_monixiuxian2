import asyncio
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if "astrbot.api" not in sys.modules:
    logger = types.SimpleNamespace(
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
        debug=lambda *args, **kwargs: None,
    )
    api = types.ModuleType("astrbot.api")
    api.logger = logger
    api.AstrBotConfig = dict
    astrbot = types.ModuleType("astrbot")
    astrbot.api = api
    sys.modules["astrbot"] = astrbot
    sys.modules["astrbot.api"] = api

PACKAGE = "_monixiuxian2_test_package"
if PACKAGE not in sys.modules:
    package = types.ModuleType(PACKAGE)
    package.__path__ = [str(ROOT)]
    sys.modules[PACKAGE] = package

from _monixiuxian2_test_package.data.data_manager import DataBase
from _monixiuxian2_test_package.data.migration import _create_all_tables_v2
from _monixiuxian2_test_package.managers.auction_manager import AuctionManager, AuctionStatus
from _monixiuxian2_test_package.models import Player


class AuctionConfig:
    storage_rings_data = {"基础储物戒": {"capacity": 2}}


async def create_db():
    db = DataBase(":memory:")
    await db.connect()
    async with db.transaction():
        await _create_all_tables_v2(db.conn)
    return db


def make_player(user_id, *, gold=0, items=None, pills=None):
    player = Player(user_id=user_id, user_name=user_id, gold=gold)
    player.set_storage_ring_items(items or {})
    player.set_pills_inventory(pills or {})
    return player


async def set_auction(db, auction_id, **values):
    assignments = ", ".join(f"{column} = ?" for column in values)
    params = tuple(values.values()) + (auction_id,)
    async with db.transaction():
        cursor = await db.conn.execute(
            f"UPDATE auction_items SET {assignments} WHERE id = ?",
            params,
            commit=False,
        )
        if cursor.rowcount != 1:
            raise AssertionError("auction fixture update failed")


async def scalar(db, sql, params=()):
    async with db.conn.execute(sql, params) as cursor:
        row = await cursor.fetchone()
    return row[0] if row else None


class FakeCursor:
    def __init__(self, rowcount=0, lastrowid=None):
        self.rowcount = rowcount
        self.lastrowid = lastrowid


class FakeResult:
    """Small awaitable/context-manager stand-in for ManagedResult."""

    def __init__(self, cursor):
        self.cursor = cursor

    def __await__(self):
        async def resolve():
            return self.cursor

        return resolve().__await__()

    async def __aenter__(self):
        return self.cursor

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return None


class WinningBattle:
    def prepare_combat_stats(self, player, equipment_manager=None, skill_manager=None):
        return types.SimpleNamespace(user_id=player.user_id)

    def execute_battle(self, first, second, battle_type="duel"):
        return {"winner": first.user_id, "p1_final": {}, "p2_final": {}}


class AuctionAtomicityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = await create_db()
        self.manager = AuctionManager(self.db, AuctionConfig())
        await self.manager.ensure_auction_tables()

    async def asyncTearDown(self):
        await self.db.close()

    async def add_player(self, player):
        await self.db.create_player(player)

    async def create_storage_auction(self, seller, *, price=100, count=1):
        ok, msg, auction = await self.manager.create_auction(
            seller, "铁矿", count, "storage", price, 0, 120
        )
        self.assertTrue(ok, msg)
        return auction

    async def test_create_cancel_and_unsold_claim_are_once_only(self):
        seller = make_player("seller", items={"铁矿": 3})
        await self.add_player(seller)
        auction = await self.create_storage_auction(seller)
        current = await self.db.get_player_by_id("seller")
        self.assertEqual(current.get_storage_ring_items(), {"铁矿": 2})

        ok, msg = await self.manager.cancel_auction(seller, auction.id)
        self.assertTrue(ok, msg)
        current = await self.db.get_player_by_id("seller")
        self.assertEqual(current.get_storage_ring_items(), {"铁矿": 3})
        ok, _ = await self.manager.cancel_auction(seller, auction.id)
        self.assertFalse(ok)

        ok, msg, source = await self.manager.claim_item(seller, auction.id)
        self.assertTrue(ok, msg)
        self.assertEqual(source, "storage")
        self.assertEqual(await scalar(self.db, "SELECT COUNT(*) FROM auction_items"), 0)
        current = await self.db.get_player_by_id("seller")
        self.assertEqual(current.get_storage_ring_items(), {"铁矿": 4})
        ok, _, _ = await self.manager.claim_item(seller, auction.id)
        self.assertFalse(ok)
        self.assertEqual(current.get_storage_ring_items(), {"铁矿": 4})

    async def test_same_bidder_topup_ten_times_only_charges_difference(self):
        seller = make_player("seller", items={"铁矿": 1})
        bidder = make_player("bidder", gold=100_000)
        await self.add_player(seller)
        await self.add_player(bidder)
        auction = await self.create_storage_auction(seller)

        price = 100
        last_bid = None
        for _ in range(10):
            ok, msg = await self.manager.place_bid(bidder, auction.id, price)
            self.assertTrue(ok, msg)
            last_bid = price
            next_price = int(price * 1.1)
            price = max(price + 1, next_price)

        current = await self.db.get_player_by_id("bidder")
        self.assertEqual(current.gold, 100_000 - last_bid)
        self.assertEqual(await scalar(self.db, "SELECT current_price FROM auction_items WHERE id = ?", (auction.id,)), last_bid)
        self.assertEqual(await scalar(self.db, "SELECT bid_count FROM auction_items WHERE id = ?", (auction.id,)), 10)
        self.assertEqual(await scalar(self.db, "SELECT COUNT(*) FROM auction_bids WHERE auction_id = ?", (auction.id,)), 10)

    async def test_insufficient_and_expired_bid_preserve_assets(self):
        seller = make_player("seller", items={"铁矿": 1})
        poor = make_player("poor", gold=99)
        await self.add_player(seller)
        await self.add_player(poor)
        auction = await self.create_storage_auction(seller)
        ok, _ = await self.manager.place_bid(poor, auction.id, 100)
        self.assertFalse(ok)
        self.assertEqual((await self.db.get_player_by_id("poor")).gold, 99)
        self.assertEqual(await scalar(self.db, "SELECT bid_count FROM auction_items WHERE id = ?", (auction.id,)), 0)

        await set_auction(self.db, auction.id, end_time=0)
        ok, _ = await self.manager.place_bid(poor, auction.id, 100)
        self.assertFalse(ok)
        self.assertEqual((await self.db.get_player_by_id("poor")).gold, 99)

    async def test_new_bid_refunds_previous_bidder_and_preserves_escrow(self):
        seller = make_player("seller", items={"铁矿": 1})
        first = make_player("first", gold=1_000)
        second = make_player("second", gold=1_000)
        await self.add_player(seller)
        await self.add_player(first)
        await self.add_player(second)
        auction = await self.create_storage_auction(seller)
        ok, msg = await self.manager.place_bid(first, auction.id, 100)
        self.assertTrue(ok, msg)
        ok, msg = await self.manager.place_bid(second, auction.id, 120)
        self.assertTrue(ok, msg)
        self.assertEqual((await self.db.get_player_by_id("first")).gold, 1_000)
        self.assertEqual((await self.db.get_player_by_id("second")).gold, 880)
        self.assertEqual(await scalar(self.db, "SELECT current_price FROM auction_items WHERE id = ?", (auction.id,)), 120)

    async def test_settle_settle_pays_seller_once(self):
        seller = make_player("seller", items={"铁矿": 1})
        bidder = make_player("bidder", gold=1_000)
        await self.add_player(seller)
        await self.add_player(bidder)
        auction = await self.create_storage_auction(seller)
        ok, msg = await self.manager.place_bid(bidder, auction.id, 100)
        self.assertTrue(ok, msg)
        await set_auction(self.db, auction.id, end_time=0)
        ok, msg = await self.manager.settle_auction(auction.id)
        self.assertTrue(ok, msg)
        await set_auction(self.db, auction.id, robbery_end_time=0)
        results = await asyncio.gather(
            self.manager.settle_auction(auction.id),
            self.manager.settle_auction(auction.id),
        )
        self.assertEqual(sum(success for success, _ in results), 1)
        self.assertEqual((await self.db.get_player_by_id("seller")).gold, 95)
        self.assertEqual(
            await scalar(self.db, "SELECT status FROM auction_items WHERE id = ?", (auction.id,)),
            AuctionStatus.COMPLETED,
        )

    async def test_bid_settle_competition_has_one_legal_outcome(self):
        seller = make_player("seller", items={"铁矿": 1})
        bidder = make_player("bidder", gold=500)
        await self.add_player(seller)
        await self.add_player(bidder)
        auction = await self.create_storage_auction(seller)
        await set_auction(self.db, auction.id, end_time=0)
        bid_result, settle_result = await asyncio.gather(
            self.manager.place_bid(bidder, auction.id, 100),
            self.manager.settle_auction(auction.id),
        )
        status = await scalar(self.db, "SELECT status FROM auction_items WHERE id = ?", (auction.id,))
        self.assertIn(status, (AuctionStatus.CANCELLED, AuctionStatus.ROBBERY_WINDOW))
        if bid_result[0]:
            self.assertEqual(status, AuctionStatus.ROBBERY_WINDOW)
            self.assertEqual((await self.db.get_player_by_id("bidder")).gold, 400)
        else:
            self.assertEqual(status, AuctionStatus.CANCELLED)
            self.assertEqual((await self.db.get_player_by_id("bidder")).gold, 500)
        self.assertIn(settle_result[0], (True, False))

    async def test_claim_race_and_inventory_full_keep_assets_consistent(self):
        seller = make_player("seller", items={"铁矿": 2})
        winner = make_player("winner", gold=1_000)
        await self.add_player(seller)
        await self.add_player(winner)
        auction = await self.create_storage_auction(seller)
        await self.manager.place_bid(winner, auction.id, 100)
        await set_auction(self.db, auction.id, status=AuctionStatus.COMPLETED)
        results = await asyncio.gather(
            self.manager.claim_item(winner, auction.id),
            self.manager.claim_item(winner, auction.id),
        )
        self.assertEqual(sum(success for success, _, _ in results), 1)
        self.assertEqual((await self.db.get_player_by_id("winner")).get_storage_ring_items(), {"铁矿": 1})
        self.assertEqual(await scalar(self.db, "SELECT COUNT(*) FROM auction_items"), 0)

        full = make_player("full", items={"占位": 1})
        await self.add_player(full)
        blocked = await self.create_storage_auction(seller)
        await self.manager.place_bid(winner, blocked.id, 100)
        await set_auction(self.db, blocked.id, status=AuctionStatus.COMPLETED)
        self.manager.config_manager.storage_rings_data["基础储物戒"]["capacity"] = 1
        ok, _, _ = await self.manager.claim_item(full, blocked.id)
        self.assertFalse(ok)
        self.assertIsNotNone(await self.manager.get_auction_by_id(blocked.id))
        self.assertEqual((await self.db.get_player_by_id("full")).get_storage_ring_items(), {"占位": 1})

    async def test_claim_delete_rowcount_fault_rolls_back_inventory(self):
        seller = make_player("seller", items={"铁矿": 1})
        winner = make_player("winner", gold=1_000)
        await self.add_player(seller)
        await self.add_player(winner)
        auction = await self.create_storage_auction(seller)
        await self.manager.place_bid(winner, auction.id, 100)
        await set_auction(self.db, auction.id, status=AuctionStatus.COMPLETED)

        original_execute = self.db.conn.execute

        def fail_delete(sql, parameters=None, *, commit=True):
            if sql.lstrip().upper().startswith("DELETE FROM AUCTION_ITEMS"):
                return FakeResult(FakeCursor(rowcount=0))
            return original_execute(sql, parameters, commit=commit)

        self.db.conn.execute = fail_delete
        try:
            ok, _, _ = await self.manager.claim_item(winner, auction.id)
        finally:
            self.db.conn.execute = original_execute
        self.assertFalse(ok)
        self.assertEqual((await self.db.get_player_by_id("winner")).get_storage_ring_items(), {})
        self.assertIsNotNone(await self.manager.get_auction_by_id(auction.id))

    async def test_robbery_race_refunds_once_then_claims_once(self):
        seller = make_player("seller", items={"铁矿": 1})
        winner = make_player("winner", gold=1_000)
        robber_a = make_player("robber_a")
        robber_b = make_player("robber_b")
        for value in (seller, winner, robber_a, robber_b):
            await self.add_player(value)
        auction = await self.create_storage_auction(seller)
        await self.manager.place_bid(winner, auction.id, 100)
        await set_auction(
            self.db,
            auction.id,
            status=AuctionStatus.ROBBERY_WINDOW,
            robbery_end_time=int(time.time()) + 600,
        )
        battle = WinningBattle()
        results = await asyncio.gather(
            self.manager.attempt_robbery(robber_a, auction.id, battle, None, None),
            self.manager.attempt_robbery(robber_b, auction.id, battle, None, None),
        )
        self.assertEqual(sum(success for success, _, _ in results), 1)
        current = await self.manager.get_auction_by_id(auction.id)
        self.assertEqual(current.status, AuctionStatus.COMPLETED)
        robber_id = current.robber_id
        self.assertIn(robber_id, {"robber_a", "robber_b"})
        self.assertEqual((await self.db.get_player_by_id("winner")).gold, 995)
        self.assertEqual(await scalar(self.db, "SELECT COUNT(*) FROM auction_bans"), 1)

        claimant = robber_a if robber_id == "robber_a" else robber_b
        ok, msg, _ = await self.manager.claim_item(claimant, auction.id)
        self.assertTrue(ok, msg)
        ok, _, _ = await self.manager.claim_item(claimant, auction.id)
        self.assertFalse(ok)
        self.assertEqual((await self.db.get_player_by_id(robber_id)).get_storage_ring_items(), {"铁矿": 1})

    async def test_bid_cas_fault_rolls_back_charge(self):
        seller = make_player("seller", items={"铁矿": 1})
        bidder = make_player("bidder", gold=500)
        await self.add_player(seller)
        await self.add_player(bidder)
        auction = await self.create_storage_auction(seller)
        original_execute = self.db.conn.execute

        def fail_auction_update(sql, parameters=None, *, commit=True):
            if sql.lstrip().upper().startswith("UPDATE AUCTION_ITEMS SET"):
                return FakeResult(FakeCursor(rowcount=0))
            return original_execute(sql, parameters, commit=commit)

        self.db.conn.execute = fail_auction_update
        try:
            ok, _ = await self.manager.place_bid(bidder, auction.id, 100)
        finally:
            self.db.conn.execute = original_execute
        self.assertFalse(ok)
        self.assertEqual((await self.db.get_player_by_id("bidder")).gold, 500)
        self.assertEqual(await scalar(self.db, "SELECT bid_count FROM auction_items WHERE id = ?", (auction.id,)), 0)


if __name__ == "__main__":
    unittest.main()
