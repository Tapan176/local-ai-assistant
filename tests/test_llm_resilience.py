"""When the AI provider fails (no credit, bad key, rate limit, outage) the app must say so plainly, fail fast, keep trying cheaper routes,
and never fall back to something that changes data on a guess. All keys and names here are invented."""

from __future__ import annotations

import json
import time

import httpx
import pytest

from src.agent import digest, workspace
from src.agent.service import AgentOrchestrator
from src.config.settings import Settings
from src.llm.chat_client import DEFAULT_MAX_TOKENS, ChatClient
from src.storage.sqlite_store import SQLiteStore

MSG = [{"role": "user", "content": "hi"}]


def make(handler, **overrides):
    s = Settings(llm_provider="openrouter", openrouter_api_key="test-key-not-real", environment="local", sqlite_path=":memory:",
                 ollama_url="http://127.0.0.1:9/api/chat", **overrides)
    return ChatClient(s, httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def ok(model="m"):
    return httpx.Response(200, json={"choices": [{"message": {"content": "hello"}}]})


async def test_no_credit_is_explained_and_not_retried_on_every_message():
    calls = []

    def handler(req):
        if "openrouter" in str(req.url):
            calls.append(json.loads(req.content)["model"])
        return httpx.Response(402, json={"error": {"message": "Insufficient credits", "code": 402}})

    c = make(handler, openrouter_model="paid/a", openrouter_fallback_model="paid/b", openrouter_free_model="")
    assert await c.complete(MSG) is None
    assert calls == ["paid/a", "paid/b"]
    assert "out of credit" in c.explain_failure() and "openrouter.ai/credits" in c.explain_failure()
    before = len(calls)
    assert await c.complete(MSG) is None                                  # the second message does not hammer a provider that said 402
    assert len(calls) == before
    assert c._cooldown["openrouter:paid/a"] - time.monotonic() > 500      # a long pause for credit problems, not the usual minute


async def test_a_free_model_is_the_last_resort_when_the_paid_ones_are_refused():
    seen = []

    def handler(req):
        model = json.loads(req.content)["model"]
        seen.append(model)
        return ok() if model == "openrouter/free" else httpx.Response(402, json={"error": {"message": "Insufficient credits"}})

    c = make(handler, openrouter_model="paid/a", openrouter_fallback_model="paid/b")
    got = await c.complete(MSG)
    assert got and got.content == "hello" and got.model == "openrouter/free" and seen == ["paid/a", "paid/b", "openrouter/free"]
    assert c.explain_failure() == ""                                      # a success clears the problem


async def test_the_free_model_can_be_switched_off():
    seen = []

    def handler(req):
        seen.append(json.loads(req.content)["model"])
        return httpx.Response(500)

    c = make(handler, openrouter_model="paid/a", openrouter_fallback_model="paid/b", openrouter_free_model="")
    await c.complete(MSG)
    assert "openrouter/free" not in seen


@pytest.mark.parametrize("status,words", [(401, "rejected the API key"), (403, "rejected the API key"), (429, "rate limiting"), (500, "returned errors")])
async def test_each_failure_kind_has_its_own_plain_explanation(status, words):
    c = make(lambda req: httpx.Response(status), openrouter_free_model="")
    assert await c.complete(MSG) is None
    assert words in c.explain_failure()


async def test_a_network_failure_is_explained_as_such():
    def handler(req):
        raise httpx.ConnectError("no route")

    c = make(handler, openrouter_free_model="")
    assert await c.complete(MSG) is None and "network" in c.explain_failure()


async def test_replies_never_ask_for_the_models_whole_window():
    sent = {}

    def handler(req):
        sent.update(json.loads(req.content))
        return ok()

    await make(handler).complete(MSG)
    assert sent["max_tokens"] == DEFAULT_MAX_TOKENS


async def test_a_small_balance_gets_a_smaller_request_instead_of_an_error():
    limits = []

    def handler(req):
        body = json.loads(req.content)
        limits.append(body["max_tokens"])
        if body["max_tokens"] > 900:
            return httpx.Response(402, json={"error": {"message": "This request requires more credits, or fewer max_tokens. You requested up to 2048 tokens, but can only afford 900."}})
        return ok()

    got = await make(handler).complete(MSG)
    assert got and got.content == "hello" and limits == [2048, 880]


async def test_a_pictures_failure_is_explained_too():
    c = make(lambda req: httpx.Response(402), openrouter_free_model="")
    assert await c.complete_vision(MSG) is None and "out of credit" in c.explain_failure()


# ── what the user sees when the AI is down ─────────────────────────────
class DeadLLM:
    configured = True

    def __init__(self, why):
        self.why = why

    def explain_failure(self):
        return self.why

    async def complete(self, *a, **k):
        return None


class Legacy:
    called = 0

    async def handle_user_input(self, session_id, user_text):
        Legacy.called += 1
        raise AssertionError("the legacy pipeline must not run when the AI is down")


@pytest.fixture
async def facade():
    import httpx as _httpx

    from src.agent.loop import AgentLoop
    from src.agent.skill import SkillContext
    from src.agent.skills import build_registry

    store = SQLiteStore(":memory:")
    await store.initialize()
    settings = Settings(llm_provider="openrouter", openrouter_api_key="k", environment="local", sqlite_path=":memory:", timezone="Asia/Kolkata", currency="INR")
    async with _httpx.AsyncClient() as http:
        loop = AgentLoop(settings, DeadLLM("The AI provider (OpenRouter) says the account is out of credit."), build_registry(settings), store,
                         lambda sid: SkillContext(settings, store, http, sid))
        yield AgentOrchestrator(settings, loop, Legacy(), type("E", (), {"add_turn": staticmethod(lambda t: None)})()), store, settings


@pytest.mark.parametrize("text", ["I spent 500 on lunch", "add task buy milk", "remind me to call mom tomorrow at 5pm", "what is the weather"])
async def test_nothing_is_changed_and_the_reason_is_given_when_the_ai_is_down(facade, text):
    orch, store, _ = facade
    reply = await orch.handle_user_input("s", text)
    assert "basic mode" in reply.text and "out of credit" in reply.text and "not changed anything" in reply.text
    assert Legacy.called == 0
    for table in ("reminders", "tasks", "financial_transactions", "ex_spend", "memories"):
        assert (await store.fetchone(f"SELECT COUNT(*) AS n FROM {table}"))["n"] == 0, table


async def test_a_briefing_request_still_gets_a_real_answer_from_your_own_data(facade):
    orch, store, settings = facade
    await workspace.create_task(store, settings, title="Call the vendor", due=workspace.timeutil.now(settings).date().isoformat())
    reply = await orch.handle_user_input("s", "Give me a briefing on my day")
    assert "basic mode" in reply.text and "Here is your day, from your own data" in reply.text and "Call the vendor" in reply.text
    assert reply.text.count("Good morning") == 1 and "remember about you" not in reply.text


async def test_the_mock_provider_keeps_the_legacy_pipeline_for_offline_development():
    s = Settings(llm_provider="mock", environment="local", sqlite_path=":memory:")
    from src.main import build_runtime

    rt = await build_runtime(s)
    reply = await rt.orchestrator.handle_user_input("s", "hello")
    assert reply.debug.get("basic") is None and reply.text
