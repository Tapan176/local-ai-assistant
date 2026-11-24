"""Web Push for reminders: keys, subscription safety, delivery semantics, the scheduler, the API, and real crypto."""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi.testclient import TestClient

from src.agent import timeutil
from src.agent.push import (
    BATCH_THRESHOLD, PushService, WebPushException, b64d, b64e, generate_private_key, host_allowed, public_key_for,
    reminder_payloads, validate_subscription,
)
from src.agent.service import ReminderScheduler
from src.config.settings import Settings
from src.interfaces.websocket_api import create_api
from src.storage.sqlite_store import SQLiteStore


# ── fixtures ────────────────────────────────────────────────────────
def browser_subscription(endpoint="https://fcm.googleapis.com/fcm/send/abc123"):
    """What a browser's pushManager.subscribe() returns, with the private halves kept so tests can decrypt."""
    key = ec.generate_private_key(ec.SECP256R1())
    import os

    auth = os.urandom(16)
    return {
        "endpoint": endpoint,
        "keys": {"p256dh": b64e(key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)), "auth": b64e(auth)},
    }, key, auth


@pytest.fixture
def settings():
    return Settings(llm_provider="mock", environment="local", sqlite_path=":memory:", timezone="UTC", push_enabled=True)


@pytest.fixture
async def store():
    s = SQLiteStore(":memory:")
    await s.initialize()
    return s


class FakeSender:
    """Stands in for pywebpush.webpush: records calls, optionally fails per endpoint."""

    def __init__(self):
        self.calls, self.fail = [], {}

    def __call__(self, info, data, private, claims, ttl, urgency, timeout):
        self.calls.append({"info": info, "data": json.loads(data), "claims": dict(claims), "ttl": ttl, "urgency": urgency, "id": id(claims)})
        outcome = self.fail.get(info["endpoint"])
        if outcome:
            raise outcome


def http_error(status):
    exc = WebPushException(f"HTTP {status}")
    exc.response = type("R", (), {"status_code": status})()
    return exc


# ── keys ────────────────────────────────────────────────────────────
async def test_keys_are_generated_once_persisted_and_valid(store, settings):
    first = PushService(store, settings, sender=FakeSender())
    pub = await first.public_key()
    raw = b64d(pub)
    assert len(raw) == 65 and raw[0] == 4                                  # uncompressed P-256 point: what browsers require
    ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)      # a real point on the curve
    second = PushService(store, settings, sender=FakeSender())             # another instance / a restart
    assert await second.public_key() == pub
    assert (await store.fetchone("SELECT COUNT(*) AS n FROM app_settings"))["n"] == 1


async def test_two_instances_racing_on_first_start_agree(store, settings):
    services = [PushService(store, settings, sender=FakeSender()) for _ in range(5)]
    keys = await asyncio.gather(*(s.public_key() for s in services))
    assert len(set(keys)) == 1 and (await store.fetchone("SELECT COUNT(*) AS n FROM app_settings"))["n"] == 1


async def test_env_key_wins_and_a_bad_one_fails_loudly(store, settings):
    private = generate_private_key()
    configured = settings.model_copy(update={"vapid_private_key": private})
    assert await PushService(store, configured, sender=FakeSender()).public_key() == public_key_for(private)
    assert (await store.fetchone("SELECT COUNT(*) AS n FROM app_settings"))["n"] == 0
    with pytest.raises(Exception):
        await PushService(store, settings.model_copy(update={"vapid_private_key": "not-a-key"}), sender=FakeSender()).public_key()


async def test_disabled_service_exposes_nothing(store, settings):
    off = PushService(store, settings.model_copy(update={"push_enabled": False}), sender=FakeSender())
    assert not off.available and await off.public_key() is None
    assert await off.send({"title": "x"}) == {"sent": 0, "removed": 0, "failed": 0}


def test_subject_is_never_an_email_taken_from_the_user(settings, monkeypatch):
    monkeypatch.delenv("RENDER_EXTERNAL_URL", raising=False)
    service = PushService(None, settings, sender=FakeSender())
    assert service.subject.startswith("mailto:") and "@tapan-ai.invalid" in service.subject
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://tapan-ai-10ps.onrender.com")
    assert service.subject == "https://tapan-ai-10ps.onrender.com"
    assert PushService(None, settings.model_copy(update={"vapid_subject": "https://me.example"}), sender=FakeSender()).subject == "https://me.example"


