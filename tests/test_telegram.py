"""Telegram: setup, pairing, security (strangers, forged buttons, token leakage, replays), chat, reminders, snooze, the API."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from src.agent import actions, timeutil
from src.agent.notifier import Notifier
from src.config.settings import Settings
from src.integrations import telegram as tg
from src.integrations.telegram import TelegramBridge, TelegramError, split_message
from src.interfaces.websocket_api import create_api
from src.storage.sqlite_store import SQLiteStore

TOKEN = "123456789:" + "A" * 35  # obviously fake; built at runtime so secret scanners do not flag a token-shaped literal
OWNER = 4242
STRANGER = 777


class FakeTelegram:
    """Records every Bot API call. Fails on demand."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.fail: dict[str, tuple[int, dict]] = {}
        self.valid_tokens = {TOKEN}
        self.network_error: Exception | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.network_error:
            raise self.network_error
        token, method = request.url.path.lstrip("/").removeprefix("bot").split("/", 1)
        payload = json.loads(request.content or b"{}")
        self.calls.append((method, payload))
        if token not in self.valid_tokens:
            return httpx.Response(401, json={"ok": False, "description": "Unauthorized"})
        if method in self.fail:
            status, body = self.fail[method]
            return httpx.Response(status, json=body)
        if method == "getMe":
            return httpx.Response(200, json={"ok": True, "result": {"id": 123456789, "username": "tapan_test_bot", "first_name": "Tapan"}})
        return httpx.Response(200, json={"ok": True, "result": {"message_id": len(self.calls)}})

    def of(self, method):
        return [p for m, p in self.calls if m == method]

    def texts(self, chat_id=None):
        return [p["text"] for p in self.of("sendMessage") if chat_id is None or p["chat_id"] == chat_id]


@pytest.fixture
def api_fake():
    return FakeTelegram()


@pytest.fixture
def settings():
    return Settings(llm_provider="mock", environment="local", sqlite_path=":memory:", timezone="UTC")


@pytest.fixture
async def store():
    s = SQLiteStore(":memory:")
    await s.initialize()
    return s


@pytest.fixture
async def http(api_fake):
    async with httpx.AsyncClient(transport=httpx.MockTransport(api_fake)) as client:
        yield client


@pytest.fixture
async def bridge(store, settings, http):
    b = TelegramBridge(store, settings, http)
    calls = []

    async def handler(session, text):
        calls.append((session, text))
        return f"echo: {text}"
    b.handler, b.handler_calls = handler, calls
    return b


async def linked(bridge, api_fake, chat_id=OWNER):
    await bridge.set_token(TOKEN)
    pairing = await bridge.create_pairing()
    assert await bridge._try_pair(pairing["code"], {"id": chat_id, "first_name": "Tapan", "last_name": "K"})   # no update id consumed
    assert (await bridge.linked_chat())["chat_id"] == chat_id
    api_fake.calls.clear()


_uid = iter(range(1, 10**6))


def msg(update_id, chat_id, text=None, chat_type="private", **extra):
    m = {"message_id": next(_uid), "chat": {"id": chat_id, "type": chat_type, "first_name": "Tapan", "last_name": "K"}, **extra}
    if text is not None:
        m["text"] = text
    return {"update_id": update_id, "message": m}


def callback(update_id, chat_id, data):
    return {"update_id": update_id, "callback_query": {"id": f"cq{update_id}", "data": data, "message": {"message_id": 9, "chat": {"id": chat_id, "type": "private"}}}}


# ── token ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("bad", ["", "abc", "123:short", "not a token at all", "12345:" + "x" * 30 + " ", "1" * 20 + ":" + "a" * 35, "123456789:" + "a" * 100])
async def test_malformed_tokens_are_rejected_without_any_network_call(bridge, api_fake, bad):
    with pytest.raises(TelegramError, match="does not look like a bot token"):
        await bridge.set_token(bad)
    assert api_fake.calls == []


