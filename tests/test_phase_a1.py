import asyncio
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock


# The plugin is normally imported by AstrBot as a package.  Give the source
# tree a stable package name and provide the small logger surface used here so
# these tests run against the real SQLite code without AstrBot installed.
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
from _monixiuxian2_test_package.data.migration import (
    MigrationManager,
    _create_all_tables_v1,
    _migrate_to_v3,
    _migrate_to_v23,
)
from _monixiuxian2_test_package.core.storage_ring_manager import StorageRingManager
from _monixiuxian2_test_package.data.transaction import (
    ManagedConnection,
    TransactionGate,
    TransactionStateError,
    UnhealthyConnectionError,
)
from _monixiuxian2_test_package.managers.bank_manager import BankManager
from _monixiuxian2_test_package.models import Player


async def create_full_db() -> DataBase:
    db = DataBase(":memory:")
    await db.connect()
    from _monixiuxian2_test_package.data.migration import _create_all_tables_v2

    async with db.transaction():
        await _create_all_tables_v2(db.conn)
    return db


def player(user_id: str = "u", *, gold: int = 0, items: dict | None = None) -> Player:
    value = Player(user_id=user_id, user_name=user_id, gold=gold)
    if items is not None:
        value.set_storage_ring_items(items)
    return value


class GateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import aiosqlite

        raw = await aiosqlite.connect(":memory:")
        self.raw = raw
        self.gate = TransactionGate(raw)
        self.conn = ManagedConnection(raw, self.gate)
        await self.conn.execute("CREATE TABLE values_(value INTEGER)")

    async def asyncTearDown(self):
        await self.conn.close()

    async def test_owner_nested_and_rollback_only(self):
        async with self.gate.transaction():
            await self.conn.execute("INSERT INTO values_ VALUES (1)", commit=False)
            with self.assertRaises(ValueError):
                async with self.gate.transaction():
                    await self.conn.execute("INSERT INTO values_ VALUES (2)", commit=False)
                    raise ValueError("nested failure")

        async with self.conn.execute("SELECT value FROM values_") as cursor:
            self.assertEqual(await cursor.fetchall(), [])
        self.assertIsNone(self.gate.owner)
        self.assertEqual(self.gate.depth, 0)

    async def test_commit_false_requires_owner_and_cross_task_serializes(self):
        with self.assertRaises(TransactionStateError):
            await self.conn.execute("INSERT INTO values_ VALUES (1)", commit=False)

        async def write(value):
            async with self.gate.transaction():
                await self.conn.execute("INSERT INTO values_ VALUES (?)", (value,), commit=False)
                await asyncio.sleep(0)

        await asyncio.gather(*(write(i) for i in range(10)))
        async with self.conn.execute("SELECT COUNT(*) FROM values_") as cursor:
            self.assertEqual((await cursor.fetchone())[0], 10)

    async def test_cancellation_releases_owner_and_rolls_back(self):
        entered = asyncio.Event()

        async def worker():
            async with self.gate.transaction():
                await self.conn.execute("INSERT INTO values_ VALUES (9)", commit=False)
                entered.set()
                await asyncio.sleep(60)

        task = asyncio.create_task(worker())
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertIsNone(self.gate.owner)
        self.assertFalse(self.gate._lock.locked())
        await self.conn.execute("INSERT INTO values_ VALUES (10)")
        async with self.conn.execute("SELECT value FROM values_") as cursor:
            self.assertEqual([row[0] for row in await cursor.fetchall()], [10])

    async def test_unhealthy_connection_fails_closed(self):
        self.gate.mark_unhealthy("test")
        with self.assertRaises(UnhealthyConnectionError):
            await self.conn.execute("SELECT 1")

    async def test_pragma_assignment_does_not_leak_read_lease(self):
        await self.conn.execute("PRAGMA foreign_keys = ON")
        self.assertIsNone(self.gate.owner)
        await self.conn.execute("INSERT INTO values_ VALUES (11)")

    async def test_executescript_is_rejected_inside_structured_transaction(self):
        with self.assertRaises(TransactionStateError):
            async with self.gate.transaction():
                await self.conn.executescript("INSERT INTO values_ VALUES (1);")


class BankTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = await create_full_db()
        self.bank = BankManager(self.db)
        self.original = player(gold=10_000)
        await self.db.create_player(self.original)

    async def asyncTearDown(self):
        await self.db.close()

    async def test_deposit_withdraw_preserve_balance_and_ledger(self):
        ok, _ = await self.bank.deposit(self.original, 1_000)
        self.assertTrue(ok)
        ok, _ = await self.bank.withdraw(self.original, 400)
        self.assertTrue(ok)
        current = await self.db.get_player_by_id("u")
        account = await self.db.ext.get_bank_account("u")
        self.assertEqual(current.gold, 9_400)
        self.assertEqual(account["balance"], 600)
        self.assertEqual(len(await self.bank.get_transactions("u")), 2)

    async def test_failed_ledger_write_rolls_back_deposit(self):
        original = self.db.ext.add_bank_transaction
        self.db.ext.add_bank_transaction = AsyncMock(side_effect=RuntimeError("ledger down"))
        with self.assertRaises(RuntimeError):
            await self.bank.deposit(self.original, 1_000)
        self.db.ext.add_bank_transaction = original
        current = await self.db.get_player_by_id("u")
        self.assertEqual(current.gold, 10_000)
        self.assertIsNone(await self.db.ext.get_bank_account("u"))

    async def test_concurrent_deposits_are_serialized(self):
        results = await asyncio.gather(*(self.bank.deposit(self.original, 500) for _ in range(20)))
        self.assertEqual(sum(success for success, _ in results), 20)
        current = await self.db.get_player_by_id("u")
        account = await self.db.ext.get_bank_account("u")
        self.assertEqual(current.gold, 0)
        self.assertEqual(account["balance"], 10_000)

    async def test_interest_can_be_claimed_once(self):
        now = int(__import__("time").time())
        await self.db.ext.update_bank_account("u", 1_000, now - 2 * 86400)
        results = await asyncio.gather(
            self.bank.claim_interest(self.original), self.bank.claim_interest(self.original)
        )
        self.assertEqual(sum(success for success, _ in results), 1)
        account = await self.db.ext.get_bank_account("u")
        self.assertEqual(account["balance"], 1_002)
        self.assertEqual(len(await self.bank.get_transactions("u")), 1)

    async def test_borrow_and_repay_are_atomic(self):
        ok, _ = await self.bank.borrow(self.original, 1_000)
        self.assertTrue(ok)
        loan = await self.db.ext.get_active_loan("u")
        self.assertIsNotNone(loan)
        ok, _ = await self.bank.repay(self.original)
        self.assertTrue(ok)
        self.assertIsNone(await self.db.ext.get_active_loan("u"))
        current = await self.db.get_player_by_id("u")
        self.assertEqual(current.gold, 9_995)


class MigrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        if getattr(self, "db", None):
            await self.db.close()

    async def test_v1_to_v23_preserves_legacy_values(self):
        self.db = DataBase(":memory:")
        await self.db.connect()
        async with self.db.transaction():
            await _create_all_tables_v1(self.db.conn)
            await self.db.conn.execute("INSERT INTO db_info(version) VALUES (1)", commit=False)
            await self.db.conn.execute(
                "INSERT INTO players(user_id, level_index, spiritual_root, experience, gold, state, hp, max_hp, attack, defense, spiritual_power, mental_power) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                ("u", 3, "木", 123, 456, "闭关", 77, 100, 42, 9, 88, 66),
                commit=False,
            )
        await MigrationManager(self.db.conn, None).migrate()
        current = await self.db.get_player_by_id("u")
        async with self.db.conn.execute("SELECT version FROM db_info") as cursor:
            self.assertEqual((await cursor.fetchone())[0], 23)
        self.assertEqual((current.level_index, current.experience, current.gold, current.hp), (3, 123, 456, 77))
        self.assertEqual((current.atk, current.spiritual_qi, current.mental_power), (42, 88, 66))

    async def test_v3_probe_and_v23_existing_column_are_idempotent(self):
        self.db = DataBase(":memory:")
        await self.db.connect()
        async with self.db.transaction():
            await self.db.conn.execute("CREATE TABLE players(user_id TEXT PRIMARY KEY, accessory TEXT DEFAULT '')", commit=False)
            await _migrate_to_v3(self.db.conn, None)
            await _migrate_to_v3(self.db.conn, None)
            await _migrate_to_v23(self.db.conn, None)
        async with self.db.conn.execute("PRAGMA table_info(players)") as cursor:
            columns = [row[1] for row in await cursor.fetchall()]
        self.assertEqual(columns.count("cultivation_start_time"), 1)
        self.assertEqual(columns.count("accessory"), 1)

    async def test_database_newer_than_supported_is_rejected(self):
        self.db = DataBase(":memory:")
        await self.db.connect()
        async with self.db.transaction():
            await self.db.conn.execute("CREATE TABLE db_info(version INTEGER NOT NULL)", commit=False)
            await self.db.conn.execute("INSERT INTO db_info VALUES (24)", commit=False)
        with self.assertRaises(ValueError):
            await MigrationManager(self.db.conn, None).migrate()


class StorageRingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = await create_full_db()
        self.value = player(items={"灵草": 3})
        await self.db.create_player(self.value)

        class Config:
            storage_rings_data = {"基础储物戒": {"capacity": 2}}
            level_data = []
            body_level_data = []

            @staticmethod
            def is_pill(name):
                return False

        self.manager = StorageRingManager(self.db, Config())

    async def asyncTearDown(self):
        await self.db.close()

    async def test_count_validation(self):
        for count in (0, -1, "-1", "0"):
            ok, _ = await self.manager.retrieve_item(self.value, "灵草", count)
            self.assertFalse(ok)
            ok, _ = await self.manager.store_item(self.value, "灵草", count)
            self.assertFalse(ok)

    async def test_concurrent_retrieval_never_goes_negative(self):
        results = await asyncio.gather(*(self.manager.retrieve_item(self.value, "灵草", 1) for _ in range(8)))
        self.assertEqual(sum(success for success, _ in results), 3)
        current = await self.db.get_player_by_id("u")
        self.assertEqual(current.get_storage_ring_items(), {})


if __name__ == "__main__":
    unittest.main()
