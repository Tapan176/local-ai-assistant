"""Telegram routes: the public webhook (header-authenticated) and the signed-in setup endpoints."""

from __future__ import annotations

import hmac
import json
import os
from typing import Any, Callable

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel

from src.config.settings import Settings
from src.integrations.telegram import TelegramError

MAX_UPDATE_BYTES = 64 * 1024


class TokenBody(BaseModel):
    token: str


def public_base(request: Request, settings: Settings) -> str:
    """Our public https address, for registering the webhook with Telegram."""
    if settings.public_url:
        return settings.public_url
    if os.getenv("RENDER_EXTERNAL_URL"):
        return os.environ["RENDER_EXTERNAL_URL"]
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    return f"{scheme}://{host}"


def register(app: FastAPI, *, runtime: Any, settings: Settings, require_auth: Callable, limiter: Any) -> None:
    bridge = runtime.telegram

    @app.post("/telegram/webhook")
    async def webhook(request: Request) -> dict[str, bool]:
        secret = await bridge.webhook_secret()
        provided = request.headers.get("x-telegram-bot-api-secret-token", "")
        if not secret or not hmac.compare_digest(secret.encode(), provided.encode()):
            raise HTTPException(status_code=403, detail="Forbidden")
        body = await request.body()
        if len(body) > MAX_UPDATE_BYTES:
            raise HTTPException(status_code=413, detail="Too large")
        try:
            update = json.loads(body)
        except ValueError:
            raise HTTPException(status_code=400, detail="Bad request")
        if isinstance(update, dict):
            bridge.schedule(update)                          # answer 200 now; the (slow) reply is sent in the background
        return {"ok": True}

    @app.get("/api/telegram/status", dependencies=[Depends(require_auth)])
    async def status() -> dict[str, Any]:
        return await bridge.status()

    async def _webhook_result(request: Request) -> dict[str, Any]:
        try:
            await bridge.ensure_webhook(public_base(request, settings))
            return {"webhook": True}
        except TelegramError as exc:
            return {"webhook": False, "webhook_error": str(exc)}

    @app.post("/api/telegram/token", dependencies=[Depends(require_auth)])
    async def set_token(body: TokenBody, request: Request, client_key: str = Depends(require_auth)) -> dict[str, Any]:
        if not limiter.allow(f"tg-token:{client_key}"):
            raise HTTPException(status_code=429, detail="Too many attempts. Wait a minute.")
        try:
            bot = await bridge.set_token(body.token)
        except TelegramError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"ok": True, "bot": bot.get("username"), **await _webhook_result(request)}

    @app.delete("/api/telegram/token", dependencies=[Depends(require_auth)])
    async def remove_token() -> dict[str, bool]:
        await bridge.remove_token()
        return {"ok": True}

    @app.post("/api/telegram/pair", dependencies=[Depends(require_auth)])
    async def pair(request: Request, client_key: str = Depends(require_auth)) -> dict[str, Any]:
        if not limiter.allow(f"tg-pair:{client_key}"):
            raise HTTPException(status_code=429, detail="Too many attempts. Wait a minute.")
        try:
            created = await bridge.create_pairing()
        except TelegramError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {**created, **await _webhook_result(request)}

    @app.post("/api/telegram/unlink", dependencies=[Depends(require_auth)])
    async def unlink() -> dict[str, bool]:
        await bridge.unlink()
        return {"ok": True}

    @app.post("/api/telegram/test", dependencies=[Depends(require_auth)])
    async def test(client_key: str = Depends(require_auth)) -> dict[str, Any]:
        if not limiter.allow(f"tg-test:{client_key}"):
            raise HTTPException(status_code=429, detail="Too many tests. Wait a minute.")
        try:
            await bridge.send("Tapan is connected. Reminders will arrive here.")
        except TelegramError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return {"ok": True}
