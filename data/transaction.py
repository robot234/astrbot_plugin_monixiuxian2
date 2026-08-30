"""Task-owned transaction gate for the single aiosqlite connection.

The plugin deliberately shares one SQLite connection between managers.  A
plain asyncio lock around individual statements is not sufficient: a
transaction must keep ownership while the caller awaits several statements.
This module provides a small compatibility proxy for the existing
``conn.execute()/commit()/rollback()`` API and a structured transaction
context for new code.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Iterable, Optional

import aiosqlite


class TransactionStateError(RuntimeError):
    """Raised when a database operation violates transaction ownership."""


class UnhealthyConnectionError(RuntimeError):
    """Raised after a connection has been marked unusable."""


_CONTROL_RE = re.compile(r"^\s*(BEGIN(?:\s+IMMEDIATE|\s+EXCLUSIVE|\s+DEFERRED)?|COMMIT|END|ROLLBACK)\b", re.I)
# PRAGMA assignments change connection state and must be treated as writes.
# A plain ``PRAGMA table_info(...)`` remains a read and keeps its cursor lease.
_READ_RE = re.compile(r"^\s*(?:SELECT|EXPLAIN)\b|^\s*PRAGMA\s+(?![^;=]*=)", re.I)


def _skip_sql_space(sql: str, position: int) -> int:
    """Skip whitespace and leading SQL comments while scanning a statement."""
    length = len(sql)
    while position < length:
        if sql[position].isspace():
            position += 1
            continue
        if sql.startswith("--", position):
            newline = sql.find("\n", position + 2)
            position = length if newline < 0 else newline + 1
            continue
        if sql.startswith("/*", position):
            end = sql.find("*/", position + 2)
            position = length if end < 0 else end + 2
            continue
        break
    return position


def _sql_word(sql: str, position: int) -> tuple[str, int]:
    """Return the next bare SQL word and the position after it."""
    position = _skip_sql_space(sql, position)
    start = position
    while position < len(sql) and (sql[position].isalnum() or sql[position] == "_"):
        position += 1
    return sql[start:position].upper(), position


def _skip_quoted_sql(sql: str, position: int) -> int:
    """Skip a quoted SQL string/identifier, including doubled quote escapes."""
    quote = sql[position]
    if quote == "[":
        end = sql.find("]", position + 1)
        return len(sql) if end < 0 else end + 1
    position += 1
    while position < len(sql):
        if sql[position] == quote:
            if position + 1 < len(sql) and sql[position + 1] == quote:
                position += 2
                continue
            return position + 1
        position += 1
    return position


def _consume_parenthesized_sql(sql: str, position: int) -> int:
    """Return the position after a balanced parenthesized SQL expression."""
    depth = 0
    while position < len(sql):
        if sql[position] in "'\"`[":
            position = _skip_quoted_sql(sql, position)
            continue
        if sql.startswith("--", position):
            position = _skip_sql_space(sql, position)
            continue
        if sql.startswith("/*", position):
            position = _skip_sql_space(sql, position)
            continue
        if sql[position] == "(":
            depth += 1
        elif sql[position] == ")":
            depth -= 1
            if depth == 0:
                return position + 1
        position += 1
    return position


def _with_statement_keyword(sql: str, position: int) -> str:
    """Find the outer DML keyword after a WITH clause.

    Looking only at the first token is unsafe for ``WITH ... UPDATE``: treating
    it as a read would leave a cursor lease held until somebody fetches it.
    This scanner skips each CTE definition and its balanced body instead of
    relying on a greedy regular expression.
    """
    word, position = _sql_word(sql, position)
    if word == "RECURSIVE":
        position = _skip_sql_space(sql, position)

    while position < len(sql):
        # Locate the AS that belongs to this CTE, ignoring its optional column
        # list and any nested expressions.
        depth = 0
        as_position = None
        scan = position
        while scan < len(sql):
            if sql[scan] in "'\"`[":
                scan = _skip_quoted_sql(sql, scan)
                continue
            if sql.startswith("--", scan) or sql.startswith("/*", scan):
                scan = _skip_sql_space(sql, scan)
                continue
            char = sql[scan]
            if char == "(":
                depth += 1
            elif char == ")" and depth:
                depth -= 1
            elif depth == 0 and (char.isalpha() or char == "_"):
                candidate, end = _sql_word(sql, scan)
                if candidate == "AS":
                    as_position = end
                    break
                scan = end
                continue
            scan += 1
        if as_position is None:
            return ""

        position = _skip_sql_space(sql, as_position)
        modifier, modifier_end = _sql_word(sql, position)
        if modifier == "NOT":
            next_modifier, next_end = _sql_word(sql, modifier_end)
            if next_modifier == "MATERIALIZED":
                position = next_end
        elif modifier == "MATERIALIZED":
            position = modifier_end
        position = _skip_sql_space(sql, position)
        if position >= len(sql) or sql[position] != "(":
            return ""
        position = _consume_parenthesized_sql(sql, position)
        position = _skip_sql_space(sql, position)
        if position < len(sql) and sql[position] == ",":
            position = position + 1
            continue
        statement, _ = _sql_word(sql, position)
        return statement
    return ""


def _is_read_statement(sql: str) -> bool:
    """Classify SELECT-like SQL without misclassifying a DML CTE."""
    position = _skip_sql_space(sql or "", 0)
    word, end = _sql_word(sql or "", position)
    if word == "WITH":
        word = _with_statement_keyword(sql or "", end)
        return word in {"SELECT", "EXPLAIN"}
    if word in {"SELECT", "EXPLAIN"}:
        return True
    return word == "PRAGMA" and bool(_READ_RE.match((sql or "")[position:]))


class _Lease:
    __slots__ = ("gate", "owner", "released")

    def __init__(self, gate: "TransactionGate", owner: bool):
        self.gate = gate
        self.owner = owner
        self.released = False


class TransactionGate:
    """A task-aware, re-entrant owner gate around one SQLite connection.

    Ownership is stored as the current ``asyncio.Task`` object rather than a
    ``ContextVar``.  Nested transaction scopes only decrement their depth;
    any nested failure marks the outer transaction rollback-only.  A failed
    or explicitly unhealthy connection rejects future work until reconnect.
    """

    def __init__(self, raw: aiosqlite.Connection):
        self.raw = raw
        self._lock = asyncio.Lock()
        self._owner: Optional[asyncio.Task[Any]] = None
        self._depth = 0
        self._rollback_only = False
        self._unhealthy = False
        self._closed = False
        self._structured = False
        # A legacy execute without an explicit commit owns the gate until
        # commit() or rollback(), matching sqlite3 transaction semantics.
        self._implicit = False
        self._stale_cleanup: Optional[asyncio.Task[Any]] = None

    async def _await_cleanup(self, awaitable):
        """Finish a rollback/close even when the caller is cancelled.

        ``asyncio.shield`` prevents the aiosqlite worker operation from being
        cancelled, but the outer task still receives ``CancelledError``.  We
        wait for that worker operation before releasing the ownership lock so
        another task can never start against a half-rolled-back connection.
        """
        task = asyncio.ensure_future(awaitable)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError as cancellation:
            # The worker task should not normally be cancelled because it is
            # shielded.  If it does fail, surface that failure; otherwise
            # restore the caller's cancellation after cleanup has completed.
            await task
            raise cancellation

    @property
    def owner(self) -> Optional[asyncio.Task[Any]]:
        return self._owner

    @property
    def depth(self) -> int:
        return self._depth

    @property
    def rollback_only(self) -> bool:
        return self._rollback_only

    @property
    def unhealthy(self) -> bool:
        return self._unhealthy

    def mark_unhealthy(self, reason: str = "connection marked unhealthy") -> None:
        """Fail closed on future operations until the database reconnects."""
        self._unhealthy = True

    def mark_rollback_only(self) -> None:
        """Make the current transaction roll back when its owner exits."""
        task = self._task()
        if self._owner is not task:
            raise TransactionStateError("rollback-only requires the transaction owner")
        self._rollback_only = True

    def _check(self) -> None:
        if self._closed:
            raise UnhealthyConnectionError("database connection is closed")
        if self._unhealthy:
            raise UnhealthyConnectionError("database connection is unhealthy")

    def _task(self) -> asyncio.Task[Any]:
        task = asyncio.current_task()
        if task is None:
            raise TransactionStateError("database access requires an asyncio task")
        return task

    async def _acquire(self, *, commit: Optional[bool]) -> _Lease:
        self._check()
        await self._recover_stale_owner()
        task = self._task()
        if self._owner is task:
            return _Lease(self, owner=True)
        if commit is False:
            raise TransactionStateError("commit=False is only valid inside the transaction owner")
        await self._lock.acquire()
        try:
            self._check()
            self._owner = task
            self._depth = 1
            self._rollback_only = False
            self._structured = False
            self._implicit = False
            return _Lease(self, owner=False)
        except BaseException:
            self._lock.release()
            raise

    async def _recover_stale_owner(self) -> None:
        """Rollback a transaction whose task exited without cleanup."""
        owner = self._owner
        if owner is None or not owner.done():
            return
        cleanup = self._stale_cleanup
        if cleanup is None:
            cleanup = asyncio.create_task(self._rollback_stale_owner())
            self._stale_cleanup = cleanup
        try:
            await cleanup
        finally:
            if cleanup.done() and self._stale_cleanup is cleanup:
                self._stale_cleanup = None

    async def _rollback_stale_owner(self) -> None:
        try:
            await self._await_cleanup(self.raw.rollback())
        except BaseException:
            self._unhealthy = True
            raise
        finally:
            self._owner = None
            self._depth = 0
            self._rollback_only = False
            self._structured = False
            self._implicit = False
            if self._lock.locked():
                self._lock.release()

    async def operation(self, *, commit: Optional[bool] = None) -> _Lease:
        """Acquire the gate for one statement or join the current owner."""
        return await self._acquire(commit=commit)

    async def operation_deferred_success(self, lease: _Lease) -> None:
        """Release a raw-style standalone operation without committing it.

        The compatibility API deliberately leaves commit ownership to the
        caller, just like aiosqlite.  Structured transactions use the gate's
        owner lease; a legacy statement by itself must not strand the gate if
        its task returns before a later explicit commit/rollback.
        """
        if lease.released or lease.owner:
            return
        lease.released = True
        if getattr(self.raw, "in_transaction", False):
            # DML has opened a sqlite transaction. Keep ownership until the
            # same task explicitly commits or rolls it back.
            self._implicit = True
            return
        self._owner = None
        self._depth = 0
        self._rollback_only = False
        self._structured = False
        self._implicit = False
        self._lock.release()

    async def operation_success(self, lease: _Lease) -> None:
        if lease.released or lease.owner:
            return
        lease.released = True
        try:
            await self._await_cleanup(self.raw.commit())
        except BaseException:
            self._unhealthy = True
            raise
        finally:
            self._owner = None
            self._depth = 0
            self._rollback_only = False
            self._structured = False
            self._implicit = False
            self._lock.release()

    async def operation_failure(self, lease: _Lease) -> None:
        if lease.released:
            return
        if lease.owner:
            self._rollback_only = True
            return
        lease.released = True
        try:
            await self._await_cleanup(self.raw.rollback())
        except BaseException:
            self._unhealthy = True
            raise
        finally:
            self._owner = None
            self._depth = 0
            self._rollback_only = False
            self._structured = False
            self._implicit = False
            self._lock.release()

    async def begin(self, sql: str = "BEGIN IMMEDIATE", *, structured: bool = False) -> _Lease:
        """Start a manual or structured transaction."""
        self._check()
        await self._recover_stale_owner()
        task = self._task()
        if self._owner is task:
            self._depth += 1
            return _Lease(self, owner=True)

        await self._lock.acquire()
        try:
            self._check()
            cursor = await self.raw.execute(sql)
            await cursor.close()
            self._owner = task
            self._depth = 1
            self._rollback_only = False
            self._structured = structured
            self._implicit = False
            return _Lease(self, owner=False)
        except BaseException:
            try:
                await self._await_cleanup(self.raw.rollback())
            except BaseException:
                self._unhealthy = True
            self._lock.release()
            raise

    async def commit(self) -> None:
        """Commit the current owner's outer scope, or a standalone statement."""
        self._check()
        task = self._task()
        if self._owner is not task:
            lease = await self._acquire(commit=True)
            await self.operation_success(lease)
            return
        if self._structured:
            return
        if self._depth > 1:
            self._depth -= 1
            return
        try:
            if self._rollback_only:
                await self._await_cleanup(self.raw.rollback())
            else:
                await self._await_cleanup(self.raw.commit())
        except BaseException:
            self._unhealthy = True
            raise
        finally:
            self._owner = None
            self._depth = 0
            self._rollback_only = False
            self._structured = False
            self._implicit = False
            self._lock.release()

    async def rollback(self) -> None:
        """Mark nested work rollback-only, or roll back the outer scope."""
        self._check()
        task = self._task()
        if self._owner is not task:
            lease = await self._acquire(commit=True)
            await self.operation_failure(lease)
            return
        self._rollback_only = True
        if self._structured:
            return
        if self._depth > 1:
            self._depth -= 1
            return
        try:
            await self._await_cleanup(self.raw.rollback())
        except BaseException:
            self._unhealthy = True
            raise
        finally:
            self._owner = None
            self._depth = 0
            self._rollback_only = False
            self._structured = False
            self._implicit = False
            self._lock.release()

    async def finish(self) -> None:
        """Finish the outer structured transaction context."""
        if self._closed:
            raise UnhealthyConnectionError("database connection is closed")
        task = self._task()
        if self._owner is not task:
            raise TransactionStateError("structured transaction is not owned by this task")
        if self._depth != 1:
            raise TransactionStateError("cannot finish a transaction with nested scopes")
        try:
            if self._rollback_only or self._unhealthy:
                await self._await_cleanup(self.raw.rollback())
            else:
                await self._await_cleanup(self.raw.commit())
        except BaseException:
            self._unhealthy = True
            raise
        finally:
            self._owner = None
            self._depth = 0
            self._rollback_only = False
            self._structured = False
            self._implicit = False
            self._lock.release()

    def transaction(self, *, immediate: bool = True):
        return _TransactionContext(self, immediate=immediate)

    async def close(self) -> None:
        if self._closed:
            return
        task = asyncio.current_task()
        if self._owner is not None and self._owner is not task:
            await self._recover_stale_owner()
        if self._owner is not None and self._owner is not task:
            await self._lock.acquire()
            self._lock.release()
        elif self._owner is task:
            try:
                await self._await_cleanup(self.raw.rollback())
            finally:
                self._owner = None
                self._depth = 0
                self._rollback_only = False
                self._structured = False
                self._implicit = False
                if self._lock.locked():
                    self._lock.release()
        try:
            await self._await_cleanup(self.raw.close())
        finally:
            self._closed = True


