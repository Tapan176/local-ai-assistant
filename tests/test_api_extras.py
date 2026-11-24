"""REST endpoints that back the web UI: conversation history, the Today panel and its quick actions."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from src.agent import timeutil
from src.config.settings import Settings
from src.interfaces.websocket_api import create_api
from src.main import build_runtime


def _app(**overrides):
    settings = Settings(
        llm_provider="mock", environment="local", sqlite_path=":memory:", intent_classifier="heuristic", timezone="UTC", **overrides
    )
    runtime = asyncio.run(build_runtime(settings))
    return settings, runtime, create_api(runtime.orchestrator, settings, runtime.health_checker, runtime=runtime)


def _run(coro):
    return asyncio.run(coro)


def test_history_returns_recent_turns_oldest_first_per_session():
    _, rt, app = _app()
    for i in range(5):
        _run(rt.sqlite_store.execute(
            'INSERT INTO episodes (session_id, "timestamp", user_text, assistant_text, emotional_state) VALUES (?,?,?,?,?)',
            ("mine", f"2026-11-23T10:0{i}:00+00:00", f"q{i}", f"a{i}", "neutral")))
    _run(rt.sqlite_store.execute(
        'INSERT INTO episodes (session_id, "timestamp", user_text, assistant_text, emotional_state) VALUES (?,?,?,?,?)',
        ("someone-else", "2026-11-23T11:00:00+00:00", "secret", "secret", "neutral")))
    with TestClient(app) as c:
        body = c.get("/api/history", params={"session_id": "mine", "limit": 3}).json()
        assert [m["text"] for m in body["messages"]] == ["q2", "a2", "q3", "a3", "q4", "a4"]  # last 3 turns, chronological
        assert body["messages"][0]["role"] == "user" and body["messages"][1]["role"] == "assistant"
        assert "secret" not in str(body)  # sessions are isolated
        assert c.get("/api/history", params={"session_id": "nobody"}).json() == {"messages": []}
        assert len(c.get("/api/history", params={"session_id": "mine", "limit": 9999}).json()["messages"]) == 10  # capped, not crashed


def test_history_and_actions_require_the_token():
    _, _, app = _app(api_token="s3cret")
    with TestClient(app) as c:
        for method, url in [("get", "/api/history?session_id=x"), ("post", "/api/tasks/1/complete"), ("delete", "/api/reminders/1")]:
            assert getattr(c, method)(url).status_code == 401
        assert c.get("/api/history?session_id=x", headers={"Authorization": "Bearer s3cret"}).status_code == 200


def test_complete_task_and_cancel_reminder():
    settings, rt, app = _app()
    _run(rt.sqlite_store.execute("INSERT INTO tasks (title, status, created_at) VALUES ('Write report', 'open', 't')"))
    soon = (timeutil.now(settings) + timedelta(days=2)).isoformat()
    _run(rt.sqlite_store.execute("INSERT INTO reminders (session_id, title, due_at, status, created_at) VALUES ('s','Dentist',?, 'pending','t')", (soon,)))
    with TestClient(app) as c:
        assert c.post("/api/tasks/1/complete").json() == {"ok": True}
        assert c.post("/api/tasks/1/complete").status_code == 404  # already done
        assert c.post("/api/tasks/999/complete").status_code == 404
        assert c.delete("/api/reminders/1").json() == {"ok": True}
        assert c.delete("/api/reminders/1").status_code == 404
    assert _run(rt.sqlite_store.fetchone("SELECT status FROM tasks"))["status"] == "done"
    assert _run(rt.sqlite_store.fetchone("SELECT status FROM reminders"))["status"] == "cancelled"


def test_briefing_separates_overdue_today_and_upcoming():
    settings, rt, app = _app()
    now = timeutil.now(settings)
    rows = [("Overdue one", now - timedelta(hours=2)), ("Later today", now + timedelta(minutes=1)),
            ("Next week", now + timedelta(days=7)), ("Tomorrow", now + timedelta(days=1, hours=1))]
    for title, due in rows:
        _run(rt.sqlite_store.execute("INSERT INTO reminders (session_id, title, due_at, status, created_at) VALUES ('s',?,?, 'pending','t')", (title, due.isoformat())))
    data = TestClient(app).get("/api/briefing").json()  # no `with`: lifespan (and its scheduler) must not fire the overdue one
    assert [r["title"] for r in data["overdue_reminders"]] == ["Overdue one"]
    upcoming = [r["title"] for r in data["upcoming_reminders"]]
    assert upcoming == ["Tomorrow", "Next week"]  # soonest first, none of today's or overdue
    assert all("id" in r for r in data["upcoming_reminders"] + data["reminders_today"])


def _episode(rt, session, user, ts):
    _run(rt.sqlite_store.execute(
        'INSERT INTO episodes (session_id, "timestamp", user_text, assistant_text, emotional_state) VALUES (?,?,?,?,?)',
        (session, ts, user, "reply", "neutral")))


def test_conversation_list_titles_order_and_delete_keeps_memories():
    _, rt, app = _app()
    _episode(rt, "old", "Plan my trip to Goa", "2026-11-01T09:00:00+00:00")
    _episode(rt, "old", "and book the hotel", "2026-11-01T09:05:00+00:00")
    _episode(rt, "new", "Remind me about the very long thing " + "x" * 100, "2026-11-23T09:00:00+00:00")
    _run(rt.sqlite_store.execute("INSERT INTO memories (content, category, created_at) VALUES ('Likes Goa', 'preference', 't')"))
    with TestClient(app) as c:
        convs = c.get("/api/conversations").json()["conversations"]
        assert [x["session_id"] for x in convs] == ["new", "old"]  # most recently active first
        assert convs[1]["title"] == "Plan my trip to Goa" and convs[1]["turns"] == 2
        assert convs[0]["title"].endswith("…") and len(convs[0]["title"]) <= 61
        assert convs[1]["updated"].startswith("2026-11-01T09:05")
        assert c.delete("/api/conversations/old").json() == {"ok": True}
        assert [x["session_id"] for x in c.get("/api/conversations").json()["conversations"]] == ["new"]
        assert c.get("/api/history", params={"session_id": "old"}).json() == {"messages": []}
    assert _run(rt.sqlite_store.fetchone("SELECT COUNT(*) AS n FROM memories")) == {"n": 1}  # facts survive deleting a chat


def test_empty_conversation_list_and_token_protection():
    _, _, app = _app(api_token="s3cret")
    with TestClient(app) as c:
        assert c.get("/api/conversations").status_code == 401 and c.delete("/api/conversations/x").status_code == 401
        assert c.get("/api/conversations", headers={"Authorization": "Bearer s3cret"}).json() == {"conversations": []}