async def test_a_valid_token_is_verified_with_getme_stored_and_never_echoed(bridge, api_fake, store):
    bot = await bridge.set_token(f"  {TOKEN}  ")
    assert bot["username"] == "tapan_test_bot" and [m for m, _ in api_fake.calls] == ["getMe"]
    assert (await store.fetchone("SELECT value FROM app_settings WHERE id = 'telegram_token'"))["value"] == TOKEN
    status = await bridge.status()
    assert status["configured"] and status["bot"] == "tapan_test_bot" and not status["linked"]
    assert TOKEN not in json.dumps(status) and TOKEN.split(":")[1] not in json.dumps(status)


async def test_a_token_telegram_rejects_is_not_stored(bridge, api_fake, store):
    api_fake.valid_tokens = set()
    with pytest.raises(TelegramError, match="Unauthorized"):
        await bridge.set_token(TOKEN)
    assert (await store.fetchone("SELECT COUNT(*) AS n FROM app_settings"))["n"] == 0 and not await bridge.configured()


async def test_environment_token_wins_over_the_stored_one(store, settings, http, api_fake):
    stored = TelegramBridge(store, settings, http)
    await stored.set_token(TOKEN)
    env_token = "987654321:" + "B" * 35
    api_fake.valid_tokens.add(env_token)
    env = TelegramBridge(store, settings.model_copy(update={"telegram_bot_token": env_token}), http)
    assert await env.token() == env_token and (await env.status())["from_env"] is True


async def test_errors_never_contain_the_token(bridge, api_fake):
    await bridge.set_token(TOKEN)
    api_fake.fail["sendMessage"] = (400, {"ok": False, "description": f"Bad Request: chat not found for bot {TOKEN}"})
    with pytest.raises(TelegramError) as info:
        await bridge._call("sendMessage", {"chat_id": 1, "text": "x"})
    assert TOKEN not in str(info.value) and "***" in str(info.value)
    api_fake.fail.clear()
    api_fake.network_error = httpx.ConnectError(f"connection failed to https://api.telegram.org/bot{TOKEN}/sendMessage")
    with pytest.raises(TelegramError) as info:
        await bridge._call("sendMessage", {"chat_id": 1, "text": "x"})
    assert TOKEN not in str(info.value) and "ConnectError" in str(info.value)


async def test_rate_limits_are_retried_once(bridge, api_fake, monkeypatch):
    await bridge.set_token(TOKEN)
    sleeps = []
    real_sleep = asyncio.sleep
    monkeypatch.setattr(tg.asyncio, "sleep", lambda s: (sleeps.append(s), real_sleep(0))[1])
    api_fake.fail["sendMessage"] = (429, {"ok": False, "description": "Too Many Requests", "parameters": {"retry_after": 99}})
    with pytest.raises(TelegramError, match="rate limiting|Too Many"):
        await bridge._call("sendMessage", {"chat_id": 1, "text": "x"})
    assert sleeps == [5] and len(api_fake.of("sendMessage")) == 2             # waited (capped at 5 s), retried once, then gave up


# ── splitting ───────────────────────────────────────────────────────
def test_split_message_keeps_everything_and_respects_the_limit():
    assert split_message("hi") == ["hi"] and split_message("   ") == ["…"]
    para = ("word " * 300).strip()
    text = "\n\n".join([para] * 5)
    parts = split_message(text)
    assert len(parts) > 1 and all(0 < len(p) <= tg.MAX_MESSAGE for p in parts)
    assert " ".join(" ".join(parts).split()) == " ".join(text.split())          # nothing lost or duplicated
    blob = "x" * (tg.MAX_MESSAGE * 2 + 10)                                          # no whitespace at all: hard cut
    assert [len(p) for p in split_message(blob)] == [tg.MAX_MESSAGE, tg.MAX_MESSAGE, 10]


# ── webhook registration ────────────────────────────────────────────
@pytest.mark.parametrize("base", ["http://tapan.example.com", "http://localhost:8000", "tapan.example.com", "", "ftp://x"])
async def test_webhook_needs_a_public_https_address(bridge, base):
    await bridge.set_token(TOKEN)
    with pytest.raises(TelegramError, match="public https"):
        await bridge.ensure_webhook(base)


