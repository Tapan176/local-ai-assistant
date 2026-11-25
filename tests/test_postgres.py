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


# ── Upgrading a database that already holds real data ───────────────────
async def test_upgrading_an_existing_database_keeps_every_payment_exactly_as_it_was(pg, pg_dsn, settings):
    """What happens on deploy: the tables are in last release's shape (no new columns or tables) and hold the user's data."""
    from src.agent import expenses

    with psycopg.connect(pg_dsn, autocommit=True) as conn:                               # recreate last release's shape
        conn.execute("ALTER TABLE ex_payments DROP COLUMN kind, DROP COLUMN grp, DROP COLUMN settled_at, DROP COLUMN open_paid_minor")
        conn.execute("ALTER TABLE ex_emis DROP COLUMN amount_custom")
        conn.execute("ALTER TABLE notes DROP COLUMN space, DROP COLUMN kind, DROP COLUMN pinned")
        conn.execute("ALTER TABLE tasks DROP COLUMN project, DROP COLUMN details, DROP COLUMN reminder_id, DROP COLUMN remind")
        conn.execute("DROP TABLE ex_spend, ex_subs")
        pay_cols = {r[0] for r in conn.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'ex_payments'")}
    assert "kind" not in pay_cols

    async def payment(title, amounts, paid_count, due_day):
        pid = await pg.execute(
            "INSERT INTO ex_payments (title, category, notes, total_minor, bank_id, due_day, remind_days, created_at, updated_at) VALUES (?, 'loan', 'keep me', ?, NULL, ?, 1, 't', 't')",
            (title, sum(amounts), due_day))
        for i, a in enumerate(amounts):
            await pg.execute("INSERT INTO ex_emis (payment_id, seq, amount_minor, due_date, paid_at, reminder_id) VALUES (?, ?, ?, ?, ?, ?)",
                             (pid, i + 1, a, f"2027-{(i % 12) + 1:02d}-{due_day:02d}", "2026-11-24T16:00:00+00:00" if i < paid_count else None, None))
        return pid

    loan_a = await payment("Loan A", [120000] * 23 + [85000], 2, 4)                          # last emi set lower by hand
    plan_b = await payment("Plan B", [60000] + [70000] * 10 + [69400], 1, 8)
    even = await payment("Plan C", [50000] * 24, 5, 8)
    await pg.execute("INSERT INTO notes (title, body, tags, created_at, updated_at) VALUES ('old note', 'body', 'a', 't', 't')")
    await pg.execute("INSERT INTO tasks (title, due_at, priority, status, created_at) VALUES ('old task', NULL, 'normal', 'open', 't')")
    snapshot_before = {
        "emis": await pg.fetchall("SELECT id, payment_id, seq, amount_minor, due_date, paid_at FROM ex_emis ORDER BY id"),
        "payments": await pg.fetchall("SELECT id, title, category, notes, total_minor, due_day, remind_days FROM ex_payments ORDER BY id"),
    }

    await pg.initialize()                                                                 # the deploy
    await pg.initialize()                                                                 # a second boot must change nothing either

    assert await pg.fetchall("SELECT id, payment_id, seq, amount_minor, due_date, paid_at FROM ex_emis ORDER BY id") == snapshot_before["emis"]
    assert await pg.fetchall("SELECT id, title, category, notes, total_minor, due_day, remind_days FROM ex_payments ORDER BY id") == snapshot_before["payments"]
    row = await pg.fetchone("SELECT kind, grp, settled_at, open_paid_minor FROM ex_payments WHERE id = ?", (loan_a,))
    assert row == {"kind": "emi", "grp": "", "settled_at": None, "open_paid_minor": 0}    # old rows get the defaults that mean "as before"
    assert (await pg.fetchone("SELECT space, kind, pinned FROM notes"))["space"] == "general"
    assert (await pg.fetchone("SELECT project, details FROM tasks"))["project"] == ""
    for table in ("ex_spend", "ex_subs"):
        assert (await pg.fetchone("SELECT relrowsecurity FROM pg_class WHERE relname = ?", (table,)))["relrowsecurity"] is True

    snap = await expenses.snapshot(pg, settings)                                           # first read: protect hand-set amounts
    flagged = {p["title"]: [e["seq"] for e in p["emis"] if e["custom"]] for p in snap["payments"]}
    assert flagged == {"Loan A": [24], "Plan B": [12], "Plan C": []}
    assert await pg.fetchall("SELECT id, amount_minor FROM ex_emis ORDER BY id") == [{"id": r["id"], "amount_minor": r["amount_minor"]} for r in snapshot_before["emis"]]

    spread = await expenses.rebalance(pg, settings, loan_a)                                  # the reported bug, on realistic shapes
    assert [e["amount_minor"] for e in spread["emis"]][-1] == 85000 and sum(e["amount_minor"] for e in spread["emis"]) == spread["total_minor"]
    assert {e["id"]: e["amount_minor"] for e in (await expenses.get_payment(pg, settings, even))["emis"]} == {r["id"]: r["amount_minor"] for r in snapshot_before["emis"] if r["payment_id"] == even}
    assert plan_b


async def test_spending_and_subscriptions_on_postgres(pg, settings):
    from datetime import timedelta

    from src.agent import spending

    day = timeutil.now(settings).date()
    await spending.add_spend(pg, settings, amount="100.50", category="food", spent_on=day.isoformat())
    await spending.add_spend(pg, settings, amount="49.50", category="travel", spent_on=day.isoformat())
    summary = await spending.month_summary(pg, settings)
    assert summary["total_minor"] == 15000 and isinstance(summary["total_minor"], int)      # SUM(bigint) is a Decimal in Postgres: must be an int
    assert [c["amount_minor"] for c in summary["categories"]] == [10050, 4950] and all(isinstance(c["amount_minor"], int) for c in summary["categories"])
    assert isinstance(summary["previous_total_minor"], int) and summary["by_day"][0]["amount_minor"] == 15000
    assert await spending.set_budget(pg, 500) == 50000 and (await spending.month_summary(pg, settings))["budget_left_minor"] == 35000

    sub = await spending.create_sub(pg, settings, name="Netflix", amount=649, next_date=(day + timedelta(days=5)).isoformat())
    renewed = await spending.renew_sub(pg, settings, sub["id"])
    assert renewed["next_date"] > sub["next_date"]
    assert (await pg.fetchone("SELECT COUNT(*) AS n FROM reminders WHERE session_id = 'expenses' AND status = 'pending'"))["n"] == 1
    await spending.delete_sub(pg, sub["id"])
    assert (await pg.fetchone("SELECT COUNT(*) AS n FROM reminders WHERE status = 'pending'"))["n"] == 0
    assert "100.50" in await spending.export_spend_csv(pg)


async def test_new_expense_tables_have_row_level_security(pg):
    for table in ("ex_spend", "ex_subs"):
        row = await pg.fetchone("SELECT relrowsecurity FROM pg_class WHERE relname = ?", (table,))
        assert row and row["relrowsecurity"] is True, table


async def test_work_and_growth_on_postgres(pg, settings):
    from datetime import timedelta

    from src.agent import workspace

    due = (timeutil.now(settings) + timedelta(days=5)).date().isoformat()
    t = await workspace.create_task(pg, settings, title="Hit 100% of target", project="Sales", priority="high", due=due, remind="morning")
    await workspace.create_task(pg, settings, title="snake_case rename", project="Code")
    assert [x["title"] for x in await workspace.list_tasks(pg, settings, q="100%")] == ["Hit 100% of target"]        # ESCAPE works the same in Postgres
    assert [x["title"] for x in await workspace.list_tasks(pg, settings, q="_")] == ["snake_case rename"]
    assert [x["title"] for x in await workspace.list_tasks(pg, settings)][0] == "Hit 100% of target"                 # high priority first, undated last
    live = await pg.fetchall("SELECT title FROM reminders WHERE session_id = 'work' AND status = 'pending'")
    assert [r["title"] for r in live] == ["Task · Hit 100% of target · Sales"]
    await workspace.set_task_done(pg, settings, t["id"], True)
    assert (await pg.fetchone("SELECT COUNT(*) AS n FROM reminders WHERE session_id = 'work' AND status = 'pending'"))["n"] == 0
    ov = await workspace.work_overview(pg, settings)
    assert ov["open"] == 1 and ov["done_7d"] == 1 and isinstance(ov["open"], int)

    r1 = await workspace.create_note(pg, space="growth", kind="rule", body="Never decide angry", tags="calm,sleep")
    r2 = await workspace.create_note(pg, space="growth", kind="rule", body="Sleep on big decisions", tags="calm")
    await workspace.create_note(pg, space="growth", kind="lesson", body="Ask early", tags="work")
    assert [n["id"] for n in await workspace.list_notes(pg, "growth", "rule")] == [r1["id"], r2["id"]]
    assert [n["id"] for n in await workspace.list_notes(pg, "growth", tag="calm")] == [r2["id"], r1["id"]]
    assert await workspace.list_notes(pg, "growth", tag="cal") == []                                                  # whole-tag match via string concatenation
    await workspace.update_note(pg, r2["id"], pinned=True)
    assert (await workspace.list_notes(pg, "growth"))[0]["id"] == r2["id"] and (await workspace.todays_pick(pg, settings))["id"] == r2["id"]
    ov = await workspace.growth_overview(pg, settings)
    assert ov["total"] == 3 and ov["tags"][0] == {"tag": "calm", "count": 2}


async def test_the_tasks_table_gained_its_new_columns_with_defaults(pg):
    cols = {r["column_name"] for r in await pg.fetchall("SELECT column_name FROM information_schema.columns WHERE table_name = 'tasks'")}
    assert {"project", "details", "reminder_id", "remind"} <= cols


# ── Batched transactions: correctness, safety and speed ─────────────────
async def test_a_batched_transaction_returns_the_new_ids_in_order(pg):
    ids = await pg.execute_transaction([
        ("INSERT INTO people (name, relationship, notes, updated_at) VALUES (?, ?, ?, ?)", ("A", "r", "", "t")),
        ("UPDATE people SET notes = ? WHERE name = ?", ("changed", "A")),
        ("INSERT INTO people (name, relationship, notes, updated_at) VALUES (?, ?, ?, ?)", ("B", "r", "", "t")),
        ("DELETE FROM people WHERE name = ?", ("nobody",)),
        ("INSERT INTO people (name, relationship, notes, updated_at) VALUES (?, ?, ?, ?)", ("C", "r", "", "t")),
    ])
    rows = {r["name"]: r["id"] for r in await pg.fetchall("SELECT id, name FROM people")}
    assert ids == [rows["A"], 0, rows["B"], 0, rows["C"]] and ids[0] < ids[2] < ids[4]
    assert (await pg.fetchone("SELECT notes FROM people WHERE name = 'A'"))["notes"] == "changed"
    assert await pg.execute_transaction([]) == []
    single = await pg.execute_transaction([("INSERT INTO people (name, relationship, notes, updated_at) VALUES (?, ?, ?, ?)", ("D", "r", "", "t"))])
    assert single == [(await pg.fetchone("SELECT id FROM people WHERE name = 'D'"))["id"]]


NASTY = ["", "plain", "it's", 'say "hi"', "back\\slash", "100%", "50% off %s %%", "line1\nline2\r\nline3", "tab\there", "ünïcödé ₹ 日本語 😀",
         "'); DROP TABLE people; --", "\\'; DROP TABLE people; --", "$$ dollar $$", "semi;colon; and -- comment", "x" * 5000, "  spaces  "]


async def test_batched_values_round_trip_exactly_and_cannot_inject_sql(pg):
    ops = [("INSERT INTO people (name, relationship, notes, updated_at) VALUES (?, ?, ?, ?)", (f"n{i}", "r", value, "t")) for i, value in enumerate(NASTY)]
    ops.append(("INSERT INTO ex_banks (name, balance_minor, note, created_at, updated_at) VALUES (?, ?, ?, ?, ?)", ("Bank", 99_999_999_999, "n", "t", "t")))
    ops.append(("INSERT INTO reminders (session_id, title, due_at, status, created_at) VALUES (?, ?, ?, 'pending', ?)", ("s", "undated", None, "t")))   # a NULL value
    await pg.execute_transaction(ops)
    stored = {r["name"]: r["notes"] for r in await pg.fetchall("SELECT name, notes FROM people")}
    assert [stored[f"n{i}"] for i in range(len(NASTY))] == NASTY                      # byte for byte, including the injection attempts
    assert (await pg.fetchone("SELECT COUNT(*) AS n FROM people"))["n"] == len(NASTY)  # the table still exists and nothing extra ran
    assert (await pg.fetchone("SELECT balance_minor FROM ex_banks"))["balance_minor"] == 99_999_999_999          # big integers survive
    assert (await pg.fetchone("SELECT due_at FROM reminders WHERE title = 'undated'"))["due_at"] is None         # and so does NULL


async def test_a_failing_statement_rolls_the_whole_batch_back_and_the_pool_recovers(pg):
    await pg.execute("INSERT INTO people (name, relationship, notes, updated_at) VALUES (?, ?, ?, ?)", ("dup", "r", "", "t"))
    with pytest.raises(Exception):
        await pg.execute_transaction([
            ("INSERT INTO people (name, relationship, notes, updated_at) VALUES (?, ?, ?, ?)", ("first", "r", "", "t")),
            ("INSERT INTO people (name, relationship, notes, updated_at) VALUES (?, ?, ?, ?)", ("dup", "r", "", "t")),       # violates UNIQUE(name)
            ("INSERT INTO people (name, relationship, notes, updated_at) VALUES (?, ?, ?, ?)", ("third", "r", "", "t")),
        ])
    assert [r["name"] for r in await pg.fetchall("SELECT name FROM people ORDER BY name")] == ["dup"]               # nothing from the batch survived
    assert await pg.execute("INSERT INTO people (name, relationship, notes, updated_at) VALUES (?, ?, ?, ?)", ("after", "r", "", "t"))
    assert len(await asyncio.gather(*(pg.fetchone("SELECT 1 AS x") for _ in range(8)))) == 8                      # every pooled connection is still usable


async def test_batched_and_statement_by_statement_transactions_end_in_the_same_state(pg, monkeypatch):
    ops = [("INSERT INTO people (name, relationship, notes, updated_at) VALUES (?, ?, ?, ?)", (f"p{i}", "r", f"o'{i}", "t")) for i in range(12)]
    ops += [("UPDATE people SET relationship = ? WHERE name = ?", ("changed", f"p{i}")) for i in range(0, 12, 3)]
    await pg.execute_transaction(ops)
    batched = await pg.fetchall("SELECT name, relationship, notes FROM people ORDER BY name")
    await pg.execute("DELETE FROM people")
    monkeypatch.setattr(PostgresStore, "BATCH", False)
    await pg.execute_transaction(ops)
    assert await pg.fetchall("SELECT name, relationship, notes FROM people ORDER BY name") == batched


@pytest.fixture
async def lagged(pg_dsn):
    """A store whose every network hop costs 20 ms each way (40 ms round trip), like a database in another region."""
    from tests.latency_proxy import LatencyProxy

    direct = PostgresStore(pg_dsn)
    await direct.initialize()
    with psycopg.connect(pg_dsn, autocommit=True) as conn:
        tables = [r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")]
        conn.execute("TRUNCATE " + ", ".join(tables) + " RESTART IDENTITY")
    await direct.initialize()
    async with LatencyProxy(pg_dsn, 0.02) as proxy:
        store = PostgresStore(proxy.dsn)
        for _ in range(3):                                                           # warm the pool, as a running server is
            await asyncio.gather(*(store.fetchone("SELECT 1 AS x") for _ in range(4)))
        store.rtt = proxy.rtt
        yield store
        await store.aclose()
    await direct.aclose()


async def test_a_batch_costs_about_one_round_trip_however_many_statements(lagged, monkeypatch):
    import time as _t

    ops = [("INSERT INTO people (name, relationship, notes, updated_at) VALUES (?, ?, ?, ?)", (f"x{i}", "r", "", "t")) for i in range(30)]
    t0 = _t.perf_counter()
    await lagged.execute_transaction(ops)
    batched = _t.perf_counter() - t0
    await lagged.execute("DELETE FROM people")
    monkeypatch.setattr(PostgresStore, "BATCH", False)
    t1 = _t.perf_counter()
    await lagged.execute_transaction(ops)
    plain = _t.perf_counter() - t1
    assert batched < 4 * lagged.rtt + 0.15, (batched, lagged.rtt)                       # ~1 hop + a little work
    assert plain > 20 * lagged.rtt and batched < plain / 5, (batched, plain)            # the old way paid for every statement


async def test_money_operations_stay_within_a_round_trip_budget(lagged, settings):
    """Every write on the Money screen is a handful of hops. If a change brings back a query per EMI, these fail."""
    import time as _t
    from datetime import timedelta

    from src.agent import expenses, spending

    rtt = lagged.rtt

    async def took(coro):
        t0 = _t.perf_counter()
        out = await coro
        return out, _t.perf_counter() - t0

    def within(seconds, hops):
        assert seconds < hops * rtt + 0.35, f"{seconds:.2f}s is more than {hops} round trips of {rtt * 1000:.0f} ms (+0.35 s of work)"

    first = (timeutil.now(settings) + timedelta(days=5)).date().isoformat()
    pay, s = await took(expenses.create_payment(lagged, settings, title="Car", total=240000, emis=24, first_due=first))
    within(s, 16)                                                                          # was ~73 hops
    assert pay["emi_count"] == 24 and (await lagged.fetchone("SELECT COUNT(*) AS n FROM reminders WHERE session_id = 'expenses' AND status = 'pending'"))["n"] == 12
    _, s = await took(asyncio.gather(expenses.snapshot(lagged, settings), spending.card(lagged, settings)))
    within(s, 6)
    _, s = await took(expenses.update_emi(lagged, settings, pay["emis"][0]["id"], paid=True))
    within(s, 10)                                                                          # was ~18
    _, s = await took(expenses.update_emi(lagged, settings, pay["emis"][1]["id"], amount=5000))
    within(s, 10)
    pay2, s = await took(expenses.rebalance(lagged, settings, pay["id"]))
    within(s, 12)                                                                          # was ~74
    assert sum(e["amount_minor"] for e in pay2["emis"]) == pay2["total_minor"]
    res, s = await took(expenses.set_emis_paid(lagged, settings, [e["id"] for e in pay["emis"][2:12]], paid=True))
    within(s, 10)                                                                          # ten EMIs, was ~90+
    assert res["changed"] == 10
    assert (await lagged.fetchone("SELECT COUNT(*) AS n FROM reminders WHERE session_id = 'expenses' AND status = 'pending'"))["n"] == 12   # the window rolled forward
    _, s = await took(spending.add_spend(lagged, settings, amount=100))
    within(s, 5)
    _, s = await took(expenses.delete_payment(lagged, pay["id"]))
    within(s, 5)                                                                           # was ~21
    assert (await lagged.fetchone("SELECT COUNT(*) AS n FROM reminders WHERE session_id = 'expenses' AND status = 'pending'"))["n"] == 0


async def test_a_pooler_that_refuses_batches_makes_the_store_fall_back_without_losing_the_write(pg, monkeypatch):
    calls = {"script": 0}

    async def refuse(self, operations):
        calls["script"] += 1
        raise psycopg.errors.FeatureNotSupported("simulated pooler")

    monkeypatch.setattr(PostgresStore, "_transaction_script", refuse)
    monkeypatch.setattr(PostgresStore, "BATCH", True)
    ops = [("INSERT INTO people (name, relationship, notes, updated_at) VALUES (?, ?, ?, ?)", (f"f{i}", "r", "", "t")) for i in range(3)]
    ids = await pg.execute_transaction(ops)
    assert len(ids) == 3 and all(ids) and (await pg.fetchone("SELECT COUNT(*) AS n FROM people"))["n"] == 3     # the write still happened, exactly once
    assert PostgresStore.BATCH is False                                                                        # and the store stopped trying
    await pg.execute_transaction([("DELETE FROM people WHERE name = ?", ("f0",)), ("DELETE FROM people WHERE name = ?", ("f1",))])
    assert calls["script"] == 1 and (await pg.fetchone("SELECT COUNT(*) AS n FROM people"))["n"] == 1


async def test_the_daily_picture_cap_is_exact_on_postgres_even_under_concurrency(pg, settings):
    from src.agent import vision

    capped = settings.model_copy(update={"vision_daily_limit": 5})
    results = await asyncio.gather(*(vision.take_budget(pg, capped) for _ in range(12)), return_exceptions=True)
    assert sum(1 for r in results if r is None) == 5 and sum(1 for r in results if isinstance(r, vision.VisionError)) == 7
    key = [r["id"] for r in await pg.fetchall("SELECT id FROM app_settings WHERE id LIKE 'vision:%'")]
    assert len(key) == 1 and (await pg.fetchone("SELECT value FROM app_settings WHERE id = ?", (key[0],)))["value"] == "12"


async def test_graph_memory_works_the_same_on_postgres(pg):
    from src.agent import graph

    await graph.link(pg, "Zorya", "works at", "Quillon Labs", "person", "org", note="since 2020")
    await graph.link(pg, "zorya", "WORKS AT", "quillon labs")                       # same edge, no duplicate, note kept
    await graph.link(pg, "Quillon Labs", "is based in", "Lisbon", "org", "place")
    await graph.link(pg, "Zorya", "sister of", "me")                                # 'me' is the single 'the user' node
    await graph.link(pg, "Marek", "mentor of", "the user")
    await graph.upsert_node(pg, "Zorya", summary="college friend")
    block = await graph.context_block(pg, "what should I tell zorya?")
    assert "Zorya (person): college friend" in block and "works at → Quillon Labs (since 2020)" in block and "Lisbon" in block and "Marek" not in block
    assert (await pg.fetchone("SELECT COUNT(*) AS n FROM kg_edges"))["n"] == 4
    assert [n["name"] for n in (await graph.overview(pg, "quil"))["nodes"]] == ["Quillon Labs"]
    assert [n["name"] for n in (await graph.overview(pg, "_"))["nodes"]] == []
    got = await graph.connections(pg, "Quillon Labs")
    assert got["connections"] and got["kind"] == "org"
    node = await graph.find_node(pg, "quillon labs")
    assert await graph.forget_node(pg, node["id"]) == "Quillon Labs"
    assert "Quillon" not in await graph.context_block(pg, "zorya")
    assert (await pg.fetchone("SELECT COUNT(*) AS n FROM kg_edges"))["n"] == 2
