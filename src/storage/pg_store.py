"""PostgreSQL backend (Supabase, Neon, Render Postgres, …) with the same interface as SQLiteStore.

The application's SQL is written in SQLite dialect. Rather than maintain two copies, every statement goes
through :func:`translate_sql`, which handles the handful of differences we actually use:

    ?                      -> %s            (placeholders; literal % is escaped)
    INSERT OR IGNORE INTO  -> INSERT INTO … ON CONFLICT DO NOTHING
    LIKE                   -> ILIKE         (SQLite LIKE is case-insensitive for ASCII; Postgres' is not)
    datetime('now')        -> UTC timestamp text
    INSERT …               -> … RETURNING id  (so ``execute`` can return the new row id like ``lastrowid``)

The legacy introspection helpers (StateManager / DataInspector / ResultVerifier) rely on SQLite internals and are
not available in this mode; the agent path does not use them.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
import time
from decimal import Decimal
from typing import Any

try:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool
except ImportError as exc:  # pragma: no cover - depends on install
    raise ImportError(
        "TAPAN_DATABASE_URL is set but psycopg is not installed. Run: pip install 'psycopg[binary,pool]'"
    ) from exc

if sys.platform == "win32":  # psycopg's async mode cannot use the default Proactor loop on Windows
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

logger = logging.getLogger(__name__)

# ── schema ──────────────────────────────────────────────────────────
# Row Level Security is enabled on every table with no policies: Supabase exposes the `public` schema over its
# REST API, so this guarantees the anon/authenticated keys can read nothing. The app connects as the database
# owner (postgres), which bypasses RLS.
_TABLES = {
    "episodes": """
        id BIGSERIAL PRIMARY KEY, session_id TEXT NOT NULL, "timestamp" TEXT NOT NULL, user_text TEXT NOT NULL,
        assistant_text TEXT NOT NULL, emotional_state TEXT NOT NULL, tool_used TEXT,
        metadata_json TEXT NOT NULL DEFAULT '{}'""",
    "semantic_facts": """
        id BIGSERIAL PRIMARY KEY, fact_key TEXT NOT NULL, fact_value TEXT NOT NULL,
        confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5, updated_at TEXT NOT NULL""",
    "persona_profile": """
        id INTEGER PRIMARY KEY CHECK (id = 1), communication_style TEXT NOT NULL DEFAULT 'balanced',
        emotional_baseline TEXT NOT NULL DEFAULT 'neutral', preferences_json TEXT NOT NULL DEFAULT '{}',
        goals_json TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL""",
    "financial_accounts": """
        id BIGSERIAL PRIMARY KEY, account_name TEXT UNIQUE NOT NULL,
        balance DOUBLE PRECISION NOT NULL DEFAULT 0.0, updated_at TEXT NOT NULL""",
    "financial_transactions": """
        id BIGSERIAL PRIMARY KEY, account_name TEXT NOT NULL, amount DOUBLE PRECISION NOT NULL, kind TEXT NOT NULL,
        note TEXT NOT NULL DEFAULT '', "timestamp" TEXT NOT NULL""",
    "reminders": """
        id BIGSERIAL PRIMARY KEY, session_id TEXT NOT NULL, title TEXT NOT NULL, due_at TEXT,
        status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL, recurrence TEXT""",
    "ex_banks": """
        id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, balance_minor BIGINT NOT NULL DEFAULT 0,
        note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL""",
    "ex_payments": """
        id BIGSERIAL PRIMARY KEY, title TEXT NOT NULL, category TEXT NOT NULL DEFAULT 'other',
        notes TEXT NOT NULL DEFAULT '', total_minor BIGINT NOT NULL, bank_id BIGINT, due_day INTEGER NOT NULL,
        remind_days INTEGER, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'emi', grp TEXT NOT NULL DEFAULT '', settled_at TEXT,
        open_paid_minor BIGINT NOT NULL DEFAULT 0""",
    "ex_emis": """
        id BIGSERIAL PRIMARY KEY, payment_id BIGINT NOT NULL, seq INTEGER NOT NULL, amount_minor BIGINT NOT NULL,
        due_date TEXT NOT NULL, paid_at TEXT, deducted_bank_id BIGINT, deducted_minor BIGINT, reminder_id BIGINT,
        amount_custom INTEGER NOT NULL DEFAULT 0""",
    "ex_spend": """
        id BIGSERIAL PRIMARY KEY, spent_on TEXT NOT NULL, amount_minor BIGINT NOT NULL, category TEXT NOT NULL DEFAULT 'other',
        note TEXT NOT NULL DEFAULT '', sub_id BIGINT, created_at TEXT NOT NULL""",
    "ex_subs": """
        id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, amount_minor BIGINT NOT NULL, cycle TEXT NOT NULL DEFAULT 'monthly',
        next_date TEXT NOT NULL, anchor_day INTEGER NOT NULL DEFAULT 1, category TEXT NOT NULL DEFAULT 'other', bank_id BIGINT,
        active INTEGER NOT NULL DEFAULT 1, notes TEXT NOT NULL DEFAULT '', remind_days INTEGER, reminder_id BIGINT,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL""",
    "people": """
        id BIGSERIAL PRIMARY KEY, name TEXT UNIQUE NOT NULL, relationship TEXT NOT NULL DEFAULT '',
        notes TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL""",
    "calendar_events": """
        id BIGSERIAL PRIMARY KEY, title TEXT NOT NULL, start_at TEXT, end_at TEXT,
        location TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL""",
    "graph_edges": """
        id BIGSERIAL PRIMARY KEY, source TEXT NOT NULL, target TEXT NOT NULL, relation TEXT NOT NULL,
        weight DOUBLE PRECISION NOT NULL DEFAULT 1.0, created_at TEXT NOT NULL""",
    "semantic_documents": """
        id TEXT PRIMARY KEY, text_value TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT NOT NULL""",
    "state_checkpoints": """
        id BIGSERIAL PRIMARY KEY, name TEXT UNIQUE NOT NULL, state_json TEXT NOT NULL, created_at TEXT NOT NULL,
        created_by TEXT NOT NULL DEFAULT 'system', description TEXT NOT NULL DEFAULT ''""",
    "notes": """
        id BIGSERIAL PRIMARY KEY, title TEXT NOT NULL DEFAULT '', body TEXT NOT NULL, tags TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, space TEXT NOT NULL DEFAULT 'general',
        kind TEXT NOT NULL DEFAULT 'note', pinned INTEGER NOT NULL DEFAULT 0""",
    "tasks": """
        id BIGSERIAL PRIMARY KEY, title TEXT NOT NULL, due_at TEXT, priority TEXT NOT NULL DEFAULT 'normal',
        status TEXT NOT NULL DEFAULT 'open', created_at TEXT NOT NULL, completed_at TEXT,
        project TEXT NOT NULL DEFAULT '', details TEXT NOT NULL DEFAULT '', reminder_id BIGINT,
        remind TEXT NOT NULL DEFAULT ''""",
    "memories": """
        id BIGSERIAL PRIMARY KEY, content TEXT NOT NULL, category TEXT NOT NULL DEFAULT 'general',
        created_at TEXT NOT NULL""",
    "app_settings": """
        id TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL""",
    "push_subscriptions": """
        id BIGSERIAL PRIMARY KEY, endpoint TEXT UNIQUE NOT NULL, p256dh TEXT NOT NULL, auth TEXT NOT NULL,
        user_agent TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, last_success_at TEXT, last_error TEXT""",
    "notifications": """
        id BIGSERIAL PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL""",
}

_MIGRATIONS = (
    ("reminders", "recurrence", "TEXT"),
    ("ex_payments", "kind", "TEXT NOT NULL DEFAULT 'emi'"),
    ("ex_payments", "grp", "TEXT NOT NULL DEFAULT ''"),
    ("ex_payments", "settled_at", "TEXT"),
    ("ex_payments", "open_paid_minor", "BIGINT NOT NULL DEFAULT 0"),
    ("ex_emis", "amount_custom", "INTEGER NOT NULL DEFAULT 0"),
    ("notes", "space", "TEXT NOT NULL DEFAULT 'general'"),
    ("notes", "kind", "TEXT NOT NULL DEFAULT 'note'"),
    ("notes", "pinned", "INTEGER NOT NULL DEFAULT 0"),
    ("tasks", "project", "TEXT NOT NULL DEFAULT ''"),
    ("tasks", "details", "TEXT NOT NULL DEFAULT ''"),
    ("tasks", "reminder_id", "BIGINT"),
    ("tasks", "remind", "TEXT NOT NULL DEFAULT ''"),
)

_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_episodes_session ON episodes(session_id, id)",
    "CREATE INDEX IF NOT EXISTS idx_reminders_status_due ON reminders(status, due_at)",
    "CREATE INDEX IF NOT EXISTS idx_ex_emis_payment ON ex_emis(payment_id, seq)",
    "CREATE INDEX IF NOT EXISTS idx_ex_emis_due ON ex_emis(due_date)",
    "CREATE INDEX IF NOT EXISTS idx_ex_spend_day ON ex_spend(spent_on)",
    "CREATE INDEX IF NOT EXISTS idx_notes_space ON notes(space, kind)",
)


def schema_sql() -> str:
    parts = [f"CREATE TABLE IF NOT EXISTS {name} ({cols});" for name, cols in _TABLES.items()]
    parts += [f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS {c} {d};" for t, c, d in _MIGRATIONS]   # for tables that predate a column
    parts += [f"{stmt};" for stmt in _INDEXES]
    parts += [f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY;" for name in _TABLES]
    parts.append(
        "INSERT INTO persona_profile (id, communication_style, emotional_baseline, preferences_json, goals_json, "
        "updated_at) VALUES (1, 'balanced', 'neutral', '{}', '{}', "
        "to_char(timezone('utc', now()), 'YYYY-MM-DD HH24:MI:SS')) ON CONFLICT DO NOTHING;"
    )
    return "\n".join(parts)


# ── SQLite -> Postgres translation ──────────────────────────────────
_STRING_RE = re.compile(r"'(?:[^']|'')*'")
_INSERT_IGNORE_RE = re.compile(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", re.IGNORECASE)
_LIKE_RE = re.compile(r"\bLIKE\b", re.IGNORECASE)
_NOW_RE = re.compile(r"datetime\(\s*'now'\s*\)", re.IGNORECASE)
_UTC_NOW = "to_char(timezone('utc', now()), 'YYYY-MM-DD HH24:MI:SS')"


def translate_sql(sql: str) -> tuple[str, bool]:
    """Return (postgres_sql, wants_returning_id). String literals are never modified."""
    ignore = bool(_INSERT_IGNORE_RE.search(sql))
    sql = _NOW_RE.sub(_UTC_NOW, sql)  # contains a quoted literal, so it must run before string-splitting
    pieces: list[str] = []
    last = 0
    for match in _STRING_RE.finditer(sql):
        pieces.append(_translate_code(sql[last : match.start()]))
        pieces.append(match.group(0).replace("%", "%%"))
        last = match.end()
    pieces.append(_translate_code(sql[last:]))
    out = "".join(pieces).strip().rstrip(";")

    is_insert = out.lstrip().upper().startswith("INSERT")
    if ignore:
        out += " ON CONFLICT DO NOTHING"
    returning = is_insert and " RETURNING " not in out.upper()
    if returning:
        out += " RETURNING id"
    return out, is_insert


def _translate_code(code: str) -> str:
    code = code.replace("%", "%%").replace("?", "%s")
    code = _INSERT_IGNORE_RE.sub("INSERT INTO", code)
    return _LIKE_RE.sub("ILIKE", code)


def _clean(row: dict[str, Any]) -> dict[str, Any]:
    return {k: (float(v) if isinstance(v, Decimal) else v) for k, v in row.items()}


def _with_ssl(dsn: str) -> str:
    """Hosted Postgres (Supabase etc.) requires TLS; make that the default for non-local hosts."""
    if "sslmode=" in dsn or not dsn.startswith(("postgres://", "postgresql://")):
        return dsn
    host = dsn.split("@")[-1].split("/")[0].split(":")[0]
    if host in {"localhost", "127.0.0.1", "::1"}:
        return dsn
    return dsn + ("&" if "?" in dsn else "?") + "sslmode=require"


class PostgresStore:
    """Async Postgres repository with the SQLiteStore interface."""

    dialect = "postgres"

    # Why this class is careful about round trips: the database is usually in another region from the server, so every statement
    # costs a network hop (about 60 ms between Singapore and Mumbai). Three things keep a request to a handful of hops:
    #   * a transaction is sent as *one multi-statement script* (values bound client-side by psycopg's own escaping), which the server
    #     runs atomically: N statements cost one hop instead of N + 2. Measured at 200 ms per hop: 20 inserts take 4.8 s as a plain
    #     transaction, 0.9 s in pipeline mode and 0.2 s as one script;
    #   * the pool's liveness check (an extra hop per checkout) is skipped for a connection that was used a moment ago;
    #   * a few connections are kept open, so a burst of parallel reads does not pay for new TLS handshakes.
    FRESH_SECONDS = 10.0
    BATCH = os.getenv("TAPAN_PG_BATCH", "1").strip().lower() not in {"0", "false", "no", "off"}

    def __init__(self, dsn: str, min_size: int = 2, max_size: int = 6) -> None:
        self.dsn = _with_ssl(dsn)
        self.db_path = "postgres"  # SQLiteStore compatibility (shown in diagnostics only)
        self._min, self._max = min_size, max_size
        self._pool: AsyncConnectionPool | None = None
        self._pool_loop: asyncio.AbstractEventLoop | None = None

    # ── lifecycle ───────────────────────────────────────────────────
    async def initialize(self) -> None:
        """Create tables (idempotent). Uses a throwaway connection so no pool is bound to this event loop."""
        async with await psycopg.AsyncConnection.connect(self.dsn, autocommit=True, prepare_threshold=None) as conn:
            await conn.execute(schema_sql())  # no params => simple protocol, multiple statements allowed

    async def aclose(self) -> None:
        if self._pool is not None and self._pool_loop is asyncio.get_running_loop():
            await self._pool.close()
        self._pool = None

    async def _get_pool(self) -> AsyncConnectionPool:
        """Open the pool lazily inside the *serving* event loop (create_app builds the runtime in another loop)."""
        loop = asyncio.get_running_loop()
        if self._pool is None or self._pool_loop is not loop:
            self._pool = AsyncConnectionPool(
                self.dsn,
                min_size=self._min,
                max_size=self._max,
                open=False,
                check=self._check,                            # drop connections the pooler closed while idle
                max_idle=240,
                kwargs={"autocommit": True, "row_factory": dict_row, "prepare_threshold": None},  # pgbouncer-safe
            )
            await self._pool.open(wait=True, timeout=20)
            self._pool_loop = loop
        return self._pool

    @classmethod
    async def _check(cls, conn: Any) -> None:
        """The pool's liveness check, skipped when the connection answered a query in the last few seconds."""
        if time.monotonic() - getattr(conn, "_tapan_used", 0.0) < cls.FRESH_SECONDS:
            return
        await AsyncConnectionPool.check_connection(conn)

    @staticmethod
    def _touch(conn: Any) -> None:
        try:
            conn._tapan_used = time.monotonic()
        except AttributeError:  # a connection type that does not allow attributes: the check simply always runs
            pass

    # ── SQLiteStore interface ───────────────────────────────────────
    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        query, returning = translate_sql(sql)
        pool = await self._get_pool()
        async with pool.connection() as conn:
            cur = await conn.execute(query, tuple(params))
            result = await self._new_id(cur) if returning else 0
            self._touch(conn)
            return result

    async def execute_transaction(self, operations: list[tuple[str, tuple[Any, ...]]]) -> list[int]:
        if not operations:
            return []
        if len(operations) == 1:                              # one statement is already atomic: no BEGIN/COMMIT hops around it
            return [await self.execute(*operations[0])]
        if self.BATCH:
            try:
                return await self._transaction_script(operations)
            except (psycopg.errors.FeatureNotSupported, psycopg.errors.ProtocolViolation):
                # The server or pooler refused the script outright, so nothing ran: fall back for good and say so once.
                type(self).BATCH = False
                logger.warning("Postgres refused a batched transaction; running transactions statement by statement from now on")
        return await self._transaction_plain(operations)

    async def _transaction_plain(self, operations: list[tuple[str, tuple[Any, ...]]]) -> list[int]:
        """One network hop per statement (plus BEGIN and COMMIT). Kept as the fallback behind TAPAN_PG_BATCH=0."""
        pool = await self._get_pool()
        ids: list[int] = []
        async with pool.connection() as conn:
            async with conn.transaction():
                for sql, params in operations:
                    query, returning = translate_sql(sql)
                    cur = await conn.execute(query, tuple(params))
                    ids.append(await self._new_id(cur) if returning else 0)
            self._touch(conn)
        return ids

    async def _transaction_script(self, operations: list[tuple[str, tuple[Any, ...]]]) -> list[int]:
        """Every statement in one message. A multi-statement simple query is a single implicit transaction on the server: all of it
        happens or none of it does. Values are bound by psycopg's client-side cursor, which quotes them exactly as libpq would."""
        pool = await self._get_pool()
        translated = [translate_sql(sql) for sql, _ in operations]
        async with pool.connection() as conn:
            cur = psycopg.AsyncClientCursor(conn)
            script = "; ".join(cur.mogrify(query, tuple(params)) for (query, _), (_, params) in zip(translated, operations))
            await cur.execute(script)
            ids: list[int] = []
            for index, (_, returning) in enumerate(translated):
                row = await cur.fetchone() if returning and cur.description else None
                try:
                    ids.append(int(row["id"]) if row else 0)
                except (TypeError, ValueError):               # tables keyed by TEXT id (semantic_documents)
                    ids.append(0)
                if index < len(translated) - 1:
                    cur.nextset()
            self._touch(conn)
        return ids

    async def _read(self, query: str, params: tuple[Any, ...], one: bool) -> Any:
        """A read is safe to repeat, so a connection the pooler dropped behind our back costs one retry, not an error."""
        for attempt in (0, 1):
            pool = await self._get_pool()
            try:
                async with pool.connection() as conn:
                    cur = await conn.execute(query, tuple(params))
                    out = await cur.fetchone() if one else await cur.fetchall()
                    self._touch(conn)
                    return out
            except psycopg.OperationalError:
                if attempt:
                    raise
        return None  # pragma: no cover

    async def fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        query, _ = translate_sql(sql)
        row = await self._read(query, params, True)
        return _clean(row) if row else None

    async def fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        query, _ = translate_sql(sql)
        return [_clean(r) for r in await self._read(query, params, False)]

    @staticmethod
    async def _new_id(cur: Any) -> int:
        row = await cur.fetchone() if cur.description else None
        try:
            return int(row["id"]) if row else 0
        except (TypeError, ValueError):  # tables keyed by TEXT id (semantic_documents)
            return 0

    @staticmethod
    def parse_json_field(value: str | None) -> dict[str, Any]:
        from src.storage.sqlite_store import SQLiteStore

        return SQLiteStore.parse_json_field(value)

    def _connect(self):  # pragma: no cover - guard for legacy SQLite-only helpers
        raise RuntimeError("This legacy helper needs SQLite; it is disabled when TAPAN_DATABASE_URL is set.")