async def test_webhook_registration_payload(bridge, api_fake):
    await bridge.set_token(TOKEN)
    await bridge.ensure_webhook("https://tapan.example.com/")
    payload = api_fake.of("setWebhook")[0]
    secret = await bridge.webhook_secret()
    assert payload["url"] == "https://tapan.example.com/telegram/webhook" and payload["secret_token"] == secret
    assert set(payload["allowed_updates"]) == {"message", "callback_query"}
    assert 1 <= len(secret) <= 256 and all(c.isalnum() or c in "-_" for c in secret) and TOKEN not in secret
    assert secret == await bridge.webhook_secret()                                  # stable across calls and restarts


# ── pairing ─────────────────────────────────────────────────────────
async def test_pairing_links_exactly_one_chat_once(bridge, api_fake):
    await bridge.set_token(TOKEN)
    pairing = await bridge.create_pairing()
    assert len(pairing["code"]) == 8 and pairing["link"] == f"https://t.me/tapan_test_bot?start={pairing['code']}"
    await bridge.handle_update(msg(1, OWNER, f"/start {pairing['code'].lower()}"))       # case-insensitive
    assert (await bridge.linked_chat())["chat_id"] == OWNER and "Linked" in api_fake.texts(OWNER)[-1]
    await bridge.handle_update(msg(2, STRANGER, f"/start {pairing['code']}"))
    assert (await bridge.linked_chat())["chat_id"] == OWNER                               # single use: the code cannot link a second chat
    assert api_fake.texts(STRANGER) == ["This is a private assistant."]


async def test_expired_wrong_and_brute_forced_codes_fail(bridge, api_fake, store):
    await bridge.set_token(TOKEN)
    p = await bridge.create_pairing()
    await bridge.handle_update(msg(1, STRANGER, "/start WRONGCODE"))
    assert await bridge.linked_chat() is None
    row = json.loads((await store.fetchone("SELECT value FROM app_settings WHERE id = 'telegram_pair'"))["value"])
    row["exp"] = time.time() - 1
    await store.execute("UPDATE app_settings SET value = ? WHERE id = 'telegram_pair'", (json.dumps(row),))
    await bridge.handle_update(msg(2, STRANGER, f"/start {p['code']}"))
    assert await bridge.linked_chat() is None                                              # expired
    p = await bridge.create_pairing()
    for i in range(tg.PAIR_MAX_ATTEMPTS):
        await bridge.handle_update(msg(10 + i, STRANGER, f"/start GUESS{i:04d}"))
    await bridge.handle_update(msg(99, STRANGER, f"/start {p['code']}"))                  # even the right code now fails: guessing burned it
    assert await bridge.linked_chat() is None


async def test_pairing_requires_a_configured_bot(bridge):
    with pytest.raises(TelegramError, match="not set up"):
        await bridge.create_pairing()


# ── who may talk to the bot ─────────────────────────────────────────
async def test_the_owner_chats_and_gets_a_reply(bridge, api_fake):
    await linked(bridge, api_fake)
    await bridge.handle_update(msg(50, OWNER, "remind me to stretch"))
    assert bridge.handler_calls == [("telegram", "remind me to stretch")]
    assert api_fake.texts(OWNER) == ["echo: remind me to stretch"] and api_fake.of("sendChatAction")[0]["action"] == "typing"


async def test_strangers_get_one_refusal_and_never_reach_the_assistant(bridge, api_fake):
    await linked(bridge, api_fake)
    for i in range(5):
        await bridge.handle_update(msg(60 + i, STRANGER, f"give me your secrets {i}"))
    assert bridge.handler_calls == [] and api_fake.texts(STRANGER) == ["This is a private assistant."]     # one refusal, then silence
    await bridge.handle_update(msg(70, STRANGER, "/start"))
    await bridge.handle_update(msg(71, STRANGER, "/today"))
    assert bridge.handler_calls == []