class _TransactionContext:
    def __init__(self, gate: TransactionGate, *, immediate: bool):
        self.gate = gate
        self.immediate = immediate
        self.lease: Optional[_Lease] = None

    async def __aenter__(self) -> TransactionGate:
        self.lease = await self.gate.begin("BEGIN IMMEDIATE" if self.immediate else "BEGIN", structured=True)
        return self.gate

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None:
            self.gate._rollback_only = True
        if self.lease is not None and not self.lease.owner:
            await self.gate.finish()
        elif self.lease is not None:
            # A nested scope only changes depth; failures are propagated to
            # the outer owner as rollback-only state.
            if self.gate._depth > 1:
                self.gate._depth -= 1
        return False


class ManagedCursor:
    """Cursor proxy that releases a standalone read lease after fetching."""

    def __init__(
        self,
        raw: Optional[aiosqlite.Cursor],
        gate: TransactionGate,
        lease: Optional[_Lease],
        *,
        deferred: bool = False,
    ):
        self._raw = raw
        self._gate = gate
        self._lease = lease
        self._deferred = deferred

    async def _release_read(self) -> None:
        if self._lease is not None and not self._lease.released:
            if self._deferred:
                await self._gate.operation_deferred_success(self._lease)
            else:
                await self._gate.operation_success(self._lease)

    async def fetchone(self):
        try:
            if self._raw is None:
                return None
            row = await self._raw.fetchone()
        except BaseException:
            if self._lease is not None:
                await self._gate.operation_failure(self._lease)
            raise
        await self._release_read()
        return row

    async def fetchall(self):
        try:
            if self._raw is None:
                return []
            rows = await self._raw.fetchall()
        except BaseException:
            if self._lease is not None:
                await self._gate.operation_failure(self._lease)
            raise
        await self._release_read()
        return rows

    async def fetchmany(self, size=None):
        try:
            if self._raw is None:
                return []
            rows = await self._raw.fetchmany(size) if size is not None else await self._raw.fetchmany()
        except BaseException:
            if self._lease is not None:
                await self._gate.operation_failure(self._lease)
            raise
        # Keep the read lease while a batch still has rows.  Releasing it
        # between batches would let another task use the shared connection
        # while this cursor is still being iterated.
        if not rows:
            await self._release_read()
        return rows

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        try:
            while True:
                rows = await self.fetchmany()
                if not rows:
                    return
                for row in rows:
                    yield row
        finally:
            await self.close()

    async def close(self):
        try:
            if self._raw is not None:
                await self._raw.close()
        finally:
            await self._release_read()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    @property
    def rowcount(self):
        return self._raw.rowcount if self._raw is not None else -1

    @property
    def lastrowid(self):
        return self._raw.lastrowid if self._raw is not None else None

    @property
    def description(self):
        return self._raw.description if self._raw is not None else None


