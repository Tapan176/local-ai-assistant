"""Authenticated REST routes beyond chat: status/diagnostics and (in later sections) settings, data and integrations."""

from __future__ import annotations

import json
import platform
import re
import time
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from src.agent import actions, timeutil, weather
from src.agent import digest, expenses
from src.agent import export as data_export
from src.config.settings import Settings
from src.interfaces import api_expenses, api_graph, api_telegram, api_workspace

CLIENT_REPORT_LIMIT = 8


class PushActionBody(BaseModel):
    r: int
    m: int
    s: str = Field(max_length=64)


class DigestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    time: str = Field(max_length=5)


class ClientReport(BaseModel):
    """What a browser tells us about itself so 'it did not work on my phone' is answerable from the server."""

    model_config = ConfigDict(extra="ignore")
    device: str = Field(pattern=r"^[A-Za-z0-9-]{6,40}$")
    web_version: str = Field(default="", max_length=40)
    ua: str = Field(default="", max_length=300)
    standalone: bool = False
    online: bool = True
    tz: str = Field(default="", max_length=60)
    push: dict[str, Any] = Field(default_factory=dict)
    sw: dict[str, Any] = Field(default_factory=dict)


_BROWSERS = (          # order matters: Edge and Opera also say "Chrome", Chrome also says "Safari", iOS Safari says "Version"
    ("Edge", r"EdgA?/(\d+)"), ("Opera", r"OPR/(\d+)"), ("Samsung Internet", r"SamsungBrowser/(\d+)"), ("Firefox", r"(?:Firefox|FxiOS)/(\d+)"),
    ("Chrome", r"(?:Chrome|CriOS)/(\d+)"), ("Safari", r"Version/(\d+)"),
)
_OSES = (r"Android [\d.]+", r"iPhone OS [\d_]+", r"CPU OS [\d_]+", r"Windows NT [\d.]+", r"Mac OS X [\d_.]+", r"CrOS", r"Linux")   # Android UAs say "Linux" first


def short_ua(ua: str) -> str:
    """'Android 14 · Chrome 130' instead of a 200-character user-agent string."""
    os_label = next((m.group(0).replace("_", ".") for pattern in _OSES if (m := re.search(pattern, ua))), "")
    browser = next((f"{name} {m.group(1)}" for name, pattern in _BROWSERS if (m := re.search(pattern, ua))), "")
    return " · ".join(p for p in (os_label, browser) if p) or (ua[:40] or "unknown")