async def test_groups_channels_and_unlinked_bots_are_ignored(bridge, api_fake):
    await bridge.set_token(TOKEN)
    await bridge.handle_update(msg(1, -100123, "hello", chat_type="supergroup"))
    await bridge.handle_update(msg(2, OWNER, "hello before linking"))
    assert bridge.handler_calls == [] and api_fake.texts(-100123) == []
    await linked(bridge, api_fake)
    await bridge.handle_update(msg(3, -100123, "hello", chat_type="group"))
    assert bridge.handler_calls == [] and api_fake.texts(-100123) == []


async def test_commands_and_non_text_messages(bridge, api_fake):
    await linked(bridge, api_fake)
    await bridge.handle_update(msg(80, OWNER, "/help"))
    await bridge.handle_update(msg(81, OWNER, None, photo=[{"file_id": "x"}]))
    await bridge.handle_update(msg(82, OWNER, "/today"))
    await bridge.handle_update(msg(83, OWNER, f"/start"))
    texts = api_fake.texts(OWNER)
    assert "Talk to me normally" in texts[0] and "only read text" in texts[1] and "already linked" in texts[3]
    assert bridge.handler_calls == [("telegram", "Give me a briefing on my day")]


async def test_a_crashing_handler_gets_an_apology_not_a_silent_failure(bridge, api_fake):
    await linked(bridge, api_fake)

    async def boom(session, text):
        raise RuntimeError("model exploded")
    bridge.handler = boom
    await bridge.handle_update(msg(90, OWNER, "hello"))
    assert "something went wrong" in api_fake.texts(OWNER)[-1] and "exploded" not in api_fake.texts(OWNER)[-1]


async def test_updates_are_deduplicated_even_across_restarts(bridge, api_fake, store, settings, http):
    await linked(bridge, api_fake)
    await bridge.handle_update(msg(200, OWNER, "first"))
    await bridge.handle_update(msg(200, OWNER, "first"))        # Telegram redelivers when our 200 was slow (cold start)
    await bridge.handle_update(msg(150, OWNER, "older"))
    assert [t for _, t in bridge.handler_calls] == ["first"]
    restarted = TelegramBridge(store, settings, http, handler=bridge.handler)
    await restarted.handle_update(msg(200, OWNER, "first"))
    await restarted.handle_update(msg(201, OWNER, "second"))
    assert [t for _, t in bridge.handler_calls] == ["first", "second"]


# ── snooze buttons ──────────────────────────────────────────────────
async def _reminder(store, settings, title="Call mom"):
    return await store.execute("INSERT INTO reminders (session_id, title, due_at, status, created_at) VALUES ('s', ?, ?, 'fired', 't')",
                               (title, (timeutil.now(settings) - timedelta(minutes=1)).isoformat()))


async def _button(bridge, rid, minutes=10):
    return f"z:{minutes}:{rid}:{(await bridge._signer()).sign('snooze', rid, minutes)}"


async def test_a_valid_snooze_button_creates_a_one_off_reminder(bridge, api_fake, store, settings):
    await linked(bridge, api_fake)
    rid = await _reminder(store, settings)
    await bridge.handle_update(callback(300, OWNER, await _button(bridge, rid, 10)))
    pending = await store.fetchall("SELECT title, due_at FROM reminders WHERE status = 'pending'")
    assert len(pending) == 1 and pending[0]["title"] == "Call mom"
    due = timeutil.as_aware(pending[0]["due_at"], settings)
    assert timedelta(minutes=9) < due - timeutil.now(settings) < timedelta(minutes=11)
    assert "Snoozed until" in api_fake.of("answerCallbackQuery")[0]["text"]
    assert api_fake.of("editMessageReplyMarkup")[0]["reply_markup"] == {"inline_keyboard": []}     # buttons removed: no double tap
    assert (await store.fetchone("SELECT status FROM reminders WHERE id = ?", (rid,)))["status"] == "fired"    # the original is untouched


