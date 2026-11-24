"""Recurring reminders through the real skills, scheduler and storage (SQLite here; Postgres in test_postgres.py)."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from src.agent import recurrence, timeutil
from src.agent.service import ReminderScheduler
from src.agent.skill import SkillContext
from src.agent.skills import build_registry
from src.agent.skills.briefing import build_briefing
from src.config.settings import Settings
from src.storage.sqlite_store import SQLiteStore


@pytest.fixture
def settings():
    return Settings(llm_provider="mock", environment="local", sqlite_path=":memory:", timezone="Asia/Kolkata")


@pytest.fixture
async def store():
    s = SQLiteStore(":memory:")
    await s.initialize()
    return s


@pytest.fixture
async def ctx(settings, store):
    async with httpx.AsyncClient() as http:
        yield SkillContext(settings=settings, store=store, http=http, session_id="t")


class Recorder:
    def __init__(self):
        self.batches = []

    async def notify_reminders(self, rows, now):
        self.batches.append([dict(r) for r in rows])
        return {"sent": len(rows)}


async def run(settings, ctx, name, **args):
    return await build_registry(settings).execute(name, args, ctx)


def iso(settings, **delta):
    return (timeutil.now(settings) + timedelta(**delta)).replace(microsecond=0).isoformat()


async def rows(store):
    return await store.fetchall("SELECT id, title, due_at, status, recurrence FROM reminders ORDER BY id")


# ── skills ──────────────────────────────────────────────────────────
async def test_a_daily_reminder_is_one_row_with_a_rule(settings, ctx, store):
    ok, text = await run(settings, ctx, "set_reminder", title="Take vitamins", when=iso(settings, days=1), repeat="daily")
    assert ok and "repeats every day" in text and "Take vitamins" in text
    [row] = await rows(store)
    assert recurrence.Rule.from_json(row["recurrence"]) == recurrence.Rule("daily") and row["status"] == "pending"


async def test_weekly_on_chosen_days_and_defaults(settings, ctx, store):
    await run(settings, ctx, "set_reminder", title="Gym", when=iso(settings, days=1), repeat="weekly", days=["mon", "thu"])
    await run(settings, ctx, "set_reminder", title="Review", when=iso(settings, days=2), repeat="weekly", every=2)
    gym, review = await rows(store)
    assert recurrence.Rule.from_json(gym["recurrence"]).days == (0, 3)
    r = recurrence.Rule.from_json(review["recurrence"])
    assert r.every == 2 and r.days == (timeutil.parse_when(review["due_at"], settings).weekday(),)       # defaults to the first day's weekday


async def test_monthly_remembers_the_anchor_day(settings, ctx, store):
    await run(settings, ctx, "set_reminder", title="Rent", when=(timeutil.now(settings) + timedelta(days=40)).replace(day=28).isoformat(), repeat="monthly")
    rule = recurrence.Rule.from_json((await rows(store))[0]["recurrence"])
    assert rule.repeat == "monthly" and rule.day == 28


@pytest.mark.parametrize("kwargs,message", [({"repeat": "hourly"}, "Unsupported repeat"), ({"repeat": "daily", "every": 0}, "between 1"),
                                            ({"repeat": "weekly", "days": ["blursday"]}, "weekday"), ({"repeat": "daily", "days": ["mon"]}, "only applies to weekly")])
async def test_bad_recurrence_is_explained_and_nothing_is_saved(settings, ctx, store, kwargs, message):
    ok, text = await run(settings, ctx, "set_reminder", title="x", when=iso(settings, days=1), **kwargs)
    assert message in text and await rows(store) == []


async def test_one_off_reminders_are_unchanged(settings, ctx, store):
    ok, text = await run(settings, ctx, "set_reminder", title="Dentist", when=iso(settings, days=1))
    assert "repeats" not in text and (await rows(store))[0]["recurrence"] is None
    for none in ("none", "once", ""):
        await run(settings, ctx, "set_reminder", title=f"x{none}", when=iso(settings, days=2), repeat=none)
    assert all(r["recurrence"] is None for r in await rows(store))


async def test_batch_mixes_one_off_and_recurring_and_reports_bad_rules(settings, ctx, store):
    items = [{"title": "Standup", "when": iso(settings, days=1), "repeat": "weekdays"}, {"title": "Dentist", "when": iso(settings, days=3)},
             {"title": "Broken", "when": iso(settings, days=2), "repeat": "fortnightly"}, {"title": "Bills", "when": iso(settings, days=5), "repeat": "monthly", "every": 2}]
    ok, text = await run(settings, ctx, "set_reminders", reminders=items)
    data = json.loads(text)
    assert [c["title"] for c in data["created"]] == ["Standup", "Dentist", "Bills"]
    assert data["created"][0]["repeats"] == "every weekday" and "repeats" not in data["created"][1] and data["created"][2]["repeats"].startswith("every 2 months")
    assert data["skipped"] == [{"item": "Broken", "reason": "Unsupported repeat “fortnightly”. Use one of: daily, weekdays, weekly, monthly, yearly."}]
    assert len(await rows(store)) == 3


async def test_listing_shows_words_not_raw_json_and_cancel_ends_the_series(settings, ctx, store):
    await run(settings, ctx, "set_reminder", title="Water plants", when=iso(settings, days=1), repeat="weekly", days=["sat"])
    ok, text = await run(settings, ctx, "list_reminders")
    listed = json.loads(text)
    assert listed[0]["repeats"] == "every week on Sat" and "recurrence" not in listed[0]
    ok, msg = await run(settings, ctx, "cancel_reminder", id=listed[0]["id"])
    assert "stops completely" in msg and (await rows(store))[0]["status"] == "cancelled"
    assert (await run(settings, ctx, "list_reminders"))[1] == "No pending reminders."


async def test_the_briefing_carries_the_repeat_text(settings, ctx):
    await run(settings, ctx, "set_reminder", title="Stretch", when=iso(settings, hours=3), repeat="daily")
    data = await build_briefing(ctx)
    flat = data["reminders_today"] + data["upcoming_reminders"]
    assert flat and flat[0]["repeats"] == "every day" and "recurrence" not in flat[0]


# ── scheduler ───────────────────────────────────────────────────────
async def _recurring(store, settings, title="Vitamins", due_delta=timedelta(minutes=-1), rule=None):
    due = timeutil.now(settings) + due_delta
    rule = rule or recurrence.Rule("daily")
    rid = await store.execute("INSERT INTO reminders (session_id, title, due_at, status, created_at, recurrence) VALUES ('s', ?, ?, 'pending', 't', ?)",
                              (title, due.isoformat(), rule.to_json()))
    return rid, due


async def test_a_daily_reminder_fires_then_moves_to_tomorrow(settings, store):
    rid, due = await _recurring(store, settings)
    rec = Recorder()
    scheduler = ReminderScheduler(store, settings, push=rec)
    assert await scheduler.tick() == 1
    row = (await rows(store))[0]
    assert row["status"] == "pending"                                                     # still alive
    nxt = timeutil.parse_when(row["due_at"], settings)
    assert nxt == due + timedelta(days=1) and nxt > timeutil.now(settings)
    assert await scheduler.tick() == 0 and len(rec.batches) == 1                          # not again until tomorrow
    assert rec.batches[0][0]["due"] == due and (await store.fetchone("SELECT COUNT(*) AS n FROM notifications"))["n"] == 1


async def test_after_days_of_downtime_it_fires_once_for_the_latest_day(settings, store):
    rid, due = await _recurring(store, settings, due_delta=timedelta(days=-5, minutes=-1))
    rec = Recorder()
    assert await ReminderScheduler(store, settings, push=rec).tick() == 1
    assert rec.batches[0][0]["due"] == due + timedelta(days=5)                            # latest missed occurrence, not the oldest
    assert timeutil.parse_when((await rows(store))[0]["due_at"], settings) > timeutil.now(settings)
    assert (await store.fetchone("SELECT COUNT(*) AS n FROM notifications"))["n"] == 1


async def test_overlapping_instances_advance_and_notify_exactly_once(settings, store):
    """During a Render deploy the old and new instance both poll the same database."""
    for i in range(5):
        await _recurring(store, settings, title=f"R{i}", due_delta=timedelta(minutes=-1))
    rec = Recorder()
    results = await asyncio.gather(*(ReminderScheduler(store, settings, push=rec).tick() for _ in range(4)))
    assert sum(results) == 5, results
    fired = [r["title"] for batch in rec.batches for r in batch]
    assert sorted(fired) == [f"R{i}" for i in range(5)]                                   # each exactly once
    for row in await rows(store):                                                          # advanced ONCE: a second advance would skip a whole day
        gap = timeutil.parse_when(row["due_at"], settings) - timeutil.now(settings)
        assert timedelta(hours=22) < gap < timedelta(hours=24, minutes=1), gap


async def test_a_corrupt_rule_degrades_to_a_one_off_instead_of_looping(settings, store):
    due = (timeutil.now(settings) - timedelta(minutes=1)).isoformat()
    await store.execute("INSERT INTO reminders (session_id, title, due_at, status, created_at, recurrence) VALUES ('s','Odd',?, 'pending','t','{broken')", (due,))
    await store.execute("INSERT INTO reminders (session_id, title, due_at, status, created_at, recurrence) VALUES ('s','Odder',?, 'pending','t',?)",
                        (due, json.dumps({"repeat": "fortnightly", "every": 1})))
    assert await ReminderScheduler(store, settings).tick() == 2
    assert {r["status"] for r in await rows(store)} == {"fired"}
    assert await ReminderScheduler(store, settings).tick() == 0


async def test_a_cancelled_series_stops(settings, store):
    rid, _ = await _recurring(store, settings)
    await store.execute("UPDATE reminders SET status = 'cancelled' WHERE id = ?", (rid,))
    assert await ReminderScheduler(store, settings).tick() == 0


async def test_monthly_on_the_31st_over_real_ticks(settings, store, monkeypatch):
    """Simulated clock: Jan 31 -> Feb 28 -> Mar 31, through the scheduler itself."""
    tz = timeutil.get_tz(settings)
    clock = {"now": datetime(2026, 1, 31, 9, 0, 30, tzinfo=tz)}
    monkeypatch.setattr(timeutil, "now", lambda s: clock["now"])
    rule = recurrence.build_rule("monthly", 1, None, anchor=datetime(2026, 1, 31, 9, 0, tzinfo=tz))
    await store.execute("INSERT INTO reminders (session_id, title, due_at, status, created_at, recurrence) VALUES ('s','Rent',?, 'pending','t',?)",
                        (datetime(2026, 1, 31, 9, 0, tzinfo=tz).isoformat(), rule.to_json()))
    rec, scheduler, seen = Recorder(), ReminderScheduler(store, settings, push=None), []
    scheduler.push = rec
    for when in (datetime(2026, 1, 31, 9, 0, 30, tzinfo=tz), datetime(2026, 2, 28, 9, 1, tzinfo=tz), datetime(2026, 3, 31, 9, 1, tzinfo=tz), datetime(2026, 4, 30, 9, 1, tzinfo=tz)):
        clock["now"] = when
        assert await scheduler.tick() == 1
        seen.append(rec.batches[-1][0]["due"].date().isoformat())
    assert seen == ["2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30"]


async def test_snooze_of_a_recurring_reminder_leaves_the_series_alone(settings, store):
    from src.agent import actions

    rid, due = await _recurring(store, settings, title="Vitamins")
    await ReminderScheduler(store, settings).tick()
    series_due = (await rows(store))[0]["due_at"]
    result = await actions.snooze(store, settings, rid, 10)
    assert result["title"] == "Vitamins"
    all_rows = await rows(store)
    assert len(all_rows) == 2 and all_rows[0]["due_at"] == series_due and all_rows[0]["recurrence"] and all_rows[1]["recurrence"] is None


# ── migration of an existing database ───────────────────────────────
async def test_an_old_database_without_the_column_is_migrated_in_place(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript("CREATE TABLE reminders (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, title TEXT NOT NULL, due_at TEXT, status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL);"
                       "INSERT INTO reminders (session_id, title, due_at, status, created_at) VALUES ('s','Old reminder','2030-01-01T09:00:00+00:00','pending','t');")
    conn.commit(); conn.close()
    store = SQLiteStore(str(path))
    await store.initialize()
    await store.initialize()                                                              # idempotent
    row = await store.fetchone("SELECT title, recurrence FROM reminders")
    assert row == {"title": "Old reminder", "recurrence": None}
    await store.execute("INSERT INTO reminders (session_id, title, due_at, status, created_at, recurrence) VALUES ('s','New','2030-01-02T09:00:00+00:00','pending','t','{}')")