# ── subscription validation (SSRF + malformed input) ────────────────
@pytest.mark.parametrize("host,ok", [
    ("fcm.googleapis.com", True), ("updates.push.services.mozilla.com", True), ("web.push.apple.com", True),
    ("wns2-par02p.notify.windows.com", True), ("FCM.GOOGLEAPIS.COM.", True),
    ("evil.com", False), ("fcm.googleapis.com.evil.com", False), ("notfcm.googleapis.com.attacker.io", False),
    ("googleapis.com", False), ("localhost", False), ("127.0.0.1", False), ("169.254.169.254", False), ("xfcm.googleapis.com", False),
])
def test_host_allowlist(host, ok):
    assert host_allowed(host) is ok


@pytest.mark.parametrize("endpoint", [
    "http://fcm.googleapis.com/x",                         # not https
    "https://127.0.0.1/hook", "https://localhost/x", "https://169.254.169.254/latest/meta-data",
    "https://10.0.0.5/x", "https://evil.example.com/fcm.googleapis.com", "https://fcm.googleapis.com.evil.com/x",
    "https://user:pw@fcm.googleapis.com/x", "https://fcm.googleapis.com:8443/x", "file:///etc/passwd",
    "ftp://fcm.googleapis.com/x", "https://fcm.googleapis.com/" + "a" * 2100, "", "not a url",
])
def test_dangerous_endpoints_are_rejected(endpoint):
    sub, _, _ = browser_subscription(endpoint)
    with pytest.raises(ValueError):
        validate_subscription(sub)


def test_malformed_keys_are_rejected():
    good, _, _ = browser_subscription()
    for mutate in (
        lambda s: s.update(keys={}),
        lambda s: s["keys"].update(p256dh="AAAA"),                              # not a curve point
        lambda s: s["keys"].update(p256dh=b64e(b"\x04" + b"\x01" * 64)),        # right length, not on the curve
        lambda s: s["keys"].update(auth=b64e(b"short")),
        lambda s: s.pop("endpoint"),
        lambda s: s.update(keys="nope"),
    ):
        sub = json.loads(json.dumps(good))
        mutate(sub)
        with pytest.raises(ValueError):
            validate_subscription(sub)
    with pytest.raises(ValueError):
        validate_subscription("a string")
    assert validate_subscription(good)[0] == good["endpoint"]


async def test_subscribe_upserts_unsubscribes_and_bounds_the_table(store, settings):
    service = PushService(store, settings, sender=FakeSender())
    sub, _, _ = browser_subscription("https://fcm.googleapis.com/fcm/send/one")
    await service.subscribe(sub, "Mozilla/5.0 (Android)")
    await service.subscribe(sub, "Mozilla/5.0 (Android) v2")                   # same endpoint: updated, not duplicated
    assert await service.count() == 1
    assert (await store.fetchone("SELECT user_agent FROM push_subscriptions"))["user_agent"].endswith("v2")
    await service.unsubscribe(sub["endpoint"])
    assert await service.count() == 0
    for i in range(25):
        s, _, _ = browser_subscription(f"https://fcm.googleapis.com/fcm/send/dev{i}")
        await service.subscribe(s)
    rows = await store.fetchall("SELECT endpoint FROM push_subscriptions ORDER BY id")
    assert len(rows) == 20 and rows[-1]["endpoint"].endswith("dev24") and not any(r["endpoint"].endswith("dev0") for r in rows)
    with pytest.raises(ValueError):
        await service.subscribe({"endpoint": "https://evil.com/x", "keys": sub["keys"]})
    assert await service.count() == 20                                        # nothing slipped through


# ── delivery semantics ──────────────────────────────────────────────
async def test_send_reaches_every_device_with_a_fresh_claims_dict(store, settings):
    sender = FakeSender()
    service = PushService(store, settings, sender=sender)
    for i in range(3):
        await service.subscribe(browser_subscription(f"https://fcm.googleapis.com/fcm/send/d{i}")[0])
    result = await service.send({"title": "Reminder", "body": "Call mom"})
    assert result == {"sent": 3, "removed": 0, "failed": 0}
    assert all(c["data"]["body"] == "Call mom" and c["claims"]["sub"] == service.subject for c in sender.calls)
    assert len({c["id"] for c in sender.calls}) == 3                            # pywebpush mutates claims: never share one dict
    assert all(r["last_success_at"] for r in await store.fetchall("SELECT last_success_at FROM push_subscriptions"))