async def test_forged_expired_or_foreign_buttons_do_nothing(bridge, api_fake, store, settings):
    await linked(bridge, api_fake)
    rid = await _reminder(store, settings)
    good = await _button(bridge, rid, 10)
    signer = await bridge._signer()
    cases = {
        "tampered signature": good[:-3] + "AAA", "other reminder id": f"z:10:{rid + 1}:{good.rsplit(':', 1)[1]}",
        "longer snooze than signed": f"z:60:{rid}:{good.rsplit(':', 1)[1]}", "garbage": "z:what", "empty": "",
        "unoffered length, validly signed": f"z:5:{rid}:{signer.sign('snooze', rid, 5)}",
        "signed with another secret": f"z:10:{rid}:{actions.ActionSigner(b'attacker').sign('snooze', rid, 10)}",
    }
    for i, (label, data) in enumerate(cases.items()):
        await bridge.handle_update(callback(400 + i, OWNER, data))
        assert (await store.fetchone("SELECT COUNT(*) AS n FROM reminders WHERE status = 'pending'"))["n"] == 0, label
    assert all("not valid" in p["text"] for p in api_fake.of("answerCallbackQuery"))


async def test_buttons_from_another_chat_are_refused(bridge, api_fake, store, settings):
    await linked(bridge, api_fake)
    rid = await _reminder(store, settings)
    await bridge.handle_update(callback(500, STRANGER, await _button(bridge, rid)))
    assert (await store.fetchone("SELECT COUNT(*) AS n FROM reminders WHERE status = 'pending'"))["n"] == 0
    assert api_fake.of("answerCallbackQuery")[0]["text"] == "Not allowed."


async def test_snoozing_twice_or_a_deleted_reminder_is_harmless(bridge, api_fake, store, settings):
    await linked(bridge, api_fake)
    rid = await _reminder(store, settings)
    await bridge.handle_update(callback(600, OWNER, await _button(bridge, rid)))
    await bridge.handle_update(callback(601, OWNER, await _button(bridge, rid)))               # a double tap
    assert (await store.fetchone("SELECT COUNT(*) AS n FROM reminders WHERE status = 'pending'"))["n"] == 1
    await store.execute("DELETE FROM reminders WHERE id = ?", (rid,))
    await bridge.handle_update(callback(602, OWNER, await _button(bridge, rid, 60)))
    assert "no longer exists" in api_fake.of("answerCallbackQuery")[-1]["text"]


# ── reminders out ───────────────────────────────────────────────────
def _rows(settings, n, minutes_late=0):
    now = timeutil.now(settings)
    return [{"id": i + 1, "title": f"Thing {i}", "due": now - timedelta(minutes=minutes_late)} for i in range(n)], now


async def test_nothing_is_sent_until_telegram_is_set_up_and_linked(bridge, api_fake, settings):
    rows, now = _rows(settings, 2)
    assert await bridge.notify_reminders(rows, now) == {"sent": 0, "removed": 0, "failed": 0} and api_fake.calls == []
    await bridge.set_token(TOKEN)
    api_fake.calls.clear()
    assert (await bridge.notify_reminders(rows, now))["sent"] == 0 and api_fake.calls == []


async def test_each_reminder_arrives_with_working_snooze_buttons(bridge, api_fake, settings):
    await linked(bridge, api_fake)
    rows, now = _rows(settings, 2, minutes_late=40)
    assert (await bridge.notify_reminders(rows, now))["sent"] == 2
    sent = api_fake.of("sendMessage")
    assert sent[0]["text"].startswith("⏰ Thing 0 · was due ")
    keyboard = sent[0]["reply_markup"]["inline_keyboard"][0]
    assert [b["text"] for b in keyboard] == ["Snooze 10 min", "Snooze 1 h"]
    signer = await bridge._signer()
    for b in keyboard:
        assert len(b["callback_data"].encode()) <= 64                                          # Telegram's hard limit
        _, m, rid, sig = b["callback_data"].split(":")
        assert signer.verify("snooze", int(rid), int(m), sig)


async def test_a_burst_is_one_message_without_buttons(bridge, api_fake, settings):
    await linked(bridge, api_fake)
    rows, now = _rows(settings, 7)
    assert (await bridge.notify_reminders(rows, now))["sent"] == 1
    only = api_fake.of("sendMessage")
    assert len(only) == 1 and "7 reminders" in only[0]["text"] and "reply_markup" not in only[0]


