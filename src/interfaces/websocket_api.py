"""FastAPI REST + WebSocket interface (token-protected, rate-limited)."""

from __future__ import annotations

import asyncio
import hmac
import inspect
import json
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from src.interfaces import api_extra, webassets

from src.config.settings import Settings
from src.core.health_check import HealthChecker
from src.llm.streaming import stream_text
from src.models import ChatRequest, ChatResponse

if TYPE_CHECKING:  # pragma: no cover
    from src.main import Runtime

class PushKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscriptionBody(BaseModel):
    model_config = ConfigDict(extra="ignore")          # the browser's toJSON() also carries expirationTime
    endpoint: str
    keys: PushKeys


class PushEndpointBody(BaseModel):
    endpoint: str


WS_UNAUTHORIZED = 4401
WS_RATE_LIMITED = 4429


class RateLimiter:
    """Sliding-window limiter, in-memory (single instance)."""

    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        window = self._hits[key]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= self.per_minute:
            return False
        window.append(now)
        return True


def _parse_auth_frame(text: str) -> str | None:
    """Return the token if `text` is an auth frame ({"auth": "<token>"}), else None (a normal chat message)."""
    if not text.startswith("{") or '"auth"' not in text[:20]:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if isinstance(data, dict) and set(data) == {"auth"} and isinstance(data["auth"], str):
        return data["auth"].strip()
    return None


def _token_matches(expected: str, provided: str | None) -> bool:
    return bool(provided) and hmac.compare_digest(expected.encode(), (provided or "").encode())