def register(app: FastAPI, *, runtime: Any, settings: Settings, require_auth: Callable, limiter: Any,
             started_at: float, ui_version: str) -> None:
    store = runtime.sqlite_store
    api_expenses.register(app, runtime=runtime, settings=settings, require_auth=require_auth, limiter=limiter)
    api_workspace.register(app, runtime=runtime, settings=settings, require_auth=require_auth, limiter=limiter)
    api_graph.register(app, runtime=runtime, settings=settings, require_auth=require_auth, limiter=limiter)

    @app.get("/api/digest", dependencies=[Depends(require_auth)])
    async def digest_get() -> dict[str, Any]:
        title, body = await digest.compose(store, settings)
        return {**await digest.get_config(store), "timezone": settings.timezone, "preview": {"title": title, "body": body}}

    @app.put("/api/digest", dependencies=[Depends(require_auth)])
    async def digest_set(body: DigestIn) -> dict[str, Any]:
        try:
            return await digest.set_config(store, body.enabled, body.time)
        except expenses.ExpenseError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from None

    @app.post("/api/digest/test")
    async def digest_test(client_key: str = Depends(require_auth)) -> dict[str, Any]:
        """Send the briefing right now to every channel (does not count as today's briefing)."""
        if not limiter.allow(f"digest-test:{client_key}"):
            raise HTTPException(status_code=429, detail="Too many test briefings. Wait a minute.")
        sent = await digest.deliver(store, settings, getattr(getattr(runtime, "scheduler", None), "push", None))
        return {"title": sent["title"], "delivery": sent["delivery"]}

    @app.get("/api/export", dependencies=[Depends(require_auth)])
    async def export_everything() -> dict[str, Any]:
        """Everything the assistant keeps about the user, as one JSON document (secrets are never included)."""
        return await data_export.build(store, settings)
    if getattr(runtime, "telegram", None):
        api_telegram.register(app, runtime=runtime, settings=settings, require_auth=require_auth, limiter=limiter)

    # ── Snooze from a notification button. No token: the signed, single-purpose action IS the credential. ──
    @app.post("/api/push/action")
    async def push_action(body: PushActionBody, request: Request) -> dict[str, Any]:
        ip = request.client.host if request.client else "unknown"
        if not limiter.allow(f"push-action:{ip}"):
            raise HTTPException(status_code=429, detail="Too many requests")
        if runtime.push is None or not runtime.push.available:
            raise HTTPException(status_code=503, detail="Push is not enabled")
        signer = await runtime.push.action_signer()
        if body.m not in actions.SNOOZE_CHOICES or not signer.verify("snooze", body.r, body.m, body.s):
            raise HTTPException(status_code=400, detail="Invalid action")
        result = await actions.snooze(store, settings, body.r, body.m)
        if result is None:
            raise HTTPException(status_code=404, detail="That reminder no longer exists")
        when = result["due"].astimezone(timeutil.get_tz(settings))
        return {"ok": True, "title": result["title"], "label": f"Snoozed until {when:%I:%M %p}".replace(" 0", " ", 1)}

    # ── what the browser reports about itself ───────────────────────
    @app.post("/api/client-report", dependencies=[Depends(require_auth)])
    async def client_report(report: ClientReport) -> dict[str, bool]:
        payload = report.model_dump()
        if len(json.dumps(payload)) > 4000:
            raise HTTPException(status_code=413, detail="Report too large")
        now = datetime.now(timezone.utc).isoformat()
        await store.execute(
            "INSERT INTO app_settings (id, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (f"client:{report.device}", json.dumps(payload), now),
        )
        stale = await store.fetchall(
            "SELECT id FROM app_settings WHERE id LIKE 'client:%' ORDER BY updated_at DESC LIMIT 100 OFFSET ?", (CLIENT_REPORT_LIMIT,)
        )
        for row in stale:
            await store.execute("DELETE FROM app_settings WHERE id = ?", (row["id"],))
        return {"ok": True}

    # ── the Status screen ───────────────────────────────────────────
    @app.get("/api/diagnostics", dependencies=[Depends(require_auth)])
    async def diagnostics() -> dict[str, Any]:
        from src.interfaces import webassets

        now = timeutil.now(settings)
        pending = await store.fetchall("SELECT due_at FROM reminders WHERE status = 'pending' AND due_at IS NOT NULL LIMIT 500")
        dues = [d for d in (timeutil.as_aware(r["due_at"], settings) for r in pending) if d is not None]
        upcoming = min((d for d in dues if d > now), default=None)
        overdue = sum(1 for d in dues if d <= now)

        subs = await store.fetchall(
            "SELECT user_agent, created_at, last_success_at, last_error FROM push_subscriptions ORDER BY id DESC LIMIT 20"
        )
        clients = []
        for row in await store.fetchall(
            "SELECT value, updated_at FROM app_settings WHERE id LIKE 'client:%' ORDER BY updated_at DESC LIMIT 8"
        ):
            try:
                data = json.loads(row["value"])
            except ValueError:
                continue
            data["ua_short"] = short_ua(data.get("ua", ""))
            data["reported_at"] = row["updated_at"]
            data["current_build"] = data.get("web_version") == ui_version
            data.pop("ua", None)
            clients.append(data)

        try:
            home = await weather.home_place(store, settings, runtime.http)
        except weather.WeatherError as exc:
            home = None
            home_error = str(exc)
        else:
            home_error = None

        chat = getattr(getattr(runtime, "llm_dispatcher", None), "chat_client", None)
        scheduler = runtime.scheduler
        return {
            "server": {
                "version": webassets.server_version(), "web_version": ui_version, "uptime_s": int(time.time() - started_at),
                "environment": settings.environment, "database": "postgres" if settings.database_url else "sqlite",
                "python": platform.python_version(), "now": now.isoformat(timespec="seconds"), "timezone": settings.timezone or "system",
            },
            "llm": {"provider": settings.llm_provider, "model": settings.openrouter_model, **(chat.stats if chat else {}), "problem": chat.explain_failure() if chat and hasattr(chat, "explain_failure") else ""},
            "scheduler": {
                **(scheduler.stats if scheduler else {}), "poll_seconds": settings.reminder_poll_seconds,
                "pending": len(dues), "overdue_pending": overdue, "next_due": upcoming.isoformat(timespec="minutes") if upcoming else None,
            },
            "push": {
                "enabled": bool(runtime.push and runtime.push.available),
                "devices": [{"device": short_ua(s["user_agent"] or ""), "since": s["created_at"],
                             "last_success_at": s["last_success_at"], "last_error": s["last_error"]} for s in subs],
            },
            "telegram": await runtime.telegram.status() if getattr(runtime, "telegram", None) else None,
            "home_location": weather.label(home) if home else None,
            "home_location_error": home_error,
            "clients": clients,
        }
