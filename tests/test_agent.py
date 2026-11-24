"""Tests for the Jarvis agent layer: skills, LLM client failover, agent loop, scheduler, API security."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from src.agent import timeutil
from src.agent.loop import AgentLoop
from src.agent.service import ReminderScheduler
from src.agent.skill import SkillContext
from src.agent.skills import build_registry
from src.agent.skills.core import safe_calculate
from src.agent.skills.local import safe_path
from src.agent.skills.web import UnsafeURL, assert_public_url, html_to_text, parse_search_results
from src.config.settings import Settings
from src.interfaces.websocket_api import create_api
from src.llm.chat_client import ChatClient, ChatResult
from src.storage.sqlite_store import SQLiteStore


# ── fixtures ────────────────────────────────────────────────────────
@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        sqlite_path=":memory:",
        llm_provider="omniroute",
        omniroute_api_key="k",
        environment="local",
        workspace_dir=str(tmp_path / "ws"),
        timezone="UTC",
    )


@pytest.fixture
async def store():
    s = SQLiteStore(":memory:")
    await s.initialize()
    return s


@pytest.fixture
async def ctx(settings, store):
    async with httpx.AsyncClient() as http:
        yield SkillContext(settings=settings, store=store, http=http, session_id="t")


async def call(settings, ctx, name, **args):
    registry = build_registry(settings)
    return await registry.execute(name, args, ctx)


# ── calculator ──────────────────────────────────────────────────────
def test_calculator_math():
    assert safe_calculate("(1250*0.18)+40") == pytest.approx(265.0)
    assert safe_calculate("max(1,2)+sqrt(16)") == 6
    assert safe_calculate("2^10") == 1024


@pytest.mark.parametrize("bad", ["__import__('os').system('x')", "open('f')", "2**100000", "[1]*10", "a+1"])
def test_calculator_rejects_unsafe(bad):
    with pytest.raises(Exception):
        safe_calculate(bad)


# ── memory / notes / tasks / reminders ──────────────────────────────
async def test_memory_roundtrip(settings, ctx):
    ok, _ = await call(settings, ctx, "remember", content="Prefers meetings after 11am", category="preference")
    assert ok
    _, dup = await call(settings, ctx, "remember", content="prefers meetings after 11AM")
    assert "Already remembered" in dup
    _, found = await call(settings, ctx, "recall", query="meetings")
    assert "11am" in found
    _, none = await call(settings, ctx, "recall", query="zzzz")
    assert "Nothing stored" in none


async def test_notes_and_tasks(settings, ctx):
    await call(settings, ctx, "add_note", body="Buy filament", title="shopping", tags="home")
    _, hits = await call(settings, ctx, "search_notes", query="filament")
    assert "Buy filament" in hits

    ok, msg = await call(settings, ctx, "add_task", title="File taxes", due="2030-01-02T09:00", priority="high")
    assert ok and "File taxes" in msg
    _, listing = await call(settings, ctx, "list_tasks")
    assert "File taxes" in listing
    await call(settings, ctx, "complete_task", id="1")  # model may send ids as strings
    _, listing = await call(settings, ctx, "list_tasks")
    assert "No open tasks" in listing


async def test_reminder_validation_and_scheduler(settings, ctx, store):
    _, msg = await call(settings, ctx, "set_reminder", title="x", when="2000-01-01T00:00")
    assert "in the past" in msg

    soon = (timeutil.now(settings) + timedelta(seconds=1)).isoformat()
    ok, _ = await call(settings, ctx, "set_reminder", title="Call mom", when=soon)
    assert ok
    sched = ReminderScheduler(store, settings)
    assert await sched.tick() == 0  # not due yet

    await store.execute("UPDATE reminders SET due_at = ?", ((timeutil.now(settings) - timedelta(minutes=1)).isoformat(),))
    assert await sched.tick() == 1
    assert await sched.tick() == 0  # fires exactly once
    notes = await store.fetchall("SELECT title, body FROM notifications")
    assert notes == [{"title": "Reminder", "body": "Call mom"}]


async def test_missing_and_unknown_args(settings, ctx):
    ok, msg = await call(settings, ctx, "add_task")
    assert not ok and "Missing required" in msg
    ok, msg = await call(settings, ctx, "nope")
    assert not ok and "Unknown tool" in msg


async def test_briefing_collects_everything(settings, ctx):
    from src.agent.skills.briefing import build_briefing

    await call(settings, ctx, "add_task", title="Ship v2", priority="high")
    data = await build_briefing(ctx)
    assert data["open_tasks"][0]["title"] == "Ship v2"
    assert "now" in data


# ── security: SSRF + file sandbox ───────────────────────────────────
@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1/", "http://localhost:8000/", "http://10.0.0.5/", "http://169.254.169.254/latest/meta-data",
     "http://[::1]/", "file:///etc/passwd", "ftp://example.com/"],
)
async def test_ssrf_blocked(url):
    with pytest.raises(UnsafeURL):
        await assert_public_url(url)


async def test_public_ip_literal_allowed():
    assert await assert_public_url("https://8.8.8.8/") == "https://8.8.8.8/"


def test_workspace_sandbox(settings, tmp_path):
    ctx = SkillContext(settings=settings, store=None, http=None)  # type: ignore[arg-type]
    inside = safe_path(ctx, "notes/a.txt")
    assert inside.is_relative_to((tmp_path / "ws").resolve())
    for evil in ("../secret.txt", "..\\..\\x", str(tmp_path / "outside.txt"), "a/../../b"):
        with pytest.raises(PermissionError):
            safe_path(ctx, evil)


async def test_write_file_never_clobbers_by_default(settings, ctx):
    assert (await call(settings, ctx, "write_file", path="a.txt", content="one"))[0]
    _, msg = await call(settings, ctx, "write_file", path="a.txt", content="two")
    assert "already exists" in msg
    _, text = await call(settings, ctx, "read_file", path="a.txt")
    assert text == "one"
    ok, msg = await call(settings, ctx, "write_file", path="../evil.txt", content="x")
    assert not ok and "outside the workspace" in msg


def test_local_skills_disabled_when_hosted(settings):
    hosted = settings.model_copy(update={"environment": "prod"})
    names = build_registry(hosted).names()
    assert "read_file" not in names and "open_app" not in names and "web_search" in names
    assert "read_file" in build_registry(settings).names()


def test_html_and_search_parsing():
    title, text = html_to_text("<html><head><title>Hi</title></head><body><script>x()</script><p>Hello</p><p>World</p></body></html>")
    assert title == "Hi" and "Hello" in text and "x()" not in text

    html = (
        '<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa&amp;rut=1">Example <b>A</b></a>'
        '<a class="result__snippet" href="x">First &amp; best</a>'
        '<a class="result__a" href="https://example.org/b">Second</a>'
    )
    results = parse_search_results(html, 5)
    assert results[0] == {"title": "Example A", "url": "https://example.com/a", "snippet": "First & best"}
    assert results[1]["url"] == "https://example.org/b" and results[1]["snippet"] == ""


# ── LLM client: failover, native tools, text-protocol fallback ──────
def _client(settings, handler) -> ChatClient:
    return ChatClient(settings, httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def _ok(message: dict) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": message}]})


async def test_native_tool_call_parsing(settings):
    def handler(request):
        assert request.url.path == "/v1/chat/completions" and request.headers["authorization"] == "Bearer k"
        body = json.loads(request.content)
        assert body["model"] == "auto" and body["tools"]
        return _ok({"content": None, "tool_calls": [{"id": "c1", "function": {"name": "calculate", "arguments": '{"expression": "1+1"}'}}]})

    result = await _client(settings, handler).complete([{"role": "user", "content": "hi"}], tools=[{"type": "function", "function": {"name": "calculate", "parameters": {}}}])
    assert result.tool_calls == [{"id": "c1", "name": "calculate", "arguments": {"expression": "1+1"}}]


async def test_falls_back_to_text_protocol_when_tools_rejected(settings):
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        if "tools" in body:
            return httpx.Response(400, json={"error": "tools unsupported"})
        return _ok({"content": 'Sure <tool_call>{"name": "calculate", "arguments": {"expression": "2+2"}}</tool_call>'})

    tools = [{"type": "function", "function": {"name": "calculate", "description": "math", "parameters": {"type": "object"}}}]
    client = _client(settings, handler)
    result = await client.complete([{"role": "system", "content": "sys"}, {"role": "user", "content": "2+2?"}], tools=tools)
    assert result.tool_calls[0]["name"] == "calculate" and result.tool_calls[0]["arguments"] == {"expression": "2+2"}
    assert "calculate" in seen[-1]["messages"][0]["content"]  # catalogue injected into the system prompt

    # the endpoint is remembered as text-only: no wasted native attempt next time
    seen.clear()
    await client.complete([{"role": "user", "content": "again"}], tools=tools)
    assert all("tools" not in body for body in seen)


async def test_failover_to_openrouter_and_cooldown(settings):
    settings = settings.model_copy(update={"openrouter_api_key": "or-key"})
    hosts = []

    def handler(request):
        hosts.append(request.url.host)
        if request.url.host == "localhost":  # omniroute down
            raise httpx.ConnectError("refused")
        return _ok({"content": "from openrouter <think>hidden</think>"})

    client = _client(settings, handler)
    result = await client.complete([{"role": "user", "content": "x"}])
    assert result.provider == "openrouter" and result.content == "from openrouter"
    hosts.clear()
    await client.complete([{"role": "user", "content": "y"}])
    assert "localhost" not in hosts  # failing endpoint is skipped during cooldown


async def test_no_providers_in_mock_mode(settings):
    mock = settings.model_copy(update={"llm_provider": "mock"})
    assert await ChatClient(mock).complete([{"role": "user", "content": "x"}]) is None


# ── agent loop end-to-end with a scripted LLM ───────────────────────
class ScriptedLLM:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    async def complete(self, messages, tools=None, temperature=0.4, json_mode=False):
        self.calls.append({"messages": [dict(m) for m in messages], "tools": tools})
        return self.replies.pop(0)


def _loop(settings, store, http, llm):
    registry = build_registry(settings)
    return AgentLoop(settings, llm, registry, store, lambda sid: SkillContext(settings, store, http, sid))


async def test_agent_runs_tools_then_answers(settings, store):
    future = (timeutil.now(settings) + timedelta(days=1)).isoformat()
    llm = ScriptedLLM(
        [
            ChatResult(tool_calls=[{"id": "1", "name": "set_reminder", "arguments": {"title": "Pay rent", "when": future}},
                                   {"id": "2", "name": "calculate", "arguments": {"expression": "6*7"}}], provider="omniroute", model="auto"),
            ChatResult(content="Done — reminder set, and 6×7 is 42.", provider="omniroute", model="auto"),
        ]
    )
    events = []

    async def on_event(e):
        events.append(e["type"] + ":" + e["name"] if "name" in e else e["type"])

    async with httpx.AsyncClient() as http:
        result = await _loop(settings, store, http, llm).run("s1", "remind me to pay rent tomorrow and what's 6*7", on_event)

    assert result.text.startswith("Done") and [s.name for s in result.steps] == ["set_reminder", "calculate"]
    assert all(s.ok for s in result.steps) and result.steps[1].result == "42"
    assert (await store.fetchone("SELECT title FROM reminders"))["title"] == "Pay rent"
    assert events.count("tool_start:set_reminder") == 1 and "tool_end:calculate" in events
    # second LLM call must have seen both tool results
    roles = [m["role"] for m in llm.calls[1]["messages"]]
    assert roles.count("tool") == 2
    assert "Current date/time" in llm.calls[0]["messages"][0]["content"]


async def test_agent_recovers_from_tool_errors_and_injects_memory(settings, store):
    await store.execute("INSERT INTO memories (content, category, created_at) VALUES ('Likes green tea', 'preference', 'x')")
    llm = ScriptedLLM(
        [
            ChatResult(tool_calls=[{"id": "1", "name": "add_task", "arguments": {}}]),
            ChatResult(content="I need a title for that task."),
        ]
    )
    async with httpx.AsyncClient() as http:
        result = await _loop(settings, store, http, llm).run("s", "add a task")
    assert result.steps[0].ok is False and "Missing required" in result.steps[0].result
    assert "Likes green tea" in llm.calls[0]["messages"][0]["content"]
    assert result.text == "I need a title for that task."


async def test_agent_step_budget_forces_final_answer(settings, store):
    settings = settings.model_copy(update={"agent_max_steps": 2})
    loop_call = ChatResult(tool_calls=[{"id": "x", "name": "get_current_time", "arguments": {}}])
    llm = ScriptedLLM([loop_call, loop_call, ChatResult(content="Here is what I have.")])
    async with httpx.AsyncClient() as http:
        result = await _loop(settings, store, http, llm).run("s", "go")
    assert result.text == "Here is what I have." and llm.calls[-1]["tools"] is None


async def test_agent_returns_none_when_no_llm(settings, store):
    class Dead:
        async def complete(self, *a, **k):
            return None

    async with httpx.AsyncClient() as http:
        assert await _loop(settings, store, http, Dead()).run("s", "hi") is None


async def test_history_is_replayed(settings, store):
    await store.execute(
        "INSERT INTO episodes (session_id, timestamp, user_text, assistant_text, emotional_state) VALUES ('h','t','my cat is Miso','Nice name!','neutral')"
    )
    llm = ScriptedLLM([ChatResult(content="Miso, yes.")])
    async with httpx.AsyncClient() as http:
        await _loop(settings, store, http, llm).run("h", "what's my cat called?")
    sent = llm.calls[0]["messages"]
    assert [m["content"] for m in sent[1:3]] == ["my cat is Miso", "Nice name!"]


# ── API security & facade ───────────────────────────────────────────
class EchoOrchestrator:
    async def handle_user_input(self, session_id, user_text):
        from src.models import OrchestratorResponse

        return OrchestratorResponse(session_id=session_id, text=f"echo:{user_text}", action_type="respond")


def test_prod_requires_token(settings):
    with pytest.raises(RuntimeError, match="TAPAN_API_TOKEN"):
        create_api(EchoOrchestrator(), settings.model_copy(update={"environment": "prod"}))


def test_api_token_enforced(settings):
    app = create_api(EchoOrchestrator(), settings.model_copy(update={"api_token": "s3cret"}))
    with TestClient(app) as c:
        body = {"session_id": "a", "message": "hi"}
        assert c.get("/health").status_code == 200  # liveness stays public
        assert c.get("/health/details").status_code == 401
        assert c.post("/chat", json=body).status_code == 401
        assert c.post("/chat", json=body, headers={"Authorization": "Bearer wrong"}).status_code == 401
        ok = c.post("/chat", json=body, headers={"Authorization": "Bearer s3cret"})
        assert ok.status_code == 200 and ok.json()["response"] == "echo:hi"
        assert c.post("/chat", json=body, headers={"X-API-Key": "s3cret"}).status_code == 200

        # WebSockets: the token is sent as the first frame (never in the URL, which would land in access logs)
        def closes_with_4401(first_frame):
            from starlette.websockets import WebSocketDisconnect

            with c.websocket_connect("/ws/a") as ws:
                if first_frame is not None:
                    ws.send_text(first_frame)
                with pytest.raises(WebSocketDisconnect) as info:
                    ws.receive_json()
            return info.value.code == 4401

        assert closes_with_4401('{"auth": "wrong"}')
        assert closes_with_4401("hello without authenticating")  # chat before auth is refused, not processed
        with c.websocket_connect("/ws/a") as ws:
            ws.send_text('{"auth": "s3cret"}')
            assert ws.receive_json() == {"type": "auth_ok"}
            ws.send_text("yo")
            assert ws.receive_json()["text"] == "echo:yo"
        with c.websocket_connect("/ws/a", headers={"Authorization": "Bearer s3cret"}) as ws:  # scripts: handshake header
            ws.send_text("hi")
            assert ws.receive_json()["text"] == "echo:hi"
        with c.websocket_connect("/ws-stream/a") as ws:
            ws.send_text('{"auth": "s3cret"}')
            assert ws.receive_json()["type"] == "auth_ok"
        # the old query-string form must NOT authenticate any more
        with c.websocket_connect("/ws/a?token=s3cret") as ws:
            ws.send_text("hi")
            from starlette.websockets import WebSocketDisconnect

            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()


def test_open_server_ignores_auth_frames(settings):
    """With no token configured, the UI's {"auth": ""} handshake is acknowledged and chat works normally."""
    app = create_api(EchoOrchestrator(), settings)
    with TestClient(app) as c, c.websocket_connect("/ws/a") as ws:
        ws.send_text('{"auth": ""}')
        assert ws.receive_json() == {"type": "auth_ok"}
        ws.send_text("plain")
        assert ws.receive_json()["text"] == "echo:plain"
        ws.send_text('{"not_auth": 1}')  # JSON that merely looks like an object is still a chat message
        assert ws.receive_json()["text"] == 'echo:{"not_auth": 1}'


