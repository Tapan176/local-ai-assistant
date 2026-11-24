"""Postgres backend: SQL translation (pure) + integration against a real embedded Postgres (pgserver).

Integration tests are skipped automatically if `pgserver` is not installed (pip install pgserver).
To run them against any other Postgres instead, set TAPAN_TEST_DATABASE_URL (it will be TRUNCATED).
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import timedelta

import httpx
import pytest

psycopg = pytest.importorskip("psycopg")

from src.agent import timeutil  # noqa: E402
from src.agent.service import ReminderScheduler  # noqa: E402
from src.agent.skill import SkillContext  # noqa: E402
from src.agent.skills import build_registry  # noqa: E402
from src.config.settings import Settings  # noqa: E402
from src.storage import pg_store  # noqa: E402
from src.storage.pg_store import PostgresStore, _with_ssl, schema_sql, translate_sql  # noqa: E402


# ── pure translation tests (no database) ────────────────────────────
def test_placeholders_and_percent_escaping():
    sql, _ = translate_sql("SELECT * FROM t WHERE a = ? AND b LIKE ? AND c = '100%?'")
    assert sql == "SELECT * FROM t WHERE a = %s AND b ILIKE %s AND c = '100%%?'"


def test_insert_or_ignore_and_returning():
    sql, returning = translate_sql("INSERT OR IGNORE INTO people (name) VALUES (?)")
    assert sql == "INSERT INTO people (name) VALUES (%s) ON CONFLICT DO NOTHING RETURNING id" and returning

    sql, returning = translate_sql("INSERT INTO t (a) VALUES (?) ON CONFLICT(a) DO UPDATE SET a = excluded.a;")
    assert sql.endswith("DO UPDATE SET a = excluded.a RETURNING id") and returning

    sql, returning = translate_sql("INSERT INTO t (a) VALUES (?) RETURNING a")
    assert sql.count("RETURNING") == 1 and returning

    sql, returning = translate_sql("UPDATE t SET a = ? WHERE id = ?")
    assert sql == "UPDATE t SET a = %s WHERE id = %s" and not returning


def test_string_literals_are_never_rewritten():
    sql, _ = translate_sql("SELECT 'it''s LIKE datetime(''now'') ?' AS x, y LIKE ?")
    assert "'it''s LIKE datetime(''now'') ?'" in sql and sql.endswith("y ILIKE %s")


def test_datetime_now_translated():
    sql, _ = translate_sql("SELECT 1 WHERE created_at > datetime('now')")
    assert "to_char(timezone('utc', now())" in sql


def test_ssl_default_for_remote_hosts_only():
    assert _with_ssl("postgresql://u:p@db.x.supabase.co:5432/postgres").endswith("?sslmode=require")
    assert _with_ssl("postgresql://u:p@h/db?application_name=a").endswith("&sslmode=require")
    assert _with_ssl("postgresql://u:p@localhost:5432/db") == "postgresql://u:p@localhost:5432/db"
    assert _with_ssl("postgresql://u:p@h/db?sslmode=disable").count("sslmode") == 1


def test_schema_covers_every_sqlite_table():
    import sqlite3

    from src.storage.sqlite_store import SCHEMA_SQL

    lite = sqlite3.connect(":memory:")
    lite.executescript(SCHEMA_SQL)
    for (table,) in lite.execute("SELECT name FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence'"):
        columns = {r[1] for r in lite.execute(f"PRAGMA table_info({table})")}
        assert f"CREATE TABLE IF NOT EXISTS {table} (" in schema_sql(), f"{table} missing from Postgres schema"
        pg_block = schema_sql().split(f"CREATE TABLE IF NOT EXISTS {table} (")[1].split(");")[0]
        for col in columns:
            assert col in pg_block, f"{table}.{col} missing from Postgres schema"
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in schema_sql()


# ── integration fixtures ────────────────────────────────────────────
@pytest.fixture(scope="session")
def pg_dsn():
    external = os.getenv("TAPAN_TEST_DATABASE_URL")
    if external:
        yield external
        return
    pgserver = pytest.importorskip("pgserver")
    with tempfile.TemporaryDirectory(prefix="tapan_pg_") as data_dir:
        server = pgserver.get_server(data_dir)
        try:
            yield server.get_uri()
        finally:
            server.cleanup()


@pytest.fixture
async def pg(pg_dsn):
    store = PostgresStore(pg_dsn)
    await store.initialize()
    with psycopg.connect(pg_dsn, autocommit=True) as conn:  # clean slate for every test
        tables = [r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")]
        conn.execute("TRUNCATE " + ", ".join(tables) + " RESTART IDENTITY")
    await store.initialize()  # re-seed the persona row
    yield store
    await store.aclose()


@pytest.fixture
def settings(tmp_path):
    return Settings(llm_provider="omniroute", omniroute_api_key="k", environment="local", timezone="UTC",
                    workspace_dir=str(tmp_path / "ws"))


@pytest.fixture
async def ctx(settings, pg):
    async with httpx.AsyncClient() as http:
        yield SkillContext(settings=settings, store=pg, http=http, session_id="pg")


# ── integration tests ───────────────────────────────────────────────
async def test_schema_is_idempotent_and_rls_enabled(pg, pg_dsn):
    await pg.initialize()  # second run must not fail
    rows = await pg.fetchall("SELECT relname, relrowsecurity FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind = 'r'")
    assert rows and all(r["relrowsecurity"] for r in rows), [r for r in rows if not r["relrowsecurity"]]
    assert (await pg.fetchone("SELECT id FROM persona_profile"))["id"] == 1


async def test_basic_store_semantics(pg):
    first = await pg.execute("INSERT INTO people (name, relationship, notes, updated_at) VALUES (?, ?, ?, ?)", ("Ravi", "manager", "", "t"))
    assert first == 1
    # upsert path used by PeopleTool
    await pg.execute(
        "INSERT INTO people (name, relationship, notes, updated_at) VALUES (?, ?, ?, ?) ON CONFLICT(name) DO UPDATE SET relationship = excluded.relationship",
        ("Ravi", "boss", "", "t2"),
    )
    assert (await pg.fetchone("SELECT relationship FROM people WHERE name = ?", ("Ravi",)))["relationship"] == "boss"
    # INSERT OR IGNORE: second insert is silently skipped and returns 0
    await pg.execute("INSERT OR IGNORE INTO financial_accounts (account_name, balance, updated_at) VALUES (?, ?, ?)", ("axis", 5, "t"))
    assert await pg.execute("INSERT OR IGNORE INTO financial_accounts (account_name, balance, updated_at) VALUES (?, ?, ?)", ("axis", 9, "t")) == 0
    assert (await pg.fetchone("SELECT balance FROM financial_accounts"))["balance"] == 5.0
    # TEXT-keyed table must not blow up when RETURNING id is not an integer
    assert await pg.execute("INSERT OR IGNORE INTO semantic_documents (id, text_value, metadata_json, updated_at) VALUES (?, ?, ?, ?)", ("doc-a", "x", "{}", "t")) == 0
    # LIKE is case-insensitive (SQLite behaviour) and '%' in parameters is safe
    assert await pg.fetchall("SELECT name FROM people WHERE name LIKE ?", ("%rAv%",))
    assert not await pg.fetchall("SELECT name FROM people WHERE name LIKE ?", ("%zzz%",))
    # transactions are atomic
    with pytest.raises(Exception):
        await pg.execute_transaction([
            ("INSERT INTO notes (title, body, tags, created_at, updated_at) VALUES ('a','b','','t','t')", ()),
            ("INSERT INTO nope VALUES (1)", ()),
        ])
    assert await pg.fetchone("SELECT COUNT(*) AS c FROM notes") == {"c": 0}
    ids = await pg.execute_transaction([("INSERT INTO notes (title, body, tags, created_at, updated_at) VALUES (?,?,?,?,?)", ("a", "b", "", "t", "t"))] * 2)
    assert ids[1] == ids[0] + 1 and ids[0] > 0  # sequences are not rolled back by the failed transaction above
    # SUM over double precision comes back as float (not Decimal)
    await pg.execute("INSERT INTO financial_transactions (account_name, amount, kind, note, timestamp) VALUES (?,?,?,?,?)", ("axis", 10, "credit", "n", "t"))
    total = (await pg.fetchone("SELECT SUM(amount) AS s FROM financial_transactions"))["s"]
    assert isinstance(total, float) and total == 10.0


async def test_all_agent_skills_work_on_postgres(pg, settings, ctx):
    registry = build_registry(settings)

    async def run(name, **args):
        ok, text = await registry.execute(name, args, ctx)
        assert ok, f"{name}: {text}"
        return text

    assert "Remembered" in await run("remember", content="Likes green tea", category="preference")
    assert "Already remembered" in await run("remember", content="likes GREEN tea")
    assert "green tea" in await run("recall", query="TEA")
    await run("add_note", body="Buy filament", title="shopping", tags="home")
    assert "filament" in await run("search_notes", query="FILAMENT")
    await run("add_task", title="File taxes", due="2030-01-02T09:00", priority="high")
    assert "File taxes" in await run("list_tasks")
    await run("complete_task", id="1")
    assert "No open tasks" in await run("list_tasks")
    await run("set_reminder", title="Call mom", when=(timeutil.now(settings) + timedelta(days=1)).isoformat())
    assert "Call mom" in await run("list_reminders")
    batch = await run("set_reminders", reminders=[
        {"title": "Pay rent", "when": (timeutil.now(settings) + timedelta(days=2)).isoformat()},
        {"title": "Gym", "when": (timeutil.now(settings) + timedelta(days=3)).isoformat()},
        {"title": "Bad", "when": "never"},
    ])
    assert "2 reminder(s) set, 1 skipped" in batch
    assert "Pay rent" in await run("list_reminders") and "Gym" in await run("list_reminders")
    briefing = await run("daily_briefing")
    assert "reminders_today" in briefing
    await pg.execute('INSERT INTO episodes (session_id, "timestamp", user_text, assistant_text, emotional_state) VALUES (?,?,?,?,?)',
                     ("old-chat", "2026-10-01T10:00:00+00:00", "my passport expires in March", "Noted, I will remind you.", "neutral"))
    found = await run("search_history", query="passport expiry March")
    assert "old-chat" in found and "passport" in found


async def test_scheduler_fires_reminder_once_on_postgres(pg, settings):
    await pg.execute("INSERT INTO reminders (session_id, title, due_at, status, created_at) VALUES (?,?,?,'pending',?)",
                     ("s", "Stretch", (timeutil.now(settings) - timedelta(minutes=1)).isoformat(), "t"))
    sched = ReminderScheduler(pg, settings)
    assert await sched.tick() == 1 and await sched.tick() == 0
    assert (await pg.fetchone("SELECT title, body FROM notifications")) == {"title": "Reminder", "body": "Stretch"}


async def test_concurrent_tool_calls_on_postgres(pg, settings, ctx):
    registry = build_registry(settings)
    results = await asyncio.gather(
        *(registry.execute("remember", {"content": f"fact {i}"}, ctx) for i in range(40)),
        *(registry.execute("add_task", {"title": f"task {i}"}, ctx) for i in range(40)),
        *(registry.execute("recall", {"query": "fact"}, ctx) for _ in range(20)),
    )
    assert not [t for ok, t in results if not ok]
    assert await pg.fetchone("SELECT (SELECT COUNT(*) FROM memories) AS m, (SELECT COUNT(*) FROM tasks) AS t") == {"m": 40, "t": 40}


async def test_legacy_tools_work_on_postgres(pg):
    """The original finance / reminder / people / calendar tools, unchanged, on the Postgres store."""
    from src.models import MemoryContext, ReasoningOutput
    from src.storage.supermemory_store import SupermemoryStore
    from src.tools.calendar_tool import CalendarTool
    from src.tools.finance_tool import FinanceTool
    from src.tools.people_tool import PeopleTool
    from src.tools.reminder_tool import ReminderTool

    reasoning, memory = ReasoningOutput(inferred_intent="x", confidence=1.0), MemoryContext()
    finance, people = FinanceTool(pg), PeopleTool(pg, SupermemoryStore(""))
    reminders, calendar = ReminderTool(pg), CalendarTool(pg)

    async def run(tool, text):
        result = await tool.execute("s1", text, reasoning, memory)
        assert result.success, f"{text!r} -> {result.output_text}"
        return result.output_text

    await run(finance, "create account savings with 1000")
    await run(finance, "add 400 to savings")
    assert "1400" in await run(finance, "show accounts")
    assert "400" in await run(finance, "recent transactions")  # exercises the GROUP BY / SUM queries
    await run(people, "add a friend roy who has a joyful nature")
    assert "roy" in (await run(people, "who is roy")).lower()
    await run(reminders, "remind me to call mom tomorrow 9 am")
    assert "call mom" in (await run(reminders, "show reminders")).lower()
    await run(calendar, "schedule design review tomorrow at 5 pm")
    assert "design review" in (await run(calendar, "show events")).lower()


async def test_full_stack_over_http_with_postgres(pg_dsn, pg):
    """build_runtime in one event loop, serve in another (what create_app does): the pool must reopen lazily."""
    from fastapi.testclient import TestClient

    from src.interfaces.websocket_api import create_api
    from src.main import build_runtime

    settings = Settings(llm_provider="mock", environment="local", database_url=pg_dsn, intent_classifier="heuristic",
                        sqlite_path=":memory:")
    runtime = await asyncio.to_thread(lambda: asyncio.run(build_runtime(settings)))  # separate loop, like create_app
    assert runtime.result_verifier is None and runtime.state_manager is None  # SQLite-only helpers are off

    app = create_api(runtime.orchestrator, settings, runtime.health_checker, runtime=runtime)
    with TestClient(app) as client:  # serves in yet another loop
        reply = client.post("/chat", json={"session_id": "pg-http", "message": "create account savings with 1000"})
        assert reply.status_code == 200 and reply.json()["response"], reply.text
        convs = client.get("/api/conversations").json()["conversations"]
        assert convs and convs[0]["session_id"] == "pg-http" and convs[0]["turns"] == 1 and convs[0]["updated"]
        assert client.get("/api/history", params={"session_id": "pg-http"}).json()["messages"][0]["role"] == "user"
        assert client.get("/api/briefing").status_code == 200
        assert client.get("/api/notifications").json() == {"notifications": []}
    assert (await pg.fetchone("SELECT COUNT(*) AS c FROM episodes WHERE session_id = 'pg-http'"))["c"] == 1
    assert (await pg.fetchone("SELECT balance FROM financial_accounts WHERE account_name ILIKE 'savings'"))["balance"] == 1000.0


# ── Web Push on Postgres ────────────────────────────────────────────
async def test_push_tables_exist_with_row_level_security(pg):
    rows = await pg.fetchall("SELECT relname, relrowsecurity FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relname IN ('app_settings','push_subscriptions')")
    assert {r["relname"] for r in rows} == {"app_settings", "push_subscriptions"} and all(r["relrowsecurity"] for r in rows)


async def test_push_keys_and_subscriptions_on_postgres(pg, settings):
    from tests.test_push import FakeSender, browser_subscription

    from src.agent.push import PushService

    sender = FakeSender()
    first, second = PushService(pg, settings, sender=sender), PushService(pg, settings, sender=sender)
    keys = await asyncio.gather(first.public_key(), second.public_key(), PushService(pg, settings, sender=sender).public_key())
    assert len(set(keys)) == 1                                                  # INSERT OR IGNORE -> ON CONFLICT DO NOTHING, race-safe
    assert (await pg.fetchone("SELECT COUNT(*) AS n FROM app_settings"))["n"] == 1

    sub, _, _ = browser_subscription()
    await first.subscribe(sub, "UA 1")
    await first.subscribe(sub, "UA 2")                                          # ON CONFLICT(endpoint) DO UPDATE
    assert await first.count() == 1 and (await pg.fetchone("SELECT user_agent FROM push_subscriptions"))["user_agent"] == "UA 2"
    for i in range(24):
        await first.subscribe(browser_subscription(f"https://fcm.googleapis.com/fcm/send/pgdev{i}")[0])
    assert await first.count() == 20                                            # LIMIT/OFFSET pruning works on Postgres too
    assert (await first.send({"title": "x", "body": "y"}))["sent"] == 20
    await first.unsubscribe(sub["endpoint"])


async def test_concurrent_schedulers_claim_each_reminder_once_on_postgres(pg, settings):
    from datetime import timedelta

    from tests.test_push import FakeSender, browser_subscription

    from src.agent.push import PushService
    from src.agent.service import ReminderScheduler

    sender = FakeSender()
    push = PushService(pg, settings, sender=sender)
    await push.subscribe(browser_subscription()[0])
    due = (timeutil.now(settings) - timedelta(minutes=2)).isoformat()
    for i in range(6):
        await pg.execute("INSERT INTO reminders (session_id, title, due_at, status, created_at) VALUES ('s', ?, ?, 'pending', 't')", (f"R{i}", due))
    results = await asyncio.gather(*(ReminderScheduler(pg, settings, push=push).tick() for _ in range(4)))   # four overlapping instances
    assert sum(results) == 6, results                                          # UPDATE ... RETURNING is a genuine atomic claim on Postgres
    assert (await pg.fetchone("SELECT COUNT(*) AS n FROM notifications"))["n"] == 6
    tags = [c["data"]["tag"] for c in sender.calls]
    assert len(tags) == len(set(tags))


# ── Home city (weather) on Postgres ─────────────────────────────────
async def test_home_city_upsert_and_briefing_on_postgres(pg, settings):
    import httpx

    from src.agent import weather
    from src.agent.skills.briefing import build_briefing
    from tests.test_weather import FakeOpenMeteo

    weather.clear_caches()
    api = FakeOpenMeteo()
    async with httpx.AsyncClient(transport=httpx.MockTransport(api)) as http:
        ctx = SkillContext(settings=settings.model_copy(update={"timezone": "Asia/Kolkata"}), store=pg, http=http, session_id="pg")
        registry = build_registry(ctx.settings)
        assert (await registry.execute("set_home_location", {"city": "Surat"}, ctx))[0]
        assert (await registry.execute("set_home_location", {"city": "Mumbai"}, ctx))[0]      # ON CONFLICT(id) DO UPDATE on a TEXT key
        assert (await pg.fetchone("SELECT COUNT(*) AS n FROM app_settings WHERE id = 'home_location'"))["n"] == 1
        data = await build_briefing(ctx)
        assert data["home_location"] == "Mumbai, Maharashtra, India" and data["weather"].startswith("Mumbai, Maharashtra, India: now")
    weather.clear_caches()


# ── Recurring reminders on Postgres ─────────────────────────────────
async def test_a_table_that_predates_the_recurrence_column_is_migrated(pg, pg_dsn):
    with psycopg.connect(pg_dsn, autocommit=True) as conn:
        conn.execute("ALTER TABLE reminders DROP COLUMN IF EXISTS recurrence")
    await pg.initialize()                                                      # what happens on the next deploy of an older database
    await pg.initialize()                                                      # idempotent
    await pg.execute("INSERT INTO reminders (session_id, title, due_at, status, created_at, recurrence) VALUES ('s','x','2030-01-01T09:00:00+00:00','pending','t','{}')")
    assert (await pg.fetchone("SELECT recurrence FROM reminders"))["recurrence"] == "{}"


async def test_overlapping_schedulers_advance_a_recurring_reminder_once_on_postgres(pg, settings):
    from datetime import timedelta

    from src.agent import recurrence
    from src.agent.service import ReminderScheduler
    from tests.test_recurring_reminders import Recorder

    due = timeutil.now(settings) - timedelta(minutes=1)
    for i in range(5):
        await pg.execute("INSERT INTO reminders (session_id, title, due_at, status, created_at, recurrence) VALUES ('s', ?, ?, 'pending', 't', ?)",
                         (f"R{i}", due.isoformat(), recurrence.Rule("daily").to_json()))
    rec = Recorder()
    results = await asyncio.gather(*(ReminderScheduler(pg, settings, push=rec).tick() for _ in range(4)))
    assert sum(results) == 5, results                                          # compare-and-swap on due_at is atomic across pooled connections
    assert sorted(r["title"] for batch in rec.batches for r in batch) == [f"R{i}" for i in range(5)]
    for row in await pg.fetchall("SELECT due_at, status FROM reminders"):
        gap = timeutil.parse_when(row["due_at"], settings) - timeutil.now(settings)
        assert row["status"] == "pending" and timedelta(hours=22) < gap < timedelta(hours=24, minutes=1)


# ── Expense tracker on Postgres ─────────────────────────────────────
async def test_expense_tracker_end_to_end_on_postgres(pg, settings):
    from datetime import timedelta

    from src.agent import expenses

    first = (timeutil.now(settings) + timedelta(days=12)).date().isoformat()
    bank = await expenses.create_bank(pg, "HDFC", "10000.50")
    assert bank["balance_minor"] == 1000050 and isinstance(bank["id"], int)
    with pytest.raises(expenses.ExpenseError):
        await expenses.create_bank(pg, "hdfc")                                              # LOWER(name) uniqueness
    pay = await expenses.create_payment(pg, settings, title="Car loan", total="1000.01", emis=3, first_due=first, bank_id=bank["id"])
    assert [e["amount_minor"] for e in pay["emis"]] == [33333, 33333, 33335]
    assert (await pg.fetchone("SELECT COUNT(*) AS n FROM reminders WHERE session_id = 'expenses' AND status = 'pending'"))["n"] == 3

    last = pay["emis"][2]["id"]
    await expenses.update_emi(pg, settings, last, paid=True, deduct=True)
    assert (await pg.fetchone("SELECT balance_minor FROM ex_banks"))["balance_minor"] == 1000050 - 33335
    await expenses.update_emi(pg, settings, last, paid=False)
    assert (await pg.fetchone("SELECT balance_minor FROM ex_banks"))["balance_minor"] == 1000050

    moved = await expenses.update_emi(pg, settings, pay["emis"][0]["id"], amount="400", due_date=(timeutil.now(settings) + timedelta(days=60)).date().isoformat())
    assert [e["seq"] for e in moved["emis"]] == [1, 2, 3] and moved["emis"][1]["amount_minor"] == 40000   # +60 days sorts between the 2nd and 3rd
    fixed = await expenses.rebalance(pg, settings, pay["id"])
    assert fixed["mismatch_minor"] == 0

    snap = await expenses.snapshot(pg, settings)
    assert snap["overview"]["remaining_minor"] == 100001 and snap["banks"][0]["name"] == "HDFC"
    assert "Car loan" in await expenses.export_csv(pg, settings)

    await expenses.delete_bank(pg, bank["id"])
    assert (await expenses.get_payment(pg, settings, pay["id"]))["bank_id"] is None
    await expenses.delete_payment(pg, pay["id"])
    assert (await pg.fetchone("SELECT COUNT(*) AS n FROM ex_emis"))["n"] == 0
    assert (await pg.fetchone("SELECT COUNT(*) AS n FROM reminders WHERE session_id = 'expenses' AND status = 'pending'"))["n"] == 0


async def test_expense_tables_have_row_level_security(pg):
    for table in ("ex_banks", "ex_payments", "ex_emis"):
        row = await pg.fetchone("SELECT relrowsecurity FROM pg_class WHERE relname = ?", (table,))
        assert row and row["relrowsecurity"] is True, table