async def test_gone_subscriptions_are_removed_but_transient_errors_are_kept(store, settings):
    sender = FakeSender()
    service = PushService(store, settings, sender=sender)
    endpoints = {k: f"https://fcm.googleapis.com/fcm/send/{k}" for k in ("ok", "gone", "expired", "overloaded", "forbidden", "boom")}
    for ep in endpoints.values():
        await service.subscribe(browser_subscription(ep)[0])
    sender.fail = {
        endpoints["gone"]: http_error(410), endpoints["expired"]: http_error(404), endpoints["overloaded"]: http_error(503),
        endpoints["forbidden"]: http_error(403), endpoints["boom"]: ConnectionError("network down"),
    }
    result = await service.send({"title": "x"})
    assert result == {"sent": 1, "removed": 2, "failed": 3}
    left = {r["endpoint"].rsplit("/", 1)[1]: r["last_error"] for r in await store.fetchall("SELECT endpoint, last_error FROM push_subscriptions")}
    assert set(left) == {"ok", "overloaded", "forbidden", "boom"}               # 403 is NOT treated as gone: a config slip must not unsubscribe everyone
    assert left["overloaded"] == "HTTP 503" and "ConnectionError" in left["boom"] and left["ok"] is None


async def test_a_dead_push_service_never_raises(store, settings):
    def explode(*a, **k):
        raise RuntimeError("encryption blew up")
    service = PushService(store, settings, sender=explode)
    await service.subscribe(browser_subscription()[0])
    assert await service.send({"title": "x"}) == {"sent": 0, "removed": 0, "failed": 1}


# ── payload building ────────────────────────────────────────────────
def _row(i, title, due):
    return {"id": i, "title": title, "due": due}


def test_payload_for_an_on_time_and_a_late_reminder():
    now = timeutil.now(Settings(timezone="UTC", llm_provider="mock"))
    [on_time] = reminder_payloads([_row(1, "Call mom", now - timedelta(seconds=30))], now)
    assert on_time == {"title": "Reminder", "body": "Call mom", "tag": "reminder-1", "url": "/web/index.html?panel=today", "reminder_id": 1}
    [late] = reminder_payloads([_row(2, "Pay rent", now - timedelta(hours=2))], now)
    assert late["body"].startswith("Pay rent · was due ") and late["tag"] == "reminder-2"      # the lock screen never lies about timing


def test_a_burst_becomes_one_summary_not_a_buzz_storm():
    now = timeutil.now(Settings(timezone="UTC", llm_provider="mock"))
    few = reminder_payloads([_row(i, f"t{i}", now) for i in range(BATCH_THRESHOLD)], now)
    assert len(few) == BATCH_THRESHOLD
    many = reminder_payloads([_row(i, f"Thing {i}", now) for i in range(8)], now)
    assert len(many) == 1 and many[0]["title"] == "8 reminders" and many[0]["tag"] == "reminders-batch"
    assert many[0]["body"] == "Thing 0; Thing 1; Thing 2 and 5 more"
    long = reminder_payloads([_row(1, "x " * 500, now)], now)[0]
    assert len(long["body"]) <= 120                                                              # bounded: push payloads are limited to ~4 KB
    assert reminder_payloads([], now) == []


# ── scheduler ───────────────────────────────────────────────────────
async def _add_reminders(store, settings, n, minutes_ago=1, title="Reminder"):
    due = (timeutil.now(settings) - timedelta(minutes=minutes_ago)).isoformat()
    for i in range(n):
        await store.execute("INSERT INTO reminders (session_id, title, due_at, status, created_at) VALUES ('s', ?, ?, 'pending', 't')", (f"{title} {i}", due))


async def test_scheduler_pushes_exactly_once_per_reminder(store, settings):
    sender = FakeSender()
    push = PushService(store, settings, sender=sender)
    await push.subscribe(browser_subscription()[0])
    await _add_reminders(store, settings, 2)
    scheduler = ReminderScheduler(store, settings, push=push)
    assert await scheduler.tick() == 2
    assert sorted(c["data"]["tag"] for c in sender.calls) == ["reminder-1", "reminder-2"]
    assert await scheduler.tick() == 0 and len(sender.calls) == 2                               # nothing fires twice
    assert (await store.fetchone("SELECT COUNT(*) AS n FROM notifications"))["n"] == 2          # the in-page feed still works