async def test_delivery_failures_are_counted_not_raised(bridge, api_fake, settings):
    await linked(bridge, api_fake)
    api_fake.fail["sendMessage"] = (403, {"ok": False, "description": "Forbidden: bot was blocked by the user"})
    rows, now = _rows(settings, 2)
    assert await bridge.notify_reminders(rows, now) == {"sent": 0, "removed": 0, "failed": 2}
    assert "blocked by the user" in (await bridge.status())["last_error"]


async def test_one_failing_channel_does_not_block_the_others(settings):
    class Ok:
        async def notify_reminders(self, rows, now):
            return {"sent": 3, "removed": 0, "failed": 0}

    class Broken:
        async def notify_reminders(self, rows, now):
            raise RuntimeError("down")
    result = await Notifier(push=Broken(), telegram=Ok(), none=None).notify_reminders([], timeutil.now(settings))
    assert result["telegram"]["sent"] == 3 and result["push"]["failed"] == 1 and "none" not in result


# ── the HTTP API ────────────────────────────────────────────────────
@pytest.fixture
def served(monkeypatch):
    """The real app with a fake Telegram behind it. Yields (client, fake, runtime)."""
    from src.main import build_runtime

    monkeypatch.delenv("RENDER_EXTERNAL_URL", raising=False)
    settings = Settings(llm_provider="mock", environment="local", sqlite_path=":memory:", intent_classifier="heuristic", timezone="UTC",
                        public_url="https://tapan.example.com")
    runtime = asyncio.run(build_runtime(settings))
    fake = FakeTelegram()
    runtime.telegram.http = httpx.AsyncClient(transport=httpx.MockTransport(fake))

    async def echo(session, text):
        return f"echo: {text}"
    runtime.telegram.handler = echo
    with TestClient(create_api(runtime.orchestrator, settings, runtime.health_checker, runtime=runtime)) as client:
        yield client, fake, runtime


