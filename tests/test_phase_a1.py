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
    _create_all_tables_v2,
    _migrate_to_v20,
    _migrate_to_v21,
    _migrate_to_v22,
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


async def scalar(db, sql, params=()):
    async with db.conn.execute(sql, params) as cursor:
        row = await cursor.fetchone()
    return row[0] if row else None


class FakeCursor:
    def __init__(self, rowcount=0, lastrowid=None):
        self.rowcount = rowcount
        self.lastrowid = lastrowid


class FakeResult:
    def __init__(self, cursor):
        self.cursor = cursor

    def __await__(self):
        async def resolve():
            return self.cursor

        return resolve().__await__()


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

    async def test_default_execute_defers_commit_until_explicit_boundary(self):
        await self.conn.execute("INSERT INTO values_ VALUES (1)")
        self.assertTrue(self.raw.in_transaction)
        await self.conn.rollback()

        async with self.conn.execute("SELECT value FROM values_") as cursor:
            self.assertEqual(await cursor.fetchall(), [])

        await self.conn.execute("INSERT INTO values_ VALUES (2)")
        await self.conn.commit()
        async with self.conn.execute("SELECT value FROM values_") as cursor:
            self.assertEqual([row[0] for row in await cursor.fetchall()], [2])

    async def test_fetchmany_keeps_read_lease_until_exhausted(self):
        await self.conn.execute("INSERT INTO values_ VALUES (1)", commit=True)
        await self.conn.execute("INSERT INTO values_ VALUES (2)", commit=True)
        writer_done = asyncio.Event()

        async def writer():
            await self.conn.execute("INSERT INTO values_ VALUES (3)", commit=True)
            writer_done.set()

        async with self.conn.execute("SELECT value FROM values_ ORDER BY value") as cursor:
            self.assertEqual(await cursor.fetchmany(1), [(1,)])
            writer_task = asyncio.create_task(writer())
            await asyncio.sleep(0)
            self.assertFalse(writer_done.is_set())
            self.assertEqual(await cursor.fetchmany(1), [(2,)])
            self.assertFalse(writer_done.is_set())
            self.assertEqual(await cursor.fetchmany(1), [])
            await asyncio.wait_for(writer_done.wait(), 1)
            await writer_task

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

    async def test_rowcount_conflicts_roll_back_withdraw_borrow_and_repay(self):
        ok, _ = await self.bank.deposit(self.original, 1_000)
        self.assertTrue(ok)

        original_execute = self.db.conn.execute

        def fail_player_credit(sql, parameters=None, *, commit=None):
            if sql.lstrip().upper().startswith("UPDATE PLAYERS SET GOLD = GOLD +"):
                return FakeResult(FakeCursor(rowcount=0))
            return original_execute(sql, parameters, commit=commit)

        self.db.conn.execute = fail_player_credit
        try:
            ok, _ = await self.bank.withdraw(self.original, 500)
        finally:
            self.db.conn.execute = original_execute
        self.assertFalse(ok)
        self.assertEqual((await self.db.get_player_by_id("u")).gold, 9_000)
        self.assertEqual((await self.db.ext.get_bank_account("u"))["balance"], 1_000)
        self.assertEqual(len(await self.bank.get_transactions("u")), 1)

        original_execute = self.db.conn.execute

        def fail_player_credit_for_borrow(sql, parameters=None, *, commit=None):
            if sql.lstrip().upper().startswith("UPDATE PLAYERS SET GOLD = GOLD +"):
                return FakeResult(FakeCursor(rowcount=0))
            return original_execute(sql, parameters, commit=commit)

        self.db.conn.execute = fail_player_credit_for_borrow
        try:
            ok, _ = await self.bank.borrow(self.original, 1_000)
        finally:
            self.db.conn.execute = original_execute
        self.assertFalse(ok)
        self.assertIsNone(await self.db.ext.get_active_loan("u"))
        self.assertEqual((await self.db.get_player_by_id("u")).gold, 9_000)

        ok, _ = await self.bank.borrow(self.original, 1_000)
        self.assertTrue(ok)
        original_execute = self.db.conn.execute

        def fail_loan_close(sql, parameters=None, *, commit=None):
            if sql.lstrip().upper().startswith("UPDATE BANK_LOANS SET STATUS = 'CLOSED'"):
                return FakeResult(FakeCursor(rowcount=0))
            return original_execute(sql, parameters, commit=commit)

        self.db.conn.execute = fail_loan_close
        try:
            ok, _ = await self.bank.repay(self.original)
        finally:
            self.db.conn.execute = original_execute
        self.assertFalse(ok)
        self.assertEqual((await self.db.get_player_by_id("u")).gold, 10_000)
        self.assertIsNotNone(await self.db.ext.get_active_loan("u"))


class CascadeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = await create_full_db()
        self.value = player(gold=100)
        await self.db.create_player(self.value)

    async def asyncTearDown(self):
        await self.db.close()

    async def test_cascade_uses_real_combat_cooldown_schema_and_is_atomic(self):
        await self.db.ext.update_bank_account("u", 25, 1)
        async with self.db.transaction():
            await self.db.conn.execute(
                "INSERT INTO combat_cooldowns(user_id, last_duel_time, last_spar_time) VALUES (?, ?, ?)",
                ("u", 1, 2),
                commit=False,
            )

        await self.db.delete_player_cascade("u")
        self.assertIsNone(await self.db.get_player_by_id("u"))
        self.assertIsNone(await self.db.ext.get_bank_account("u"))
        self.assertEqual(await scalar(self.db, "SELECT COUNT(*) FROM combat_cooldowns WHERE user_id = ?", ("u",)), 0)

    async def test_cascade_structural_failure_rolls_back_prior_deletes(self):
        await self.db.ext.update_bank_account("u", 25, 1)
        await self.db.conn.execute("DROP TABLE combat_cooldowns", commit=True)
        with self.assertRaises(Exception):
            await self.db.delete_player_cascade("u")
        self.assertIsNotNone(await self.db.get_player_by_id("u"))
        self.assertIsNotNone(await self.db.ext.get_bank_account("u"))

    async def test_overdue_processing_deletes_and_ledger_writes_atomically(self):
        now = int(__import__("time").time())
        await self.db.ext.create_loan("u", 1_000, 0.005, now - 10 * 86400, now - 1)
        async with self.db.transaction():
            await self.db.conn.execute(
                "INSERT INTO combat_cooldowns(user_id, last_duel_time, last_spar_time) VALUES (?, ?, ?)",
                ("u", 1, 2),
                commit=False,
            )

        bank = BankManager(self.db)
        processed = await bank.check_and_process_overdue_loans()
        self.assertEqual(len(processed), 1)
        self.assertIsNone(await self.db.get_player_by_id("u"))
        self.assertEqual(await scalar(self.db, "SELECT status FROM bank_loans WHERE user_id = ?", ("u",)), "overdue")
        self.assertEqual(
            await scalar(
                self.db,
                "SELECT COUNT(*) FROM bank_transactions WHERE user_id = ? AND trans_type = 'bank_kill'",
                ("u",),
            ),
            1,
        )
        self.assertEqual(await scalar(self.db, "SELECT COUNT(*) FROM combat_cooldowns WHERE user_id = ?", ("u",)), 0)


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

    async def test_v20_v22_partial_schema_migrations_are_idempotent(self):
        self.db = DataBase(":memory:")
        await self.db.connect()
        async with self.db.transaction():
            await self.db.conn.execute(
                "CREATE TABLE user_cd(user_id TEXT PRIMARY KEY, type INTEGER, create_time INTEGER, scheduled_time INTEGER)",
                commit=False,
            )
            await self.db.conn.execute(
                "CREATE TABLE spirit_eyes(eye_id INTEGER PRIMARY KEY, spawn_time INTEGER)",
                commit=False,
            )
            await self.db.conn.execute(
                "CREATE TABLE players(user_id TEXT PRIMARY KEY)", commit=False
            )
            await _migrate_to_v20(self.db.conn, None)
            await _migrate_to_v20(self.db.conn, None)
            await _migrate_to_v21(self.db.conn, None)
            await _migrate_to_v21(self.db.conn, None)
            await _migrate_to_v22(self.db.conn, None)
            await _migrate_to_v22(self.db.conn, None)

        async with self.db.conn.execute("PRAGMA table_info(user_cd)") as cursor:
            user_cd_columns = [row[1] for row in await cursor.fetchall()]
        async with self.db.conn.execute("PRAGMA table_info(spirit_eyes)") as cursor:
            eye_columns = [row[1] for row in await cursor.fetchall()]
        async with self.db.conn.execute("PRAGMA table_info(players)") as cursor:
            player_columns = [row[1] for row in await cursor.fetchall()]
        self.assertEqual(user_cd_columns.count("extra_data"), 1)
        self.assertEqual(eye_columns.count("last_collect_time"), 1)
        for column in (
            "max_hp", "max_mp", "speed", "critical_rate", "critical_damage",
            "hit_rate", "dodge_rate", "learned_skills", "equipped_skills",
            "partner_id", "partner_bindtime", "partner_intimacy",
        ):
            self.assertEqual(player_columns.count(column), 1)

    async def test_complete_v2_schema_fast_forwards_to_latest(self):
        self.db = DataBase(":memory:")
        await self.db.connect()
        async with self.db.transaction():
            await _create_all_tables_v2(self.db.conn)
            await self.db.conn.execute(
                "INSERT INTO db_info(version) VALUES (2)", commit=False
            )
        await MigrationManager(self.db.conn, None).migrate()
        self.assertEqual(await scalar(self.db, "SELECT version FROM db_info"), 23)


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