async def test_two_instances_ticking_at_once_notify_once(store, settings):
    """Render runs the old and new instance side by side during a deploy; both poll the same database."""
    sender = FakeSender()
    push = PushService(store, settings, sender=sender)
    await push.subscribe(browser_subscription()[0])
    await _add_reminders(store, settings, 6)
    results = await asyncio.gather(*(ReminderScheduler(store, settings, push=push).tick() for _ in range(4)))
    assert sum(results) == 6, results                                                           # each reminder claimed by exactly one instance
    assert (await store.fetchone("SELECT COUNT(*) AS n FROM notifications"))["n"] == 6
    assert sum(1 for c in sender.calls if c["data"]["tag"].startswith("reminder-")) <= 6        # <= 6 singles, or batches: never duplicates
    tags = [c["data"]["tag"] for c in sender.calls]
    assert len(tags) == len(set(tags)), tags


async def test_burst_after_downtime_is_a_single_push(store, settings):
    sender = FakeSender()
    push = PushService(store, settings, sender=sender)
    await push.subscribe(browser_subscription()[0])
    await _add_reminders(store, settings, 7, minutes_ago=600, title="Overnight")
    await ReminderScheduler(store, settings, push=push).tick()
    assert len(sender.calls) == 1 and sender.calls[0]["data"]["title"] == "7 reminders"


async def test_push_failure_cannot_break_reminders(store, settings):
    class Broken:
        async def notify_reminders(self, rows, now):
            raise RuntimeError("push service exploded")
    await _add_reminders(store, settings, 2)
    assert await ReminderScheduler(store, settings, push=Broken()).tick() == 2
    assert (await store.fetchone("SELECT COUNT(*) AS n FROM reminders WHERE status = 'fired'"))["n"] == 2
    assert (await store.fetchone("SELECT COUNT(*) AS n FROM notifications"))["n"] == 2


async def test_scheduler_without_push_is_unchanged(store, settings):
    await _add_reminders(store, settings, 1)
    assert await ReminderScheduler(store, settings).tick() == 1


# ── the API ─────────────────────────────────────────────────────────
class Runtime:
    """Minimal stand-in for main.Runtime with just what the push routes touch."""

    def __init__(self, store, push, settings):
        self.sqlite_store, self.push, self.scheduler, self.registry = store, push, None, None
        self.settings = settings

    async def aclose(self):
        pass


class Echo:
    async def handle_user_input(self, session_id, user_text):  # pragma: no cover
        raise AssertionError


def make_client(settings, push, store, **overrides):
    cfg = settings.model_copy(update=overrides)
    return TestClient(create_api(Echo(), cfg, runtime=Runtime(store, push, cfg)))


def test_every_push_route_requires_the_token(settings):
    store = SQLiteStore(":memory:")
    asyncio.run(store.initialize())
    push = PushService(store, settings, sender=FakeSender())
    with make_client(settings, push, store, api_token="s3cret") as c:
        for method, url in [("get", "/api/push/key"), ("post", "/api/push/subscribe"), ("post", "/api/push/unsubscribe"), ("post", "/api/push/test")]:
            assert getattr(c, method)(url, **({"json": {}} if method == "post" else {})).status_code == 401, url
        assert c.get("/api/push/key", headers={"Authorization": "Bearer s3cret"}).status_code == 200


def test_subscribe_flow_and_test_notification_over_http(settings):
    store = SQLiteStore(":memory:")
    asyncio.run(store.initialize())
    sender = FakeSender()
    push = PushService(store, settings, sender=sender)
    sub, _, _ = browser_subscription()
    with make_client(settings, push, store) as c:
        key = c.get("/api/push/key").json()
        assert key["enabled"] is True and len(b64d(key["public_key"])) == 65
        assert c.post("/api/push/test").status_code == 409                                       # no device yet: say so, do not pretend
        assert c.post("/api/push/subscribe", json={**sub, "expirationTime": None}).json() == {"ok": True}
        result = c.post("/api/push/test").json()
        assert result["ok"] is True and result["sent"] == 1 and sender.calls[-1]["data"]["tag"] == "tapan-test"
        assert sender.calls[-1]["ttl"] == 300                                                    # a test is worthless an hour later
        for payload, status in [({"endpoint": "https://evil.com/x", "keys": sub["keys"]}, 400),
                                ({"endpoint": "http://127.0.0.1/x", "keys": sub["keys"]}, 400),
                                ({"endpoint": sub["endpoint"]}, 422)]:
            assert c.post("/api/push/subscribe", json=payload).status_code == status
        assert c.post("/api/push/unsubscribe", json={"endpoint": sub["endpoint"]}).json() == {"ok": True}
        assert c.post("/api/push/test").status_code == 409


