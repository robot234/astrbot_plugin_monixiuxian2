import asyncio
import json
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CaptureLogger:
    def __init__(self):
        self.errors = []

    def info(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None

    def debug(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        self.errors.append(" ".join(str(arg) for arg in args))


LOGGER = CaptureLogger()


def install_astrbot_stubs():
    """Provide only the AstrBot surface needed to import the real modules."""
    astrbot = sys.modules.setdefault("astrbot", types.ModuleType("astrbot"))
    api = sys.modules.setdefault("astrbot.api", types.ModuleType("astrbot.api"))
    api.logger = LOGGER
    api.AstrBotConfig = dict
    astrbot.api = api

    event = sys.modules.setdefault(
        "astrbot.api.event", types.ModuleType("astrbot.api.event")
    )

    class AstrMessageEvent:
        pass

    class Filter:
        def command(self, *args, **kwargs):
            return lambda func: func

    event.AstrMessageEvent = AstrMessageEvent
    event.filter = Filter()

    all_module = sys.modules.setdefault(
        "astrbot.api.all", types.ModuleType("astrbot.api.all")
    )

    class At:
        def __init__(self, qq=None, target=None, uin=None):
            self.qq = qq
            self.target = target
            self.uin = uin

    class Plain:
        def __init__(self, text=""):
            self.text = text

    all_module.At = At
    all_module.Plain = Plain

    star = sys.modules.setdefault(
        "astrbot.api.star", types.ModuleType("astrbot.api.star")
    )

    class Context:
        pass

    class Star:
        def __init__(self, context=None):
            self.context = context

    class StarTools:
        @staticmethod
        def get_data_dir(name):
            return Path(tempfile.gettempdir()) / name

    star.Context = Context
    star.Star = Star
    star.StarTools = StarTools


install_astrbot_stubs()

PACKAGE = "_monixiuxian2_a2b_test_package"
if PACKAGE not in sys.modules:
    package = types.ModuleType(PACKAGE)
    package.__path__ = [str(ROOT)]
    sys.modules[PACKAGE] = package

from _monixiuxian2_a2b_test_package.data.data_manager import DataBase
from _monixiuxian2_a2b_test_package.data.migration import _create_all_tables_v2
from _monixiuxian2_a2b_test_package.handlers.storage_ring_handler import (
    StorageRingHandler,
)
from _monixiuxian2_a2b_test_package.managers.dual_cultivation_manager import (
    DUAL_CULT_COOLDOWN,
    DUAL_CULT_INTIMACY_GAIN,
    DualCultivationManager,
)
from _monixiuxian2_a2b_test_package.models import Player
from _monixiuxian2_a2b_test_package.main import XiuXianPlugin


class TestConfig:
    items_data = {}
    storage_rings_data = {"基础储物戒": {"capacity": 20}}


def make_player(
    user_id,
    *,
    experience=0,
    gold=0,
    storage=None,
    pills=None,
    partner_id="",
    intimacy=0,
):
    player = Player(
        user_id=user_id,
        user_name=user_id,
        experience=experience,
        gold=gold,
        partner_id=partner_id,
        partner_intimacy=intimacy,
    )
    player.set_storage_ring_items(storage or {})
    player.set_pills_inventory(pills or {})
    return player


async def new_db():
    db = DataBase(":memory:")
    await db.connect()
    async with db.transaction():
        await _create_all_tables_v2(db.conn)
    return db


async def scalar(db, sql, params=()):
    async with db.conn.execute(sql, params) as cursor:
        row = await cursor.fetchone()
    return row[0] if row else None


async def player_from_db(db, user_id):
    value = await db.get_player_by_id(user_id)
    assert value is not None
    return value


async def pending_count(db, receiver_id=None):
    if receiver_id is None:
        return await scalar(db, "SELECT COUNT(*) FROM pending_gifts")
    return await scalar(
        db,
        "SELECT COUNT(*) FROM pending_gifts WHERE receiver_id = ?",
        (receiver_id,),
    )


class GiftLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = await new_db()
        self.config = TestConfig()
        self.handler = StorageRingHandler(self.db, self.config)
        await self.db.ext.ensure_pending_gifts_table()

    async def asyncTearDown(self):
        await self.db.close()

    async def add_players(self, *players):
        for value in players:
            await self.db.create_player(value)

    async def create_storage_gift(self, count=2, *, sender_items=None):
        sender = make_player(
            "sender", storage=sender_items or {"herb": count + 3}
        )
        receiver = make_player("receiver")
        await self.add_players(sender, receiver)
        result = await self.handler.create_gift(sender, "receiver", "herb", count)
        self.assertTrue(result[0], result[1])
        gift = await self.db.ext.get_pending_gift("receiver")
        self.assertIsNotNone(gift)
        return sender, receiver, gift

    async def test_create_failure_rolls_back_escrow_and_pending_row(self):
        sender = make_player("sender", storage={"herb": 5})
        receiver = make_player("receiver")
        await self.add_players(sender, receiver)

        original = self.db.ext.create_pending_gift

        async def fail_create(*args, **kwargs):
            raise RuntimeError("injected pending-gift failure")

        self.db.ext.create_pending_gift = fail_create
        try:
            with self.assertRaises(RuntimeError):
                await self.handler.create_gift(sender, "receiver", "herb", 2)
        finally:
            self.db.ext.create_pending_gift = original

        persisted = await player_from_db(self.db, "sender")
        self.assertEqual(persisted.get_storage_ring_items(), {"herb": 5})
        self.assertEqual(await pending_count(self.db), 0)
        self.assertIsNone(self.db.gate.owner)
        self.assertEqual(self.db.gate.depth, 0)

    async def test_accept_race_delivers_once(self):
        await self.create_storage_gift()

        results = await asyncio.gather(
            *(self.handler.accept_gift(make_player("receiver")) for _ in range(10))
        )
        self.assertEqual(sum(int(result[0]) for result in results), 1)
        persisted_sender = await player_from_db(self.db, "sender")
        persisted_receiver = await player_from_db(self.db, "receiver")
        self.assertEqual(persisted_sender.get_storage_ring_items(), {"herb": 3})
        self.assertEqual(persisted_receiver.get_storage_ring_items(), {"herb": 2})
        self.assertEqual(await pending_count(self.db), 0)

    async def test_reject_race_refunds_once(self):
        await self.create_storage_gift()

        results = await asyncio.gather(
            *(self.handler.reject_gift(make_player("receiver")) for _ in range(10))
        )
        self.assertEqual(sum(int(result[0]) for result in results), 1)
        persisted_sender = await player_from_db(self.db, "sender")
        persisted_receiver = await player_from_db(self.db, "receiver")
        self.assertEqual(persisted_sender.get_storage_ring_items(), {"herb": 5})
        self.assertEqual(persisted_receiver.get_storage_ring_items(), {})
        self.assertEqual(await pending_count(self.db), 0)

    async def test_accept_reject_race_preserves_item_conservation(self):
        await self.create_storage_gift()

        calls = []
        for index in range(10):
            receiver = make_player("receiver")
            if index % 2:
                calls.append(self.handler.reject_gift(receiver))
            else:
                calls.append(self.handler.accept_gift(receiver))
        results = await asyncio.gather(*calls)
        self.assertEqual(sum(int(result[0]) for result in results), 1)
        sender = await player_from_db(self.db, "sender")
        receiver = await player_from_db(self.db, "receiver")
        total = sender.get_storage_ring_items().get("herb", 0) + receiver.get_storage_ring_items().get("herb", 0)
        self.assertEqual(total, 5)
        self.assertEqual(await pending_count(self.db), 0)

    async def test_inventory_full_accept_rolls_back_and_keeps_escrow(self):
        self.config.storage_rings_data["基础储物戒"]["capacity"] = 1
        sender = make_player("sender", storage={"herb": 2})
        receiver = make_player("receiver", storage={"existing": 1})
        await self.add_players(sender, receiver)
        created = await self.handler.create_gift(sender, "receiver", "herb", 1)
        self.assertTrue(created[0], created[1])

        result = await self.handler.accept_gift(make_player("receiver"))
        self.assertFalse(result[0])
        self.assertIn("满", result[1])
        persisted_sender = await player_from_db(self.db, "sender")
        persisted_receiver = await player_from_db(self.db, "receiver")
        self.assertEqual(persisted_sender.get_storage_ring_items(), {"herb": 1})
        self.assertEqual(persisted_receiver.get_storage_ring_items(), {"existing": 1})
        self.assertEqual(await pending_count(self.db), 1)

        cancelled = await self.handler.cancel_gift(make_player("sender"))
        self.assertTrue(cancelled[0], cancelled[1])
        self.assertEqual(
            (await player_from_db(self.db, "sender")).get_storage_ring_items(),
            {"herb": 2},
        )

    async def test_expired_accept_refunds_once(self):
        _, _, gift = await self.create_storage_gift()
        async with self.db.transaction():
            await self.db.conn.execute(
                "UPDATE pending_gifts SET expires_at = ? WHERE id = ?",
                (int(time.time()) - 1, gift["id"]),
                commit=False,
            )

        first = await self.handler.accept_gift(make_player("receiver"))
        self.assertFalse(first[0])
        self.assertIn("过期", first[1])
        self.assertEqual(await pending_count(self.db), 0)
        self.assertEqual(
            (await player_from_db(self.db, "sender")).get_storage_ring_items(),
            {"herb": 5},
        )
        second = await self.handler.expire_gift(gift["id"])
        self.assertFalse(second[0])

    async def test_cancel_gift_refunds_and_is_idempotent(self):
        _, _, gift = await self.create_storage_gift()
        first = await self.handler.cancel_gift(make_player("sender"), gift["id"])
        self.assertTrue(first[0], first[1])
        self.assertEqual(await pending_count(self.db), 0)
        self.assertEqual(
            (await player_from_db(self.db, "sender")).get_storage_ring_items(),
            {"herb": 5},
        )
        second = await self.handler.cancel_gift(make_player("sender"), gift["id"])
        self.assertFalse(second[0])


class DualLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = await new_db()
        self.manager = DualCultivationManager(self.db)
        await self.manager.ensure_partner_tables()

    async def asyncTearDown(self):
        await self.db.close()

    async def add_players(self, *players):
        for value in players:
            await self.db.create_player(value)

    async def test_ordinary_dual_accept_race_updates_both_once_and_sets_cooldown(self):
        initiator = make_player("initiator", experience=1000)
        target = make_player("target", experience=2000)
        await self.add_players(initiator, target)
        sent = await self.manager.send_dual_request(initiator, "target")
        self.assertTrue(sent[0], sent[1])

        results = await asyncio.gather(
            *(
                self.manager.accept_dual_request(make_player("target"))
                for _ in range(10)
            )
        )
        self.assertEqual(sum(int(result[0]) for result in results), 1)
        current_initiator = await player_from_db(self.db, "initiator")
        current_target = await player_from_db(self.db, "target")
        self.assertEqual(current_initiator.experience, 1200)
        self.assertEqual(current_target.experience, 2100)
        self.assertEqual(
            await scalar(
                self.db,
                "SELECT COUNT(*) FROM dual_cultivation_requests",
            ),
            0,
        )
        self.assertIsNotNone(
            await scalar(
                self.db,
                "SELECT last_dual_time FROM dual_cultivation WHERE user_id = ?",
                ("initiator",),
            )
        )
        blocked = await self.manager.send_dual_request(initiator, "target")
        self.assertFalse(blocked[0])
        self.assertIn("冷却", blocked[1])
        self.assertLessEqual(
            int(time.time()) - (await scalar(
                self.db,
                "SELECT last_dual_time FROM dual_cultivation WHERE user_id = ?",
                ("target",),
            )),
            DUAL_CULT_COOLDOWN,
        )

    async def test_partner_dual_race_updates_both_once_and_sets_mutual_cooldown(self):
        first = make_player(
            "first", experience=1000, partner_id="second", intimacy=0
        )
        second = make_player(
            "second", experience=2000, partner_id="first", intimacy=0
        )
        await self.add_players(first, second)

        results = await asyncio.gather(
            *(self.manager.dual_cultivate(make_player("first", partner_id="second")) for _ in range(10))
        )
        self.assertEqual(sum(int(result[0]) for result in results), 1)
        current_first = await player_from_db(self.db, "first")
        current_second = await player_from_db(self.db, "second")
        self.assertEqual(current_first.experience, 1200)
        self.assertEqual(current_second.experience, 2100)
        self.assertEqual(current_first.partner_intimacy, DUAL_CULT_INTIMACY_GAIN)
        self.assertEqual(current_second.partner_intimacy, DUAL_CULT_INTIMACY_GAIN)
        self.assertEqual(
            await scalar(
                self.db,
                "SELECT COUNT(*) FROM dual_cultivation WHERE user_id IN (?, ?)",
                ("first", "second"),
            ),
            2,
        )
        self.assertEqual(
            sum(
                int(result[0])
                for result in await asyncio.gather(
                    self.manager.dual_cultivate(make_player("first", partner_id="second")),
                    self.manager.dual_cultivate(make_player("first", partner_id="second")),
                )
            ),
            0,
        )

    async def test_shared_gold_concurrent_spends_conserve_total_and_reject_invalid_amounts(self):
        first = make_player("first", gold=50, partner_id="second")
        second = make_player("second", gold=50, partner_id="first")
        await self.add_players(first, second)

        invalid_before = (
            await scalar(self.db, "SELECT gold FROM players WHERE user_id = ?", ("first",)),
            await scalar(self.db, "SELECT gold FROM players WHERE user_id = ?", ("second",)),
        )
        for amount in (0, -1, True, 1.5, "15"):
            result = await self.manager.spend_shared_gold(make_player("first", partner_id="second"), amount)
            self.assertFalse(result[0])
        self.assertEqual(
            invalid_before,
            (
                await scalar(self.db, "SELECT gold FROM players WHERE user_id = ?", ("first",)),
                await scalar(self.db, "SELECT gold FROM players WHERE user_id = ?", ("second",)),
            ),
        )

        results = await asyncio.gather(
            *(
                self.manager.spend_shared_gold(
                    make_player("first", partner_id="second"), 15
                )
                for _ in range(10)
            )
        )
        self.assertEqual(sum(int(result[0]) for result in results), 6)
        balances = (
            await scalar(self.db, "SELECT gold FROM players WHERE user_id = ?", ("first",)),
            await scalar(self.db, "SELECT gold FROM players WHERE user_id = ?", ("second",)),
        )
        self.assertEqual(sum(balances), 10)
        self.assertGreaterEqual(min(balances), 0)
        self.assertEqual(
            await self.manager.check_shared_gold(make_player("first", partner_id="second"), 11),
            (False, 10),
        )
        self.assertEqual(
            (await self.manager.get_shared_gold(make_player("first", partner_id="second")))[2],
            10,
        )


class TerminateLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        LOGGER.errors.clear()
        self.db = await new_db()
        async with self.db.transaction():
            await self.db.conn.execute("CREATE TABLE tx_values(value INTEGER)", commit=False)

    async def asyncTearDown(self):
        if self.db.conn is not None:
            await self.db.close()

    def plugin_for(self):
        plugin = object.__new__(XiuXianPlugin)
        plugin.db = self.db
        plugin.boss_task = None
        plugin.loan_check_task = None
        plugin.bounty_check_task = None
        plugin.auction_task = None
        return plugin

    async def test_terminate_waits_for_transaction_cleanup_before_close_and_is_idempotent(self):
        events = []
        started = asyncio.Event()

        async def transaction_worker():
            try:
                async with self.db.transaction():
                    await self.db.conn.execute(
                        "INSERT INTO tx_values VALUES (1)", commit=False
                    )
                    events.append("inserted")
                    started.set()
                    await asyncio.sleep(60)
            except asyncio.CancelledError:
                events.append("worker_cancelled")
                raise

        plugin = self.plugin_for()
        plugin.boss_task = asyncio.create_task(transaction_worker())
        await started.wait()
        original_close = self.db.close

        async def close_probe():
            events.append("close_start")
            if self.db.conn is None:
                events.append("already_closed")
                return
            async with self.db.conn.execute("SELECT COUNT(*) FROM tx_values") as cursor:
                row = await cursor.fetchone()
            events.append(f"rows:{row[0]}")
            await original_close()

        self.db.close = close_probe
        await plugin.terminate()
        self.assertEqual(plugin.boss_task, None)
        self.assertLess(events.index("worker_cancelled"), events.index("close_start"))
        self.assertIn("rows:0", events)
        self.assertIsNone(self.db.gate)

        await plugin.terminate()
        self.assertEqual(plugin.boss_task, None)

    async def test_terminate_logs_non_cancelled_task_exception_and_cleans_fields(self):
        started = asyncio.Event()

        async def bad_worker():
            try:
                started.set()
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                raise RuntimeError("background failure")

        plugin = self.plugin_for()
        plugin.auction_task = asyncio.create_task(bad_worker())
        await started.wait()
        await plugin.terminate()
        self.assertTrue(
            any("auction_task" in message and "background failure" in message for message in LOGGER.errors),
            LOGGER.errors,
        )
        self.assertIsNone(plugin.auction_task)


if __name__ == "__main__":
    unittest.main()