def wait_for(predicate, seconds=3.0):
    end = time.time() + seconds
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_the_webhook_only_accepts_telegram(served):
    client, fake, runtime = served
    assert client.post("/api/telegram/token", json={"token": TOKEN}).status_code == 200
    secret = asyncio.run(runtime.telegram.webhook_secret())
    update = msg(1, OWNER, "hi")
    assert client.post("/telegram/webhook", json=update).status_code == 403
    assert client.post("/telegram/webhook", json=update, headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"}).status_code == 403
    assert client.post("/telegram/webhook", json=update, headers={"X-Telegram-Bot-Api-Secret-Token": secret + "x"}).status_code == 403
    assert client.post("/telegram/webhook", content=b"x" * 70_000, headers={"X-Telegram-Bot-Api-Secret-Token": secret}).status_code == 413
    assert client.post("/telegram/webhook", content=b"{nope", headers={"X-Telegram-Bot-Api-Secret-Token": secret}).status_code == 400
    assert client.post("/telegram/webhook", json=update, headers={"X-Telegram-Bot-Api-Secret-Token": secret}).json() == {"ok": True}


def test_the_webhook_is_closed_until_a_bot_is_configured(served):
    client, fake, runtime = served
    assert client.post("/telegram/webhook", json=msg(1, OWNER, "hi"), headers={"X-Telegram-Bot-Api-Secret-Token": ""}).status_code == 403


def test_setup_routes_require_the_token():
    from src.main import build_runtime

    settings = Settings(llm_provider="mock", environment="local", sqlite_path=":memory:", intent_classifier="heuristic", api_token="s3cret")
    runtime = asyncio.run(build_runtime(settings))
    with TestClient(create_api(runtime.orchestrator, settings, runtime.health_checker, runtime=runtime)) as c:
        for method, url in [("get", "/api/telegram/status"), ("post", "/api/telegram/token"), ("delete", "/api/telegram/token"),
                            ("post", "/api/telegram/pair"), ("post", "/api/telegram/unlink"), ("post", "/api/telegram/test")]:
            assert getattr(c, method)(url, **({"json": {"token": TOKEN}} if method == "post" and url.endswith("token") else {})).status_code == 401, url


def test_the_whole_journey_over_http(served):
    client, fake, runtime = served
    assert client.get("/api/telegram/status").json()["configured"] is False
    bad = client.post("/api/telegram/token", json={"token": "nonsense"})
    assert bad.status_code == 400 and "bot token" in bad.json()["detail"]
    ok = client.post("/api/telegram/token", json={"token": TOKEN}).json()
    assert ok["ok"] and ok["bot"] == "tapan_test_bot" and ok["webhook"] is True
    hook = fake.of("setWebhook")[0]
    assert hook["url"] == "https://tapan.example.com/telegram/webhook" and hook["secret_token"]

    status = client.get("/api/telegram/status").json()
    assert status["configured"] and not status["linked"] and TOKEN not in json.dumps(status)
    assert client.post("/api/telegram/test").status_code == 409                       # nobody linked yet: say so

    pairing = client.post("/api/telegram/pair").json()
    assert pairing["link"].startswith("https://t.me/tapan_test_bot?start=") and pairing["webhook"] is True
    secret = {"X-Telegram-Bot-Api-Secret-Token": asyncio.run(runtime.telegram.webhook_secret())}
    client.post("/telegram/webhook", json=msg(1, OWNER, f"/start {pairing['code']}"), headers=secret)
    assert wait_for(lambda: client.get("/api/telegram/status").json()["linked"])
    assert client.get("/api/telegram/status").json()["linked_name"] == "Tapan K"

    client.post("/telegram/webhook", json=msg(2, OWNER, "what's up"), headers=secret)
    assert wait_for(lambda: "echo: what's up" in fake.texts(OWNER))                    # answered in the background, not in the HTTP response
    assert client.post("/api/telegram/test").json() == {"ok": True}
    assert "Tapan is connected" in fake.texts(OWNER)[-1]

    client.post("/api/telegram/unlink")
    assert client.get("/api/telegram/status").json()["linked"] is False
    client.post("/telegram/webhook", json=msg(3, OWNER, "still there?"), headers=secret)
    assert wait_for(lambda: "This is a private assistant." in fake.texts(OWNER))      # unlinking really cuts access
    client.delete("/api/telegram/token")
    assert client.get("/api/telegram/status").json()["configured"] is False
    assert client.post("/telegram/webhook", json=msg(4, OWNER, "x"), headers=secret).status_code == 403


def test_http_addresses_fail_with_a_clear_message_but_the_token_is_still_saved(monkeypatch):
    from src.main import build_runtime

    monkeypatch.delenv("RENDER_EXTERNAL_URL", raising=False)
    settings = Settings(llm_provider="mock", environment="local", sqlite_path=":memory:", intent_classifier="heuristic")
    runtime = asyncio.run(build_runtime(settings))
    runtime.telegram.http = httpx.AsyncClient(transport=httpx.MockTransport(FakeTelegram()))
    with TestClient(create_api(runtime.orchestrator, settings, runtime.health_checker, runtime=runtime)) as c:
        out = c.post("/api/telegram/token", json={"token": TOKEN}).json()
        assert out["ok"] is True and out["webhook"] is False and "public https" in out["webhook_error"]
        forwarded = c.post("/api/telegram/pair", headers={"x-forwarded-proto": "https", "x-forwarded-host": "tapan.onrender.com"}).json()
        assert forwarded["webhook"] is True                                              # derived from the proxy headers behind Render


def test_setup_attempts_are_rate_limited(served):
    client, fake, runtime = served
    codes = [client.post("/api/telegram/token", json={"token": "x"}).status_code for _ in range(40)]
    assert 429 in codes and codes[0] == 400


async def test_the_morning_briefing_reaches_telegram_only_once_linked(bridge, api_fake):
    assert await bridge.notify_digest("Good morning · Wed 25 Nov", "Due today: ₹1,200") == {"sent": 0, "removed": 0, "failed": 0} and api_fake.calls == []
    await linked(bridge, api_fake)
    api_fake.calls.clear()
    assert (await bridge.notify_digest("Good morning · Wed 25 Nov", "Due today: ₹1,200"))["sent"] == 1
    assert api_fake.of("sendMessage")[0]["text"] == "☀️ Good morning · Wed 25 Nov\nDue today: ₹1,200"
