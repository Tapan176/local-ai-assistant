"""Milestone 0: an open page must learn about new deployments, and the server must be able to say what a phone's page is doing."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.config.settings import Settings
from src.interfaces import api_extra, webassets
from src.interfaces.api_extra import short_ua
from src.interfaces.websocket_api import create_api
from src.main import build_runtime

ANDROID_UA = "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36"
IPHONE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"
EDGE_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0"


def make_app(**overrides):
    settings = Settings(llm_provider="mock", environment="local", sqlite_path=":memory:", intent_classifier="heuristic",
                        timezone="UTC", **overrides)
    runtime = asyncio.run(build_runtime(settings))
    return settings, runtime, create_api(runtime.orchestrator, settings, runtime.health_checker, runtime=runtime)


# ── version stamping & caching ──────────────────────────────────────
def test_web_version_changes_exactly_when_the_ui_changes(tmp_path):
    for name in ("index.html", "app.js", "style.css", "sw.js", "manifest.webmanifest"):
        (tmp_path / name).write_text(f"// {name}")
    first = webassets.web_version(tmp_path)
    assert first == webassets.web_version(tmp_path) and len(first) == 10
    (tmp_path / "app.js").write_text("// changed")
    assert webassets.web_version(tmp_path) != first
    (tmp_path / "unrelated.txt").write_text("x")                 # files outside the UI set do not change the stamp
    changed = webassets.web_version(tmp_path)
    (tmp_path / "unrelated.txt").write_text("y")
    assert webassets.web_version(tmp_path) == changed


def test_served_app_js_carries_the_build_hash_and_health_reports_the_same():
    _, _, app = make_app()
    with TestClient(app) as c:
        health = c.get("/health").json()
        js = c.get("/web/app.js")
        assert js.status_code == 200 and "javascript" in js.headers["content-type"]
        assert f"const WEB_VERSION = '{health['web_version']}';" in js.text      # the page knows which build it is
        assert "__WEB_VERSION__" not in js.text.replace("'__WEB_' + 'VERSION__'", "")   # only the split comparison literal survives
        assert "'__WEB_' + 'VERSION__'" in js.text                                # ...so WEB_VERSION_KNOWN is still correct
        assert health["version"] and isinstance(health["uptime_s"], int) and health["status"] == "ok"
        assert re.fullmatch(r"[0-9a-f]{10}", health["web_version"])


def test_app_js_supports_conditional_requests():
    _, _, app = make_app()
    with TestClient(app) as c:
        first = c.get("/web/app.js")
        etag = first.headers["etag"]
        assert first.headers["cache-control"] == "no-cache"
        again = c.get("/web/app.js", headers={"If-None-Match": etag})
        assert again.status_code == 304 and again.content == b""
        assert c.get("/web/app.js", headers={"If-None-Match": '"stale"'}).status_code == 200


@pytest.mark.parametrize("path", ["/web/index.html", "/web/style.css", "/web/sw.js", "/web/settings.js", "/web/manifest.webmanifest", "/web/icons/icon-192.png"])
def test_every_ui_file_is_always_revalidated(path):
    _, _, app = make_app()
    with TestClient(app) as c:
        r = c.get(path)
        assert r.status_code == 200 and r.headers["cache-control"] == "no-cache", path


def test_the_service_worker_precaches_every_script_the_page_loads():
    web = webassets.WEB_DIR
    scripts = re.findall(r'<script[^>]+src="([^"/]+\.js)"', (web / "index.html").read_text(encoding="utf-8"))
    shell = re.search(r"const SHELL = \[(.*?)\];", (web / "sw.js").read_text(encoding="utf-8"), re.S).group(1)
    for script in scripts:
        assert f'"{script}"' in shell, f"{script} is loaded by the page but not cached for offline use"


# ── client reports ──────────────────────────────────────────────────
REPORT = {"device": "abc123-def456", "web_version": "old0000000", "ua": ANDROID_UA, "standalone": True, "online": True,
          "tz": "Asia/Kolkata", "push": {"status": "unsupported", "issue": "unsupported", "permission": "default", "has_push_manager": False},
          "sw": {"supported": True, "controlled": False}}


def test_client_reports_require_the_token_and_are_validated():
    _, _, app = make_app(api_token="s3cret")
    auth = {"Authorization": "Bearer s3cret"}
    with TestClient(app) as c:
        assert c.post("/api/client-report", json=REPORT).status_code == 401
        assert c.get("/api/diagnostics").status_code == 401
        assert c.post("/api/client-report", json=REPORT, headers=auth).json() == {"ok": True}
        for bad in ({**REPORT, "device": "x"}, {**REPORT, "device": "has space!"}, {**REPORT, "device": "a" * 41}, {k: v for k, v in REPORT.items() if k != "device"}):
            assert c.post("/api/client-report", json=bad, headers=auth).status_code == 422
        assert c.post("/api/client-report", json={**REPORT, "push": {"x": "y" * 5000}}, headers=auth).status_code == 413


def test_reports_are_upserted_per_device_and_bounded():
    _, runtime, app = make_app()
    with TestClient(app) as c:
        for i in range(12):
            assert c.post("/api/client-report", json={**REPORT, "device": f"device-{i:03d}-xx"}).status_code == 200
        c.post("/api/client-report", json={**REPORT, "device": "device-011-xx", "web_version": "newer"})     # same device again: updated
        n = asyncio.run(runtime.sqlite_store.fetchone("SELECT COUNT(*) AS n FROM app_settings WHERE id LIKE 'client:%'"))["n"]
        assert n == api_extra.CLIENT_REPORT_LIMIT
        kept = c.get("/api/diagnostics").json()["clients"]
        assert len(kept) == api_extra.CLIENT_REPORT_LIMIT and kept[0]["web_version"] == "newer"


# ── diagnostics ─────────────────────────────────────────────────────
def test_diagnostics_tells_a_stale_phone_from_a_current_one():
    _, _, app = make_app()
    with TestClient(app) as c:
        current = c.get("/health").json()["web_version"]
        c.post("/api/client-report", json={**REPORT, "device": "phone-old-0001"})
        c.post("/api/client-report", json={**REPORT, "device": "phone-new-0001", "web_version": current,
                                            "push": {"status": "on", "permission": "granted"}})
        d = c.get("/api/diagnostics").json()
        by_device = {x["device"]: x for x in d["clients"]}
        assert by_device["phone-old-0001"]["current_build"] is False and by_device["phone-new-0001"]["current_build"] is True
        assert by_device["phone-old-0001"]["ua_short"] == "Android 14 · Chrome 130"
        assert "ua" not in by_device["phone-old-0001"]                                  # the long user-agent is not echoed back
        assert by_device["phone-old-0001"]["push"]["issue"] == "unsupported"
        assert d["server"]["web_version"] == current and d["server"]["database"] == "sqlite"


def test_diagnostics_reports_scheduler_heartbeat_overdue_work_and_push_devices():
    settings, runtime, app = make_app()
    from datetime import datetime, timedelta, timezone

    from tests.test_push import browser_subscription

    async def seed():
        await runtime.sqlite_store.execute("INSERT INTO reminders (session_id, title, due_at, status, created_at) VALUES ('s','Soon',?,'pending','t')",
                                           ((datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),))
        await runtime.sqlite_store.execute("INSERT INTO reminders (session_id, title, due_at, status, created_at) VALUES ('s','Late',?,'pending','t')",
                                           ((datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),))
        await runtime.push.subscribe(browser_subscription()[0], ANDROID_UA)
    asyncio.run(seed())
    with TestClient(app) as c:                            # entering the client starts the scheduler, which fires the late one
        asyncio.run(asyncio.sleep(0))
        d = c.get("/api/diagnostics").json()
    sch = d["scheduler"]
    assert sch["pending"] >= 1 and sch["next_due"] is not None and sch["poll_seconds"] == settings.reminder_poll_seconds
    assert {"ticks", "last_tick_at", "fired_total", "errors", "last_error"} <= set(sch)
    assert d["push"]["enabled"] is True and d["push"]["devices"][0]["device"] == "Android 14 · Chrome 130"
    assert d["llm"]["provider"] == "mock" and "calls" in d["llm"]


def test_scheduler_heartbeat_counts_ticks_and_errors():
    from src.agent.service import ReminderScheduler

    class Boom:
        async def fetchall(self, *a, **k):
            raise RuntimeError("db is down")

    scheduler = ReminderScheduler(Boom(), Settings(timezone="UTC", llm_provider="mock"))

    async def go():
        scheduler.settings.reminder_poll_seconds = 5
        task = asyncio.create_task(scheduler._run())
        await asyncio.sleep(0.05)
        task.cancel()
    asyncio.run(go())
    assert scheduler.stats["ticks"] >= 1 and scheduler.stats["errors"] >= 1 and "RuntimeError: db is down" in scheduler.stats["last_error"]


@pytest.mark.parametrize("ua,expected", [
    (ANDROID_UA, "Android 14 · Chrome 130"), (IPHONE_UA, "iPhone OS 17.4 · Safari 17"), (EDGE_UA, "Windows NT 10.0 · Edge 130"),
    ("", "unknown"), ("curl/8.0", "curl/8.0"),
])
def test_short_ua(ua, expected):
    assert short_ua(ua) == expected


def test_a_new_ui_file_changes_the_build_stamp_automatically(tmp_path):
    (tmp_path / "app.js").write_text("// app")
    before = webassets.web_version(tmp_path)
    (tmp_path / "brand-new-feature.js").write_text("// added later; nobody remembered to register it anywhere")
    assert webassets.web_version(tmp_path) != before
    (tmp_path / "icons").mkdir()
    (tmp_path / "icons" / "x.png").write_bytes(b"\x89PNG")
    assert webassets.web_version(tmp_path) != before