class ManagedResult:
    """Awaitable/async-context-manager matching aiosqlite's Result API."""

    def __init__(self, connection: "ManagedConnection", sql: str, parameters: Iterable[Any], *, commit: Optional[bool], operation: str = "execute"):
        self.connection = connection
        self.sql = sql
        self.parameters = parameters
        self.commit = commit
        self.operation = operation
        self._cursor: Optional[ManagedCursor] = None

    async def _run(self) -> ManagedCursor:
        control = _CONTROL_RE.match(self.sql or "")
        keyword = control.group(1).upper().split()[0] if control else ""
        if keyword == "BEGIN":
            await self.connection.gate.begin(self.sql.strip())
            # The cursor has no standalone lease; the transaction owner is
            # released only by commit()/rollback() or its context manager.
            self._cursor = ManagedCursor(None, self.connection.gate, None)
            return self._cursor
        if keyword in {"COMMIT", "END"}:
            await self.connection.gate.commit()
            self._cursor = ManagedCursor(None, self.connection.gate, None)
            return self._cursor
        if keyword == "ROLLBACK":
            await self.connection.gate.rollback()
            self._cursor = ManagedCursor(None, self.connection.gate, None)
            return self._cursor

        if self.operation == "executescript" and self.connection.gate.owner is asyncio.current_task():
            # sqlite3.Connection.executescript() commits any pending
            # transaction before running the script, which would make a
            # structured rollback incomplete.  Callers can execute individual
            # statements inside the structured context instead.
            raise TransactionStateError(
                "executescript is not supported inside an active transaction"
            )

        lease = await self.connection.gate.operation(commit=self.commit)
        try:
            if self.operation == "executemany":
                raw_cursor = await self.connection.raw.executemany(self.sql, self.parameters)
            elif self.operation == "executescript":
                raw_cursor = await self.connection.raw.executescript(self.sql)
            else:
                raw_cursor = await self.connection.raw.execute(self.sql, self.parameters)
            if _is_read_statement(self.sql) and not lease.owner:
                self._cursor = ManagedCursor(
                    raw_cursor,
                    self.connection.gate,
                    lease,
                    deferred=self.commit is None,
                )
            else:
                self._cursor = ManagedCursor(raw_cursor, self.connection.gate, None)
                if not lease.owner:
                    if self.commit is None:
                        await self.connection.gate.operation_deferred_success(lease)
                    else:
                        await self.connection.gate.operation_success(lease)
            return self._cursor
        except BaseException:
            await self.connection.gate.operation_failure(lease)
            raise

    def __await__(self):
        return self._run().__await__()

    async def __aenter__(self):
        return await self._run()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._cursor is not None:
            await self._cursor.close()


class ManagedConnection:
    """Compatibility proxy routing every operation through ``TransactionGate``."""

    def __init__(self, raw: aiosqlite.Connection, gate: TransactionGate):
        self.raw = raw
        self.gate = gate

    def execute(self, sql: str, parameters: Optional[Iterable[Any]] = None, *, commit: Optional[bool] = None) -> ManagedResult:
        return ManagedResult(self, sql, [] if parameters is None else parameters, commit=commit)

    def executemany(self, sql: str, parameters: Iterable[Iterable[Any]], *, commit: Optional[bool] = None) -> ManagedResult:
        return ManagedResult(self, sql, parameters, commit=commit, operation="executemany")

    def executescript(self, sql_script: str, *, commit: Optional[bool] = None) -> ManagedResult:
        return ManagedResult(self, sql_script, [], commit=commit, operation="executescript")

    async def commit(self):
        await self.gate.commit()

    async def rollback(self):
        await self.gate.rollback()

    def transaction(self, *, immediate: bool = True):
        return self.gate.transaction(immediate=immediate)

    async def close(self):
        await self.gate.close()

    def __getattr__(self, name: str):
        return getattr(self.raw, name)
