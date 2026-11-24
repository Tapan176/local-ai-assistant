"""Work (tasks, projects, reminders, notes) and Growth (journal, rulebook, today's pick): service, API and chat skills."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from src.agent import timeutil, workspace
from src.agent.expenses import ExpenseError, NotFound
from src.config.settings import Settings
from src.storage.sqlite_store import SQLiteStore


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


async def pending(store):
    return await store.fetchall("SELECT id, title, due_at FROM reminders WHERE session_id = 'work' AND status = 'pending' ORDER BY id")


# ── tasks ──────────────────────────────────────────────────────────────
async def test_create_update_finish_and_delete_a_task(store, settings):
    t = await workspace.create_task(store, settings, title="  Send   the report ", project="Q4 plan", priority="high", due=day(settings, 2), details="to finance")
    assert t["title"] == "Send the report" and t["project"] == "Q4 plan" and t["priority"] == "high" and t["status"] == "open"
    assert t["due_date"] == day(settings, 2) and t["due_time"] is None and t["details"] == "to finance"
    t = await workspace.update_task(store, settings, t["id"], title="Send the final report", priority="low", project="")
    assert t["title"] == "Send the final report" and t["priority"] == "low" and t["project"] == ""
    done = await workspace.set_task_done(store, settings, t["id"], True)
    assert done["status"] == "done" and done["completed_at"]
    assert (await workspace.set_task_done(store, settings, t["id"], False))["completed_at"] is None
    await workspace.delete_task(store, t["id"])
    with pytest.raises(NotFound):
        await workspace.get_task(store, settings, t["id"])


@pytest.mark.parametrize("kwargs,message", [
    ({"title": "  "}, "Give the task a name"), ({"title": "x", "priority": "urgent"}, "priority must be one of"),
    ({"title": "x", "due": "someday-ish"}, "couldn't understand that due date"), ({"title": "x", "due": "2026-02-31"}, "real date"),
    ({"title": "x", "due": "1999-01-01"}, "out of range"), ({"title": "x", "remind": "morning"}, "needs a due date"),
    ({"title": "x", "remind": "weekly"}, "reminder must be"), ({"title": "x" * 201}, "too long"), ({"title": "x", "project": "p" * 61}, "too long"),
])
async def test_bad_tasks_are_refused_with_a_reason(store, settings, kwargs, message):
    with pytest.raises(ExpenseError, match=message):
        await workspace.create_task(store, settings, **kwargs)
    assert (await store.fetchone("SELECT COUNT(*) AS n FROM tasks"))["n"] == 0


async def test_a_date_without_a_time_means_the_end_of_that_day(store, settings):
    today = await workspace.create_task(store, settings, title="today", due=day(settings, 0))
    yesterday = await workspace.create_task(store, settings, title="yesterday", due=day(settings, -1))
    timed = await workspace.create_task(store, settings, title="timed", due=f"{day(settings, 3)}T17:30")
    assert today["overdue"] is False and today["due_today"] is True              # not overdue until the day is over
    assert yesterday["overdue"] is True and yesterday["due_today"] is False
    assert timed["due_time"] == "17:30" and timed["due_date"] == day(settings, 3)
    past_timed = await workspace.create_task(store, settings, title="earlier", due=f"{day(settings, -2)}T08:00")
    assert past_timed["overdue"] is True


async def test_open_tasks_sort_by_priority_then_date_with_undated_last_and_done_at_the_bottom(store, settings):
    await workspace.create_task(store, settings, title="low soon", priority="low", due=day(settings, 1))
    await workspace.create_task(store, settings, title="normal undated")
    await workspace.create_task(store, settings, title="normal later", due=day(settings, 9))
    await workspace.create_task(store, settings, title="high undated", priority="high")
    await workspace.create_task(store, settings, title="normal soon", due=day(settings, 2))
    finished = await workspace.create_task(store, settings, title="finished", priority="high")
    await workspace.set_task_done(store, settings, finished["id"], True)
    order = [t["title"] for t in await workspace.list_tasks(store, settings, "all")]
    assert order == ["high undated", "normal soon", "normal later", "normal undated", "low soon", "finished"]
    assert [t["title"] for t in await workspace.list_tasks(store, settings, "done")] == ["finished"]
    with pytest.raises(ExpenseError, match="open, done or all"):
        await workspace.list_tasks(store, settings, "someday")


async def test_filtering_by_project_and_searching_treat_percent_and_underscore_literally(store, settings):
    await workspace.create_task(store, settings, title="Hit 100% of target", project="Sales")
    await workspace.create_task(store, settings, title="snake_case rename", project="Code")
    await workspace.create_task(store, settings, title="Plain task", project="Code", details="mentions the budget")
    assert {t["title"] for t in await workspace.list_tasks(store, settings, project=" CODE ")} == {"snake_case rename", "Plain task"}   # case and spaces do not matter
    assert [t["title"] for t in await workspace.list_tasks(store, settings, project="sales")] == ["Hit 100% of target"]
    assert [t["title"] for t in await workspace.list_tasks(store, settings, q="100%")] == ["Hit 100% of target"]
    assert [t["title"] for t in await workspace.list_tasks(store, settings, q="%")] == ["Hit 100% of target"]          # not "everything"
    assert [t["title"] for t in await workspace.list_tasks(store, settings, q="_")] == ["snake_case rename"]
    assert [t["title"] for t in await workspace.list_tasks(store, settings, q="BUDGET")] == ["Plain task"]            # details and case


async def test_the_overview_counts_and_projects(store, settings):
    a = await workspace.create_task(store, settings, title="a", project="Alpha", due=day(settings, -1), priority="high")
    await workspace.create_task(store, settings, title="b", project="Alpha", due=day(settings, 0))
    await workspace.create_task(store, settings, title="c", project="Beta")
    d = await workspace.create_task(store, settings, title="d", project="Gamma")
    await workspace.set_task_done(store, settings, d["id"], True)
    ov = await workspace.work_overview(store, settings)
    assert (ov["open"], ov["overdue"], ov["due_today"], ov["high"], ov["no_date"], ov["done_7d"]) == (3, 1, 1, 1, 1, 1)
    assert ov["projects"] == [{"name": "Alpha", "open": 2, "overdue": 1}, {"name": "Beta", "open": 1, "overdue": 0}, {"name": "Gamma", "open": 0, "overdue": 0}]
    assert a["id"]


# ── a task's reminder always follows the task ──────────────────────────
async def test_the_reminder_follows_the_due_date_and_is_cancelled_with_the_task(store, settings):
    t = await workspace.create_task(store, settings, title="Call the vendor", project="Ops", due=day(settings, 5), remind="morning")
    live = await pending(store)
    assert len(live) == 1 and live[0]["title"] == "Task · Call the vendor · Ops" and live[0]["due_at"].startswith(f"{day(settings, 5)}T09:00")
    await workspace.update_task(store, settings, t["id"], title="Call the vendor again")
    live = await pending(store)
    assert len(live) == 1 and "again" in live[0]["title"]                           # one reminder, renamed
    await workspace.update_task(store, settings, t["id"], due=day(settings, 8))
    live = await pending(store)
    assert len(live) == 1 and live[0]["due_at"].startswith(f"{day(settings, 8)}T09:00")
    assert (await store.fetchone("SELECT COUNT(*) AS n FROM reminders WHERE session_id = 'work' AND status = 'cancelled'"))["n"] == 2
    await workspace.set_task_done(store, settings, t["id"], True)
    assert await pending(store) == []                                                # finished: no reminder
    await workspace.set_task_done(store, settings, t["id"], False)
    assert len(await pending(store)) == 1                                            # reopened: it is back
    await workspace.delete_task(store, t["id"])
    assert await pending(store) == []


async def test_reminder_choices_and_edge_cases(store, settings):
    due = await workspace.create_task(store, settings, title="timed", due=f"{day(settings, 4)}T15:45", remind="due")
    assert (await pending(store))[0]["due_at"].startswith(f"{day(settings, 4)}T15:45")
    before = await workspace.create_task(store, settings, title="eve", due=day(settings, 6), remind="day_before")
    live = {r["title"]: r["due_at"] for r in await pending(store)}
    assert live["Task · eve (due tomorrow)"].startswith(f"{day(settings, 5)}T09:00")
    same = await workspace.create_task(store, settings, title="datewise", due=day(settings, 7), remind="due")        # date only: 'at the due time' means 9 am
    assert any(r["due_at"].startswith(f"{day(settings, 7)}T09:00") for r in await pending(store))
    gone = await workspace.update_task(store, settings, due["id"], due="")                                         # clearing the date clears the reminder
    assert gone["due_at"] is None and gone["remind"] == ""
    assert len(await pending(store)) == 2
    past = await workspace.create_task(store, settings, title="too late", due=day(settings, -3), remind="morning")  # already in the past: nothing to schedule
    assert past["remind"] == "morning" and len([r for r in await pending(store) if "too late" in r["title"]]) == 0
    switched = await workspace.update_task(store, settings, before["id"], remind="none")
    assert switched["remind"] == "" and len(await pending(store)) == 1
    with pytest.raises(ExpenseError, match="needs a due date"):
        await workspace.update_task(store, settings, gone["id"], remind="morning")
    assert same["id"]


# ── notes: work and growth ─────────────────────────────────────────────
async def test_notes_are_created_with_normalised_tags_and_validated(store, settings):
    n = await workspace.create_note(store, space="growth", kind="lesson", title=" Patience ", body="  Slow is smooth.\r\nSmooth is fast.  ", tags="#Habits, deep work,habits , ")
    assert n["tags"] == ["habits", "deep-work"] and n["body"] == "Slow is smooth.\nSmooth is fast." and n["title"] == "Patience" and n["kind"] == "lesson"
    w = await workspace.create_note(store, space="work", body="Plan the launch")
    assert w["kind"] == "note" and w["space"] == "work"                               # default kind per space
    for kwargs, message in [({"space": "play", "body": "x"}, "space must be"), ({"space": "work", "kind": "lesson", "body": "x"}, "For work the kind must be"),
                            ({"space": "growth", "kind": "note", "body": "x"}, "For growth the kind must be"), ({"space": "work", "body": "   "}, "Write something"),
                            ({"space": "work", "body": "x" * 8001}, "too long"), ({"space": "work", "body": "x", "tags": ",".join(f"t{i}" for i in range(9))}, "at most 8 tags"),
                            ({"space": "work", "body": "x", "tags": "y" * 25}, "24 characters")]:
        with pytest.raises(ExpenseError, match=message):
            await workspace.create_note(store, **kwargs)


async def test_listing_filters_orders_and_pins(store, settings):
    r1 = await workspace.create_note(store, space="growth", kind="rule", body="Never reply angry", tags="calm")
    r2 = await workspace.create_note(store, space="growth", kind="rule", body="Sleep on big decisions", tags="calm,sleep")
    q = await workspace.create_note(store, space="growth", kind="quote", title="Seneca", body="We suffer more in imagination than in reality", tags="stoic")
    l1 = await workspace.create_note(store, space="growth", kind="lesson", body="Ask early", tags="work")
    l2 = await workspace.create_note(store, space="growth", kind="lesson", body="Ship small", tags="work")
    assert [n["id"] for n in await workspace.list_notes(store, "growth", "rule")] == [r1["id"], r2["id"]]       # a rulebook keeps its order
    assert [n["id"] for n in await workspace.list_notes(store, "growth", "lesson")] == [l2["id"], l1["id"]]     # a journal is newest first
    assert [n["id"] for n in await workspace.list_notes(store, "growth", tag="calm")] == [r2["id"], r1["id"]]
    assert [n["id"] for n in await workspace.list_notes(store, "growth", q="IMAGINATION")] == [q["id"]]
    assert [n["id"] for n in await workspace.list_notes(store, "growth", q="seneca")] == [q["id"]]               # title
    assert [n["id"] for n in await workspace.list_notes(store, "growth", q="stoic")] == [q["id"]]                # tag text
    assert await workspace.list_notes(store, "growth", tag="cal") == []                                          # a tag matches whole, not a prefix
    assert await workspace.list_notes(store, "growth", q="%") == []
    await workspace.update_note(store, l1["id"], pinned=True)
    assert (await workspace.list_notes(store, "growth", "lesson"))[0]["id"] == l1["id"]
    assert [n["id"] for n in await workspace.list_notes(store, "growth", pinned=True)] == [l1["id"]]
    assert await workspace.list_notes(store, "work") == []
    with pytest.raises(ExpenseError, match="space must be"):
        await workspace.list_notes(store, "nowhere")


async def test_update_delete_and_chat_notes_stay_out_of_reach(store, settings):
    n = await workspace.create_note(store, space="work", kind="plan", title="Launch", body="Draft", tags="q4")
    n = await workspace.update_note(store, n["id"], kind="meeting", body="Draft v2", tags="q4,launch", title="Launch sync")
    assert (n["kind"], n["body"], n["tags"], n["title"]) == ("meeting", "Draft v2", ["q4", "launch"], "Launch sync")
    with pytest.raises(ExpenseError, match="For work the kind must be"):
        await workspace.update_note(store, n["id"], kind="rule")
    with pytest.raises(ExpenseError, match="Write something"):
        await workspace.update_note(store, n["id"], body=" ")
    legacy = await store.execute("INSERT INTO notes (title, body, tags, created_at, updated_at) VALUES ('chat note', 'from chat', '', 't', 't')")
    with pytest.raises(ExpenseError, match="belongs to chat"):
        await workspace.update_note(store, legacy, body="hijack")
    assert await workspace.list_notes(store, "work") != [] and all(x["id"] != legacy for x in await workspace.list_notes(store, "work"))
    await workspace.delete_note(store, n["id"])
    with pytest.raises(NotFound):
        await workspace.delete_note(store, n["id"])


async def test_growth_overview_counts_tags_and_a_stable_daily_pick(store, settings, monkeypatch):
    assert (await workspace.growth_overview(store, settings))["pick"] is None
    for i in range(3):
        await workspace.create_note(store, space="growth", kind="rule", body=f"rule {i}", tags="calm" if i else "calm,focus")
    await workspace.create_note(store, space="growth", kind="thought", body="a passing thought")
    ov = await workspace.growth_overview(store, settings)
    assert ov["counts"]["rule"] == 3 and ov["counts"]["thought"] == 1 and ov["total"] == 4
    assert ov["tags"][0] == {"tag": "calm", "count": 3} and {"tag": "focus", "count": 1} in ov["tags"]
    first = ov["pick"]
    assert first["kind"] in ("rule", "quote", "lesson") and (await workspace.growth_overview(store, settings))["pick"]["id"] == first["id"]      # stable within the day
    real_now = timeutil.now
    seen = set()
    for offset in range(3):
        monkeypatch.setattr(timeutil, "now", lambda s, o=offset: real_now(s) + timedelta(days=o))
        seen.add((await workspace.todays_pick(store, settings))["id"])
    assert len(seen) == 3                                                                                        # three days, three different rules
    monkeypatch.setattr(timeutil, "now", real_now)
    pinned = await workspace.create_note(store, space="growth", kind="quote", body="Pinned quote", pinned=True)
    assert (await workspace.todays_pick(store, settings))["id"] == pinned["id"]                                  # pinned ones win


# ── chat skills ────────────────────────────────────────────────────────
@pytest.fixture
async def run(store, settings):
    import httpx

    from src.agent.skill import SkillContext
    from src.agent.skills import build_registry

    registry = build_registry(settings)
    async with httpx.AsyncClient() as http:
        ctx = SkillContext(settings=settings, store=store, http=http, session_id="t")

        async def call(skill, **args):
            return await registry.skills[skill].handler(ctx, args)
        yield call


async def test_chat_tasks_share_projects_reminders_and_completion_with_the_work_screen(run, store, settings):
    reply = await run("add_task", title="Draft the spec", project="Atlas", due=day(settings, 4), remind="morning", priority="high")
    assert "Added task #1: Draft the spec in project Atlas" in reply and "I will remind you" in reply
    assert len(await pending(store)) == 1
    listing = await run("list_tasks", project="atlas")
    assert listing[0]["title"] == "Draft the spec" and listing[0]["project"] == "Atlas"
    assert "needs a due date" in await run("add_task", title="x", remind="due")
    assert "Completed task #1" in await run("complete_task", id="1")
    assert await pending(store) == []                                                                            # finishing in chat cancels the reminder
    assert "No task #99" in await run("complete_task", id=99) and "No task #99" in await run("delete_task", id=99)
    assert "No open tasks" in await run("list_tasks")
    assert "Deleted task #1" in await run("delete_task", id=1)


async def test_chat_notebook_skills(run, store, settings):
    assert "empty" in await run("daily_principle")
    assert "Saved to your growth journal as a lesson" in await run("save_growth_note", kind="lesson", text="Ask for help early", tags="work")
    saved = await run("save_growth_note", kind="rule", text="Never decide angry")
    assert "rulebook" in saved
    assert "kind must be" in await run("save_growth_note", kind="meeting", text="x")
    assert "Write something" in await run("save_growth_note", kind="thought", text=" ")
    assert "your work notes" in await run("add_work_note", text="Q3 plan: ship v2", kind="plan")
    hits = await run("search_notebook", query="angry")
    assert hits[0]["space"] == "growth" and hits[0]["kind"] == "rule"
    assert len(await run("search_notebook", query="")) == 3
    assert [h["space"] for h in await run("search_notebook", query="ship", space="work")] == ["work"]
    assert "Nothing in your notebook" in await run("search_notebook", query="zebra")
    assert (await run("daily_principle"))["kind"] in ("rule", "lesson")


# ── API ────────────────────────────────────────────────────────────────
TOKEN = "test-token-123"
H = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client():
    import asyncio

    from src.interfaces.websocket_api import create_api
    from src.main import build_runtime

    cfg = Settings(llm_provider="mock", environment="local", sqlite_path=":memory:", intent_classifier="heuristic", timezone="UTC", api_token=TOKEN)
    runtime = asyncio.run(build_runtime(cfg))
    with TestClient(create_api(runtime.orchestrator, cfg, runtime.health_checker, runtime=runtime)) as c:
        yield c


ROUTES = [("GET", "/api/work"), ("POST", "/api/work/tasks"), ("PATCH", "/api/work/tasks/1"), ("DELETE", "/api/work/tasks/1"), ("POST", "/api/work/tasks/1/done"),
          ("GET", "/api/notebook?space=work"), ("POST", "/api/notebook"), ("PATCH", "/api/notebook/1"), ("DELETE", "/api/notebook/1"), ("GET", "/api/growth")]


@pytest.mark.parametrize("method,path", ROUTES)
def test_every_route_needs_the_access_token(client, method, path):
    assert client.request(method, path, json={}).status_code == 401
    assert client.request(method, path, json={}, headers={"Authorization": "Bearer nope"}).status_code == 401


def soon(n: int) -> str:
    return (datetime.utcnow() + timedelta(days=n)).date().isoformat()


def test_work_over_the_api(client):
    r = client.post("/api/work/tasks", json={"title": "Write brief", "project": "Atlas", "priority": "high", "due": soon(3), "remind": "morning"}, headers=H)
    assert r.status_code == 200 and r.json()["remind"] == "morning" and r.json()["due_date"] == soon(3)
    tid = r.json()["id"]
    work = client.get("/api/work", headers=H).json()
    assert [t["title"] for t in work["tasks"]] == ["Write brief"] and work["overview"]["open"] == 1 and work["overview"]["projects"][0]["name"] == "Atlas"
    assert work["priorities"] == ["high", "normal", "low"] and "plan" in work["kinds"] and len(work["today"]) == 10
    assert client.get("/api/work", params={"project": "nothing"}, headers=H).json()["tasks"] == []
    assert client.get("/api/work", params={"status": "bogus"}, headers=H).status_code == 400
    cleared = client.patch(f"/api/work/tasks/{tid}", json={"due": None}, headers=H)                   # an explicit null clears the date (and so the reminder)
    assert cleared.status_code == 200 and cleared.json()["due_at"] is None and cleared.json()["remind"] == ""
    assert client.patch(f"/api/work/tasks/{tid}", json={"title": None}, headers=H).status_code == 400
    assert client.patch(f"/api/work/tasks/{tid}", json={"priority": "meh"}, headers=H).status_code == 400
    assert client.post(f"/api/work/tasks/{tid}/done", headers=H).json()["status"] == "done"          # no body means done
    assert client.post(f"/api/work/tasks/{tid}/done", json={"done": False}, headers=H).json()["status"] == "open"
    assert client.post("/api/work/tasks/999/done", headers=H).status_code == 404
    assert client.post("/api/work/tasks", json={"title": "x", "bogus": 1}, headers=H).status_code == 422
    assert client.post("/api/work/tasks", json={"title": "x", "remind": "due"}, headers=H).status_code == 400
    assert client.delete(f"/api/work/tasks/{tid}", headers=H).json() == {"ok": True}
    assert client.delete(f"/api/work/tasks/{tid}", headers=H).status_code == 404


def test_the_today_panel_completion_also_cancels_the_reminder(client):
    t = client.post("/api/work/tasks", json={"title": "Pay vendor", "due": soon(3), "remind": "morning"}, headers=H).json()
    assert client.post(f"/api/tasks/{t['id']}/complete", headers=H).status_code == 200
    assert client.get("/api/work", params={"status": "done"}, headers=H).json()["tasks"][0]["title"] == "Pay vendor"
    briefing = client.get("/api/briefing", headers=H).json()
    assert all(r["title"] != "Task · Pay vendor" for r in briefing["upcoming_reminders"] + briefing["reminders_today"])
    assert client.post(f"/api/tasks/{t['id']}/complete", headers=H).status_code == 404


def test_notebook_and_growth_over_the_api(client):
    a = client.post("/api/notebook", json={"space": "growth", "kind": "rule", "body": "Never decide angry", "tags": "calm"}, headers=H)
    assert a.status_code == 200 and a.json()["tags"] == ["calm"]
    client.post("/api/notebook", json={"space": "growth", "kind": "quote", "title": "Seneca", "body": "Begin at once"}, headers=H)
    client.post("/api/notebook", json={"space": "work", "kind": "plan", "body": "Launch plan"}, headers=H)
    growth = client.get("/api/growth", headers=H).json()
    assert growth["total"] == 2 and growth["counts"]["rule"] == 1 and growth["pick"]["body"] in ("Never decide angry", "Begin at once") and len(growth["notes"]) == 2
    only_rules = client.get("/api/notebook", params={"space": "growth", "kind": "rule"}, headers=H).json()
    assert [n["body"] for n in only_rules["notes"]] == ["Never decide angry"] and "thought" in only_rules["kinds"]
    assert client.get("/api/notebook", params={"space": "work", "q": "launch"}, headers=H).json()["notes"][0]["kind"] == "plan"
    assert client.get("/api/notebook", params={"space": "x"}, headers=H).status_code == 400
    nid = a.json()["id"]
    assert client.patch(f"/api/notebook/{nid}", json={"pinned": True, "body": "Never decide angry. Sleep first."}, headers=H).json()["pinned"] is True
    assert client.patch(f"/api/notebook/{nid}", json={"body": None}, headers=H).status_code == 400
    assert client.patch(f"/api/notebook/{nid}", json={"kind": "plan"}, headers=H).status_code == 400
    assert client.post("/api/notebook", json={"space": "growth", "kind": "rule", "body": ""}, headers=H).status_code == 400
    assert client.post("/api/notebook", json={"space": "growth", "body": "x" * 20001}, headers=H).status_code == 422
    assert client.delete(f"/api/notebook/{nid}", headers=H).json() == {"ok": True}
    assert client.delete(f"/api/notebook/{nid}", headers=H).status_code == 404