def test_rate_limit(settings):
    app = create_api(EchoOrchestrator(), settings.model_copy(update={"rate_limit_per_minute": 2}))
    with TestClient(app) as c:
        codes = [c.post("/chat", json={"session_id": "a", "message": "x"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


async def test_facade_uses_agent_then_falls_back_to_legacy(settings, store):
    from src.agent.service import AgentOrchestrator
    from src.models import OrchestratorResponse

    class Legacy:
        async def handle_user_input(self, session_id, user_text):
            return OrchestratorResponse(session_id=session_id, text="legacy says hi", action_type="respond")

    class Episodic:
        def __init__(self):
            self.turns = []

        async def add_turn(self, turn):
            self.turns.append(turn)

    episodic = Episodic()
    llm = ScriptedLLM([ChatResult(content="agent says hi", provider="omniroute", model="auto")])
    async with httpx.AsyncClient() as http:
        facade = AgentOrchestrator(settings, _loop(settings, store, http, llm), Legacy(), episodic)  # type: ignore[arg-type]
        first = await facade.handle_user_input("s", "hello")
        assert first.text == "agent says hi" and first.debug["mode"] == "agent" and len(episodic.turns) == 1

        llm.replies = [None]  # provider outage
        second = await facade.handle_user_input("s", "hello again")
        assert second.text == "legacy says hi" and second.debug["mode"] == "legacy"


# ── regression: parallel tool calls share one SQLite connection ─────
async def test_concurrent_db_writes_do_not_collide(settings, ctx):
    """The model often emits several tool calls at once; they run concurrently via asyncio.gather."""
    import asyncio

    registry = build_registry(settings)
    results = await asyncio.gather(
        *(registry.execute("remember", {"content": f"fact number {i}"}, ctx) for i in range(60)),
        *(registry.execute("add_task", {"title": f"task {i}"}, ctx) for i in range(60)),
        *(registry.execute("recall", {"query": "fact"}, ctx) for _ in range(30)),
    )
    failures = [text for ok, text in results if not ok]
    assert not failures, failures[:3]
    rows = await ctx.store.fetchone("SELECT (SELECT COUNT(*) FROM memories) AS m, (SELECT COUNT(*) FROM tasks) AS t")
    assert rows == {"m": 60, "t": 60}


def test_health_reports_config_without_leaking_secrets(settings):
    cfg = settings.model_copy(update={"database_url": "postgresql://u:supersecret@h/db", "openrouter_api_key": "sk-top-secret",
                                      "api_token": "tok"})
    with TestClient(create_api(EchoOrchestrator(), cfg)) as c:
        body = c.get("/health").json()
    assert body["database"] == "postgres" and body["llm_key_configured"] is True and body["auth_required"] is True
    assert "supersecret" not in str(body) and "sk-top-secret" not in str(body) and "tok" not in body.values()
    with TestClient(create_api(EchoOrchestrator(), settings.model_copy(update={"omniroute_api_key": ""}))) as c:
        assert c.get("/health").json()["database"] == "sqlite" and c.get("/health").json()["llm_key_configured"] is False


# ── batch reminders ─────────────────────────────────────────────────
def _iso(settings, **delta):
    return (timeutil.now(settings) + timedelta(**delta)).replace(microsecond=0).isoformat()


async def test_set_reminders_creates_many_in_one_call(settings, ctx, store):
    import json

    items = [
        {"title": "Call mom", "when": _iso(settings, days=1)},
        {"title": "Pay rent", "when": _iso(settings, days=2, hours=3)},
        {"title": "Gym", "when": _iso(settings, hours=5)},
    ]
    ok, text = await call(settings, ctx, "set_reminders", reminders=items)
    data = json.loads(text)
    assert ok and data["summary"] == "3 reminder(s) set, 0 skipped" and not data["skipped"]
    assert [c["title"] for c in data["created"]] == ["Call mom", "Pay rent", "Gym"]
    assert [int(c["id"]) for c in data["created"]] == [1, 2, 3]
    rows = await store.fetchall("SELECT title, status FROM reminders ORDER BY id")
    assert [r["title"] for r in rows] == ["Call mom", "Pay rent", "Gym"] and {r["status"] for r in rows} == {"pending"}


async def test_set_reminders_saves_good_items_and_explains_the_rest(settings, ctx, store):
    import json

    items = [
        {"title": "Good one", "when": _iso(settings, days=1)},
        {"title": "In the past", "when": "2000-01-01T00:00:00"},
        {"title": "Nonsense time", "when": "whenever the stars align"},
        {"title": "", "when": _iso(settings, days=1)},
        {"title": "No time at all"},
        "just a string",
        {"title": "Good one", "when": _iso(settings, days=1)},  # exact duplicate inside the batch
    ]
    _, text = await call(settings, ctx, "set_reminders", reminders=items)
    data = json.loads(text)
    assert [c["title"] for c in data["created"]] == ["Good one"]
    reasons = {s["item"]: s["reason"] for s in data["skipped"]}
    assert "in the past" in reasons["In the past"]
    assert "couldn't understand" in reasons["Nonsense time"]
    assert reasons["#4"] == "missing title" and reasons["No time at all"] == "missing time"
    assert reasons["#6"].startswith("not a") and "already exists" in reasons["Good one"]
    assert (await store.fetchone("SELECT COUNT(*) AS n FROM reminders")) == {"n": 1}


async def test_set_reminders_skips_what_already_exists(settings, ctx, store):
    import json

    when = _iso(settings, days=1)
    await call(settings, ctx, "set_reminder", title="Dentist", when=when)
    _, text = await call(settings, ctx, "set_reminders", reminders=[{"title": "dentist", "when": when}, {"title": "Dentist", "when": _iso(settings, days=3)}])
    data = json.loads(text)
    assert len(data["created"]) == 1 and len(data["skipped"]) == 1  # same title at a different time is allowed


async def test_set_reminders_accepts_json_string_and_enforces_limits(settings, ctx):
    import json

    ok, text = await call(settings, ctx, "set_reminders", reminders=json.dumps([{"title": "A", "when": _iso(settings, days=1)}]))
    assert ok and json.loads(text)["created"][0]["title"] == "A"
    assert "non-empty array" in (await call(settings, ctx, "set_reminders", reminders=[]))[1]
    _, text = await call(settings, ctx, "set_reminders", reminders=[{"title": f"t{i}", "when": _iso(settings, days=1, minutes=i)} for i in range(26)])
    assert "max 25" in text
    assert "must be an array" in (await call(settings, ctx, "set_reminders", reminders="not json"))[1]


async def test_every_batched_reminder_fires(settings, ctx, store):
    items = [{"title": f"Task {i}", "when": _iso(settings, minutes=10 + i)} for i in range(4)]
    await call(settings, ctx, "set_reminders", reminders=items)
    await store.execute("UPDATE reminders SET due_at = ?", ((timeutil.now(settings) - timedelta(minutes=1)).isoformat(),))
    assert await ReminderScheduler(store, settings).tick() == 4
    assert [n["body"] for n in await store.fetchall("SELECT body FROM notifications ORDER BY id")] == [f"Task {i}" for i in range(4)]


# ── search across all past conversations ────────────────────────────
async def _seed_episode(store, session, user, assistant, days_ago=0):
    from datetime import datetime, timezone

    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    await store.execute(
        'INSERT INTO episodes (session_id, "timestamp", user_text, assistant_text, emotional_state) VALUES (?,?,?,?,?)',
        (session, ts, user, assistant, "neutral"),
    )


async def test_search_history_finds_older_conversations_in_any_session(settings, ctx, store):
    import json

    await _seed_episode(store, "last-month", "let's plan the quarterly budget review", "Sure: Friday works for the budget review.", days_ago=30)
    await _seed_episode(store, "last-week", "what's a good pasta recipe", "Try cacio e pepe.", days_ago=7)
    await _seed_episode(store, "yesterday", "move the budget meeting to Monday", "Done, budget meeting is Monday.", days_ago=1)
    ok, text = await call(settings, ctx, "search_history", query="quarterly budget review")
    hits = json.loads(text)
    assert ok and [h["conversation"] for h in hits] == ["last-month", "yesterday"]  # chronological; pasta not matched
    assert hits[0]["when"][:4].isdigit() and "budget" in hits[0]["assistant"]
    # best match first when trimmed to one result
    assert json.loads((await call(settings, ctx, "search_history", query="quarterly budget review", limit=1))[1])[0]["conversation"] == "last-month"
    # date window
    recent = json.loads((await call(settings, ctx, "search_history", query="budget", days=3))[1])
    assert [h["conversation"] for h in recent] == ["yesterday"]
    assert "Nothing in past conversations" in (await call(settings, ctx, "search_history", query="submarine"))[1]


async def test_search_history_clips_long_messages_and_ignores_stopword_noise(settings, ctx, store):
    import json

    await _seed_episode(store, "s", "x " * 600 + "zebra", "ok")
    hit = json.loads((await call(settings, ctx, "search_history", query="zebra"))[1])[0]
    assert len(hit["user"]) <= 320 and hit["user"].endswith("…")
    assert "Nothing" in (await call(settings, ctx, "search_history", query="is it"))[1]  # words <3 chars carry no signal