def create_api(
    orchestrator: Any,
    settings: Settings,
    health_checker: HealthChecker | None = None,
    *,
    runtime: "Runtime | None" = None,
) -> FastAPI:
    if settings.environment.lower() != "local" and not settings.api_token:
        raise RuntimeError(
            "TAPAN_API_TOKEN must be set when TAPAN_ENV is not 'local' — the API can execute tools on your behalf."
        )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if runtime and runtime.scheduler:
            runtime.scheduler.start()
        if runtime and getattr(runtime, "telegram", None):
            asyncio.create_task(runtime.telegram.startup())     # register the webhook when we know our public address
        yield
        if runtime:
            await runtime.aclose()

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    limiter = RateLimiter(settings.rate_limit_per_minute)

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type", "X-API-Key"],
        )

    # ── auth helpers ────────────────────────────────────────────────
    def _http_token(request: Request) -> str | None:
        header = request.headers.get("authorization", "")
        if header.lower().startswith("bearer "):
            return header[7:].strip()
        return request.headers.get("x-api-key")

    async def require_auth(request: Request) -> str:
        if settings.api_token and not _token_matches(settings.api_token, _http_token(request)):
            raise HTTPException(status_code=401, detail="Invalid or missing API token")
        client = request.client.host if request.client else "unknown"
        return _http_token(request) or client

    def _ws_header_token(ws: WebSocket) -> str | None:
        header = ws.headers.get("authorization", "")
        return header[7:].strip() if header.lower().startswith("bearer ") else ws.headers.get("x-api-key")

    # ── static UI ───────────────────────────────────────────────────
    started_at = time.time()
    ui_version = webassets.web_version()

    @app.get("/web/app.js")
    async def app_js(request: Request):
        return webassets.app_js_response(request, webassets.WEB_DIR, ui_version)

    app.mount("/web", webassets.NoCacheStaticFiles(directory=str(webassets.WEB_DIR)), name="web")

    @app.get("/")
    async def root():
        return RedirectResponse(url="/web/index.html")

    # ── health (public liveness; details need auth) ─────────────────
    @app.get("/health")
    async def health() -> dict[str, Any]:
        # Booleans / names only — never secrets. Lets you confirm a deployment is configured as intended.
        return {
            "status": "ok",
            "app": settings.app_name,
            "version": webassets.server_version(),
            "web_version": ui_version,
            "uptime_s": int(time.time() - started_at),
            "environment": settings.environment,
            "auth_required": bool(settings.api_token),
            "database": "postgres" if settings.database_url else "sqlite",
            "llm_provider": settings.llm_provider,
            "llm_key_configured": bool(settings.openrouter_api_key or settings.omniroute_api_key),
        }

    @app.get("/health/details", dependencies=[Depends(require_auth)])
    async def health_details() -> dict[str, Any]:
        if health_checker:
            return await health_checker.check_health()
        return {"status": "ok"}

    @app.get("/ready", dependencies=[Depends(require_auth)])
    async def ready() -> dict[str, Any]:
        if health_checker:
            return await health_checker.check_readiness()
        return {"ready": True}

    # ── chat ────────────────────────────────────────────────────────
    @app.post("/chat", response_model=ChatResponse)
    async def chat(req: ChatRequest, client_key: str = Depends(require_auth)) -> ChatResponse:
        if not limiter.allow(client_key):
            raise HTTPException(status_code=429, detail="Too many requests — slow down a little.")
        result = await orchestrator.handle_user_input(session_id=req.session_id, user_text=req.message)
        return ChatResponse(
            session_id=result.session_id,
            response=result.text,
            action_type=result.action_type,
            tool_used=result.tool_used,
            emotional_state=result.emotional_state,
        )

    # WebSocket auth never uses the URL (URLs end up in access logs). Browsers send {"auth": "<token>"} as the first
    # frame; scripts may instead send an `Authorization: Bearer` header on the handshake.
    async def _serve(ws: WebSocket, session_id: str, stream: bool) -> None:
        await ws.accept()
        authed = not settings.api_token or _token_matches(settings.api_token, _ws_header_token(ws))
        client_key = _ws_header_token(ws) or (ws.client.host if ws.client else "ws")

        async def push(event: dict[str, Any]) -> None:
            await ws.send_json(jsonable_encoder(event))

        try:
            while True:
                text = await ws.receive_text()

                auth_frame = _parse_auth_frame(text)
                if auth_frame is not None:
                    if settings.api_token and not _token_matches(settings.api_token, auth_frame):
                        await ws.close(code=WS_UNAUTHORIZED)
                        return
                    authed = True
                    client_key = auth_frame or client_key
                    await ws.send_json({"type": "auth_ok"})
                    continue
                if not authed:
                    await ws.close(code=WS_UNAUTHORIZED)
                    return

                if not limiter.allow(client_key):
                    await ws.send_json(
                        {"type": "final", "text": "Easy there — too many requests. Give me a moment.",
                         "action_type": "respond", "tool": None, "emotion": "neutral", "debug": {}}
                        if not stream else {"type": "complete", "action_type": "respond", "tool": None, "emotion": "neutral"}
                    )
                    continue

                result = await _handle(orchestrator, session_id, text, push)
                if stream:
                    async for chunk in stream_text(result.text, chunk_size=settings.stream_chunk_size):
                        await ws.send_json(jsonable_encoder({"type": "chunk", "content": chunk}))
                    await ws.send_json(
                        jsonable_encoder(
                            {"type": "complete", "action_type": result.action_type, "tool": result.tool_used,
                             "emotion": result.emotional_state}
                        )
                    )
                else:
                    await ws.send_json(
                        jsonable_encoder(
                            {
                                "type": "final",
                                "text": result.text,
                                "action_type": result.action_type,
                                "tool": result.tool_used,
                                "emotion": result.emotional_state,
                                "debug": result.debug if settings.environment.lower() == "local" else {"mode": result.debug.get("mode")},
                            }
                        )
                    )
        except WebSocketDisconnect:
            return

    @app.websocket("/ws/{session_id}")
    async def websocket_chat(ws: WebSocket, session_id: str) -> None:
        await _serve(ws, session_id, stream=False)

    @app.websocket("/ws-stream/{session_id}")
    async def websocket_stream(ws: WebSocket, session_id: str) -> None:
        """Streams the finished answer in chunks (plus tool progress events)."""
        await _serve(ws, session_id, stream=True)

    # ── proactive features (need the full runtime) ──────────────────
    if runtime is not None:

        @app.get("/api/notifications", dependencies=[Depends(require_auth)])
        async def notifications(after: int = 0, limit: int = 50) -> dict[str, Any]:
            rows = await runtime.sqlite_store.fetchall(
                "SELECT id, kind, title, body, created_at FROM notifications WHERE id > ? ORDER BY id LIMIT ?",
                (max(after, 0), min(max(limit, 1), 100)),
            )
            return {"notifications": rows}

        @app.get("/api/briefing", dependencies=[Depends(require_auth)])
        async def briefing() -> dict[str, Any]:
            from src.agent.skills.briefing import build_briefing

            return await build_briefing(runtime.skill_context("api"))

        @app.get("/api/history", dependencies=[Depends(require_auth)])
        async def history(session_id: str, limit: int = 40) -> dict[str, Any]:
            """Recent conversation for a session, oldest first, so the UI can restore it after a refresh."""
            rows = await runtime.sqlite_store.fetchall(
                'SELECT user_text, assistant_text, "timestamp" AS ts FROM episodes WHERE session_id = ? ORDER BY id DESC LIMIT ?',
                (session_id, min(max(limit, 1), 100)),
            )
            messages: list[dict[str, str]] = []
            for row in reversed(rows):
                messages.append({"role": "user", "text": row["user_text"], "ts": row["ts"]})
                messages.append({"role": "assistant", "text": row["assistant_text"], "ts": row["ts"]})
            return {"messages": messages}

        @app.get("/api/conversations", dependencies=[Depends(require_auth)])
        async def conversations(limit: int = 30) -> dict[str, Any]:
            """Past conversations, most recently active first, each titled by its first message."""
            groups = await runtime.sqlite_store.fetchall(
                "SELECT session_id, COUNT(*) AS turns, MIN(id) AS first_id, MAX(id) AS last_id FROM episodes "
                "GROUP BY session_id ORDER BY MAX(id) DESC LIMIT ?",
                (min(max(limit, 1), 100),),
            )
            if not groups:
                return {"conversations": []}
            ids = [g["first_id"] for g in groups] + [g["last_id"] for g in groups]
            marks = ",".join("?" for _ in ids)
            rows = await runtime.sqlite_store.fetchall(
                f'SELECT id, user_text, "timestamp" AS ts FROM episodes WHERE id IN ({marks})', tuple(ids)
            )
            by_id = {r["id"]: r for r in rows}
            out = []
            for g in groups:
                first, last = by_id.get(g["first_id"], {}), by_id.get(g["last_id"], {})
                title = " ".join(str(first.get("user_text", "")).split())
                out.append(
                    {
                        "session_id": g["session_id"],
                        "title": (title[:60] + "…") if len(title) > 60 else (title or "Conversation"),
                        "turns": g["turns"],
                        "updated": last.get("ts"),
                    }
                )
            return {"conversations": out}

        @app.delete("/api/conversations/{session_id}", dependencies=[Depends(require_auth)])
        async def delete_conversation(session_id: str) -> dict[str, bool]:
            """Removes the chat transcript only. Saved memories, tasks and reminders are untouched."""
            await runtime.sqlite_store.execute("DELETE FROM episodes WHERE session_id = ?", (session_id,))
            return {"ok": True}

        @app.post("/api/tasks/{task_id}/complete", dependencies=[Depends(require_auth)])
        async def complete_task(task_id: int) -> dict[str, bool]:
            if not await runtime.sqlite_store.fetchone("SELECT id FROM tasks WHERE id = ? AND status = 'open'", (task_id,)):
                raise HTTPException(status_code=404, detail="No open task with that id")
            await runtime.sqlite_store.execute(
                "UPDATE tasks SET status = 'done', completed_at = ? WHERE id = ?", (datetime.now(timezone.utc).isoformat(), task_id)
            )
            return {"ok": True}

        @app.delete("/api/reminders/{reminder_id}", dependencies=[Depends(require_auth)])
        async def cancel_reminder(reminder_id: int) -> dict[str, bool]:
            if not await runtime.sqlite_store.fetchone("SELECT id FROM reminders WHERE id = ? AND status = 'pending'", (reminder_id,)):
                raise HTTPException(status_code=404, detail="No pending reminder with that id")
            await runtime.sqlite_store.execute("UPDATE reminders SET status = 'cancelled' WHERE id = ?", (reminder_id,))
            return {"ok": True}

        # ── Web Push (reminders on your lock screen) ────────────────
        @app.get("/api/push/key", dependencies=[Depends(require_auth)])
        async def push_key() -> dict[str, Any]:
            service = runtime.push
            if service is None or not service.available:
                return {"enabled": False, "public_key": None}
            return {"enabled": True, "public_key": await service.public_key()}

        @app.post("/api/push/subscribe", dependencies=[Depends(require_auth)])
        async def push_subscribe(body: PushSubscriptionBody, request: Request) -> dict[str, Any]:
            service = runtime.push
            if service is None or not service.available:
                raise HTTPException(status_code=503, detail="Push notifications are not enabled on this server")
            try:
                await service.subscribe(body.model_dump(), request.headers.get("user-agent", ""))
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
            return {"ok": True}

        @app.post("/api/push/unsubscribe", dependencies=[Depends(require_auth)])
        async def push_unsubscribe(body: PushEndpointBody) -> dict[str, bool]:
            if runtime.push is not None:
                await runtime.push.unsubscribe(body.endpoint)
            return {"ok": True}

        @app.post("/api/push/test")
        async def push_test(client_key: str = Depends(require_auth)) -> dict[str, Any]:
            service = runtime.push
            if service is None or not service.available:
                raise HTTPException(status_code=503, detail="Push notifications are not enabled on this server")
            if not limiter.allow(f"push-test:{client_key}"):
                raise HTTPException(status_code=429, detail="Too many test notifications — wait a minute.")
            if await service.count() == 0:
                raise HTTPException(status_code=409, detail="No device is subscribed yet")
            result = await service.send(
                {"title": "Tapan", "body": "Notifications are working. Reminders will arrive like this.",
                 "tag": "tapan-test", "url": "/web/index.html?panel=today"},
                ttl=300, urgency="normal",
            )
            return {"ok": result["sent"] > 0, **result}

        api_extra.register(app, runtime=runtime, settings=settings, require_auth=require_auth, limiter=limiter,
                           started_at=started_at, ui_version=ui_version)

        @app.get("/api/skills", dependencies=[Depends(require_auth)])
        async def skills() -> dict[str, Any]:
            return {
                "skills": [
                    {"name": s.name, "description": s.description, "local_only": s.local_only}
                    for s in runtime.registry.skills.values()
                ]
            }

    return app


async def _handle(orchestrator: Any, session_id: str, text: str, push):
    """Call the orchestrator, forwarding tool-progress events only if it supports them."""
    if "on_event" in inspect.signature(orchestrator.handle_user_input).parameters:
        return await orchestrator.handle_user_input(session_id=session_id, user_text=text, on_event=push)
    return await orchestrator.handle_user_input(session_id=session_id, user_text=text)