def test_test_notifications_are_rate_limited_and_disabled_servers_say_so(settings):
    store = SQLiteStore(":memory:")
    asyncio.run(store.initialize())
    push = PushService(store, settings, sender=FakeSender())
    asyncio.run(push.subscribe(browser_subscription()[0]))
    with make_client(settings, push, store, rate_limit_per_minute=3) as c:
        codes = [c.post("/api/push/test").status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and 429 in codes[3:]
    off = PushService(store, settings.model_copy(update={"push_enabled": False}), sender=FakeSender())
    with make_client(settings, off, store) as c:
        assert c.get("/api/push/key").json() == {"enabled": False, "public_key": None}
        assert c.post("/api/push/subscribe", json=browser_subscription()[0]).status_code == 503
        assert c.post("/api/push/test").status_code == 503


# ── real crypto: the genuine pywebpush -> a local "push service" -> decrypt like a browser ─────
class _Capture(BaseHTTPRequestHandler):
    captured: list = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        _Capture.captured.append({"headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
        self.send_response(201)
        self.end_headers()

    def log_message(self, *a):
        pass


@pytest.fixture
def push_server():
    _Capture.captured = []
    server = HTTPServer(("127.0.0.1", 0), _Capture)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/push/endpoint", _Capture.captured
    server.shutdown()


async def test_real_encryption_and_vapid_signature_round_trip(store, settings, push_server):
    pytest.importorskip("pywebpush")
    import http_ece
    from py_vapid import Vapid02

    endpoint, captured = push_server
    sub, browser_key, auth_secret = browser_subscription(endpoint)
    service = PushService(store, settings, allow_any_endpoint=True)                              # the real pywebpush sender
    await service.subscribe(sub)
    result = await service.send({"title": "Reminder", "body": "Call mom · was due 9:00 AM", "tag": "reminder-7", "url": "/web/index.html?panel=today"})
    assert result == {"sent": 1, "removed": 0, "failed": 0}, result

    req = captured[0]
    plaintext = http_ece.decrypt(req["body"], private_key=browser_key, auth_secret=auth_secret, version="aes128gcm")
    assert json.loads(plaintext) == {"title": "Reminder", "body": "Call mom · was due 9:00 AM", "tag": "reminder-7", "url": "/web/index.html?panel=today"}
    assert b"Call mom" not in req["body"]                                                        # the push service only ever sees ciphertext
    assert req["headers"]["content-encoding"] == "aes128gcm" and req["headers"]["ttl"] == "86400" and req["headers"]["urgency"] == "high"
    auth_header = req["headers"]["authorization"]
    assert auth_header.lower().startswith("vapid ") and Vapid02.verify(auth_header)              # signature valid for the embedded public key
    assert f"k={await service.public_key()}" in auth_header                                      # ...and it is OUR key, which the browser subscribed against


# ── Snooze buttons on the notification ──────────────────────────────
async def test_single_reminders_get_signed_snooze_buttons_and_bursts_do_not(store, settings):
    sender = FakeSender()
    service = PushService(store, settings, sender=sender)
    await service.subscribe(browser_subscription()[0])
    now = timeutil.now(settings)
    await service.notify_reminders([{"id": 41, "title": "Call mom", "due": now}], now)
    one = sender.calls[-1]["data"]
    assert [a["action"] for a in one["actions"]] == ["snooze10", "snooze60"] and [a["title"] for a in one["actions"]] == ["Snooze 10 min", "Snooze 1 h"]
    signer = await service.action_signer()
    assert signer.verify("snooze", 41, 10, one["sigs"]["10"]) and signer.verify("snooze", 41, 60, one["sigs"]["60"])
    assert not signer.verify("snooze", 42, 10, one["sigs"]["10"]) and not signer.verify("snooze", 41, 60, one["sigs"]["10"])   # bound to id AND length
    sender.calls.clear()
    await service.notify_reminders([{"id": i, "title": f"t{i}", "due": now} for i in range(6)], now)
    burst = sender.calls[-1]["data"]
    assert "actions" not in burst and "sigs" not in burst                                                      # a summary has nothing to snooze


def _action_client(settings, **overrides):
    from src.main import build_runtime

    cfg = settings.model_copy(update=overrides)
    runtime = asyncio.run(build_runtime(cfg))
    return runtime, TestClient(create_api(runtime.orchestrator, cfg, runtime.health_checker, runtime=runtime))


def test_snooze_endpoint_works_without_the_access_token_but_only_with_a_valid_signature(settings):
    runtime, client = _action_client(settings, api_token="s3cret")
    rid = asyncio.run(runtime.sqlite_store.execute("INSERT INTO reminders (session_id, title, due_at, status, created_at) VALUES ('s','Pay rent',?, 'fired','t')",
                                                   ((timeutil.now(settings) - timedelta(minutes=1)).isoformat(),)))
    signer = asyncio.run(runtime.push.action_signer())
    good = {"r": rid, "m": 10, "s": signer.sign("snooze", rid, 10)}
    with client as c:
        assert c.post("/api/briefing").status_code in (401, 405)                                      # sanity: the rest of the API still needs the token
        ok = c.post("/api/push/action", json=good)                                                     # ...but this one does not
        assert ok.status_code == 200 and ok.json()["ok"] and ok.json()["title"] == "Pay rent" and ok.json()["label"].startswith("Snoozed until")
        assert asyncio.run(runtime.sqlite_store.fetchone("SELECT COUNT(*) AS n FROM reminders WHERE status = 'pending'"))["n"] == 1
        assert c.post("/api/push/action", json=good).status_code == 200                               # a double tap is harmless...
        assert asyncio.run(runtime.sqlite_store.fetchone("SELECT COUNT(*) AS n FROM reminders WHERE status = 'pending'"))["n"] == 1   # ...and idempotent
        for label, body in {"tampered": {**good, "s": good["s"][:-2] + "AA"}, "another reminder": {**good, "r": rid + 1}, "longer than signed": {**good, "m": 60},
                            "unoffered length": {"r": rid, "m": 5, "s": signer.sign("snooze", rid, 5)},
                            "other secret": {**good, "s": actions_signer_for(b"attacker").sign("snooze", rid, 10)}}.items():
            assert c.post("/api/push/action", json=body).status_code == 400, label
        assert c.post("/api/push/action", json={"r": "x", "m": 10, "s": "y"}).status_code == 422
        gone = {"r": 99999, "m": 10, "s": signer.sign("snooze", 99999, 10)}
        assert c.post("/api/push/action", json=gone).status_code == 404


def actions_signer_for(secret: bytes):
    from src.agent.actions import ActionSigner

    return ActionSigner(secret, b"tapan-action-push")


def test_a_different_server_key_cannot_forge_or_replay_buttons(settings):
    runtime_a, client_a = _action_client(settings)
    runtime_b, client_b = _action_client(settings)                    # a second deployment with its own generated key
    rid = asyncio.run(runtime_b.sqlite_store.execute("INSERT INTO reminders (session_id, title, due_at, status, created_at) VALUES ('s','x','2030-01-01T00:00:00+00:00','fired','t')"))
    sig_from_a = asyncio.run(runtime_a.push.action_signer()).sign("snooze", rid, 10)
    with client_b as c:
        assert c.post("/api/push/action", json={"r": rid, "m": 10, "s": sig_from_a}).status_code == 400


def test_snooze_endpoint_is_rate_limited_and_respects_disabled_push(settings):
    runtime, client = _action_client(settings, rate_limit_per_minute=5)
    with client as c:
        codes = [c.post("/api/push/action", json={"r": 1, "m": 10, "s": "nope"}).status_code for _ in range(8)]
    assert codes[:5] == [400] * 5 and 429 in codes[5:]
    runtime, client = _action_client(settings, push_enabled=False)
    with client as c:
        assert c.post("/api/push/action", json={"r": 1, "m": 10, "s": "x"}).status_code == 503
