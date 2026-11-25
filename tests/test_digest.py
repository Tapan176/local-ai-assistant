"""Daily briefing push: built from data by fixed rules, due once a day inside a window, delivered to every channel, off by default.
All names and amounts are invented."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from src.agent import digest, expenses, timeutil, workspace
from src.agent.expenses import ExpenseError
from src.agent.notifier import Notifier
from src.agent.service import ReminderScheduler
from src.config.settings import Settings
from src.storage.sqlite_store import SQLiteStore

TZ = ZoneInfo("Asia/Kolkata")


@pytest.fixture
def settings():
    return Settings(llm_provider="mock", environment="local", sqlite_path=":memory:", timezone="Asia/Kolkata", currency="INR")


@pytest.fixture
async def store():
    s = SQLiteStore(":memory:")
    await s.initialize()
    return s


def day(settings, n: int) -> str:
    return (timeutil.now(settings).date() + timedelta(days=n)).isoformat()


class Recorder:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    async def notify_digest(self, title, body):
        self.sent.append((title, body))
        return {"push": {"sent": 1, "removed": 0, "failed": 0}}

    async def notify_reminders(self, rows, now):
        return {}


# ── configuration ──────────────────────────────────────────────────────
async def test_it_is_off_until_switched_on_and_validates_the_time(store):
    assert await digest.get_config(store) == {"enabled": False, "time": "08:00"}
    assert await digest.set_config(store, True, "07:30") == {"enabled": True, "time": "07:30"}
    assert await digest.get_config(store) == {"enabled": True, "time": "07:30"}
    for bad in ("", "8:00", "25:00", "07:60", "7am", "07:30:00"):
        with pytest.raises(ExpenseError, match="hours and minutes"):
            await digest.set_config(store, True, bad)
    assert await digest.get_config(store) == {"enabled": True, "time": "07:30"}                     # a refused save changes nothing


async def test_a_damaged_setting_falls_back_to_off(store):
    await store.execute("INSERT INTO app_settings (id, value, updated_at) VALUES (?, 'not json', 'x')", (digest.CONFIG_KEY,))
    assert await digest.get_config(store) == {"enabled": False, "time": "08:00"}
    await store.execute("UPDATE app_settings SET value = ? WHERE id = ?", ('{"enabled": true, "time": "99:99"}', digest.CONFIG_KEY))
    assert await digest.get_config(store) == {"enabled": True, "time": "08:00"}


# ── when is it due ─────────────────────────────────────────────────────
@pytest.mark.parametrize("clock,expected", [("07:59", False), ("08:00", True), ("09:30", True), ("12:00", True), ("12:01", False), ("20:00", False)])
def test_due_only_from_the_set_time_until_four_hours_later(clock, expected):
    hh, mm = clock.split(":")
    now = datetime(2026, 11, 25, int(hh), int(mm), tzinfo=TZ)
    assert digest.due({"enabled": True, "time": "08:00"}, now) is expected
    assert digest.due({"enabled": False, "time": "08:00"}, now) is False


async def test_a_day_is_claimed_once_even_when_instances_race(store):
    results = await asyncio.gather(*(digest.claim_today(store, "2026-11-25") for _ in range(6)))
    assert results.count(True) == 1
    assert await digest.claim_today(store, "2026-11-25") is False
    assert await digest.claim_today(store, "2026-11-26") is True                                     # a new day is a new claim


# ── what it says ───────────────────────────────────────────────────────
async def test_empty_data_still_says_something_short(store, settings):
    title, body = await digest.compose(store, settings)
    assert title.startswith("Good morning") and body == "Nothing due today. Enjoy the day."


async def test_it_reports_overdue_today_and_soon_for_payments_and_tasks(store, settings):
    await expenses.create_payment(store, settings, title="Sofa loan", emis=3, emi_amount=2500, first_due=day(settings, -40))      # first two overdue
    await expenses.create_payment(store, settings, title="Card bill", kind="due", emi_amount=1200, total=1200, first_due=day(settings, 0))
    await expenses.create_payment(store, settings, title="Gym", kind="due", emi_amount=800, total=800, first_due=day(settings, 2))
    await expenses.create_payment(store, settings, title="Far away", kind="due", emi_amount=999, total=999, first_due=day(settings, 20))
    await workspace.create_task(store, settings, title="File the report", due=day(settings, -1))
    await workspace.create_task(store, settings, title="Call the vendor", due=day(settings, 0))
    await workspace.create_task(store, settings, title="Someday", due=day(settings, 9))
    _, body = await digest.compose(store, settings)
    lines = body.splitlines()
    assert lines[0].startswith("Overdue: ") and "Sofa loan" in lines[0]
    assert any(ln.startswith("Due today: ₹1,200") and "Card bill" in ln for ln in lines)
    assert any(ln.startswith("Next 3 days: 1 payment, ₹800") for ln in lines)
    assert "File the report" in body and "Call the vendor" in body
    assert "Far away" not in body and "Someday" not in body


async def test_long_lists_are_shortened(store, settings):
    for i in range(6):
        await workspace.create_task(store, settings, title=f"Late task {i}", due=day(settings, -1))
    _, body = await digest.compose(store, settings)
    assert "and 3 more" in body


# ── sending ────────────────────────────────────────────────────────────
async def test_delivery_goes_to_the_channels_and_to_the_open_app(store, settings):
    rec = Recorder()
    out = await digest.deliver(store, settings, rec)
    assert rec.sent and out["delivery"]["push"]["sent"] == 1
    row = await store.fetchone("SELECT kind, title, body FROM notifications WHERE kind = 'digest'")
    assert row and row["title"].startswith("Good morning")


async def test_send_if_due_sends_once_per_day_and_never_when_off(store, settings, monkeypatch):
    rec = Recorder()
    cfg_on = {"enabled": True, "time": "08:00"}
    at = datetime(2026, 11, 25, 9, 0, tzinfo=TZ)
    monkeypatch.setattr(timeutil, "now", lambda s: at)
    assert await digest.send_if_due(store, settings, rec, {"enabled": False, "time": "08:00"}) is False
    assert await digest.send_if_due(store, settings, rec, cfg_on) is True
    assert await digest.send_if_due(store, settings, rec, cfg_on) is False                           # the second tick the same day does nothing
    assert len(rec.sent) == 1
    monkeypatch.setattr(timeutil, "now", lambda s: at + timedelta(days=1))
    assert await digest.send_if_due(store, settings, rec, cfg_on) is True
    assert len(rec.sent) == 2


async def test_a_missed_day_is_skipped_not_sent_at_night(store, settings, monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(timeutil, "now", lambda s: datetime(2026, 11, 25, 15, 0, tzinfo=TZ))
    assert await digest.send_if_due(store, settings, rec, {"enabled": True, "time": "08:00"}) is False
    assert rec.sent == []


async def test_the_scheduler_sends_the_briefing_and_survives_a_channel_failure(store, settings, monkeypatch):
    rec = Recorder()
    sched = ReminderScheduler(store, settings, push=rec)
    await digest.set_config(store, True, "08:00")
    at = datetime(2026, 11, 25, 8, 30, tzinfo=TZ)
    monkeypatch.setattr(timeutil, "now", lambda s: at)
    await sched._digest()
    await sched._digest()
    assert len(rec.sent) == 1 and sched.stats.get("digest_sent_at")

    class Broken:
        async def notify_digest(self, title, body):
            raise RuntimeError("down")

    sched2 = ReminderScheduler(store, settings, push=Broken())
    monkeypatch.setattr(timeutil, "now", lambda s: at + timedelta(days=1))
    await sched2._digest()                                                                            # must not raise: a broken channel cannot stop reminders


async def test_the_notifier_fans_out_and_isolates_a_failing_channel():
    class Ok:
        async def notify_digest(self, t, b):
            return {"sent": 1, "removed": 0, "failed": 0}

    class Boom:
        async def notify_digest(self, t, b):
            raise RuntimeError("x")

    class NoDigest:
        pass

    out = await Notifier(push=Ok(), telegram=Boom(), other=NoDigest()).notify_digest("t", "b")
    assert out["push"]["sent"] == 1 and out["telegram"]["failed"] == 1 and "other" not in out


# ── API ────────────────────────────────────────────────────────────────
TOKEN = "test-token-123"
H = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client():
    from src.interfaces.websocket_api import create_api
    from src.main import build_runtime

    cfg = Settings(llm_provider="mock", environment="local", sqlite_path=":memory:", intent_classifier="heuristic", timezone="UTC", api_token=TOKEN)
    runtime = asyncio.run(build_runtime(cfg))
    with TestClient(create_api(runtime.orchestrator, cfg, runtime.health_checker, runtime=runtime)) as c:
        yield c


@pytest.mark.parametrize("method,path", [("GET", "/api/digest"), ("PUT", "/api/digest"), ("POST", "/api/digest/test")])
def test_digest_routes_need_the_access_token(client, method, path):
    assert client.request(method, path, json={}).status_code == 401


def test_api_read_save_and_test_send(client):
    got = client.get("/api/digest", headers=H).json()
    assert got["enabled"] is False and got["time"] == "08:00" and got["preview"]["title"].startswith("Good morning") and got["timezone"] == "UTC"
    saved = client.put("/api/digest", json={"enabled": True, "time": "06:45"}, headers=H)
    assert saved.json() == {"enabled": True, "time": "06:45"} and client.get("/api/digest", headers=H).json()["enabled"] is True
    bad = client.put("/api/digest", json={"enabled": True, "time": "6.45"}, headers=H)
    assert bad.status_code == 400 and "hours and minutes" in bad.json()["detail"]
    assert client.put("/api/digest", json={"enabled": True, "time": "06:45", "x": 1}, headers=H).status_code == 422
    sent = client.post("/api/digest/test", headers=H)
    assert sent.status_code == 200 and sent.json()["title"].startswith("Good morning")
    assert any(n["kind"] == "digest" for n in client.get("/api/notifications", headers=H).json()["notifications"])
