"""Telegram bot: a reminder channel that works on every phone (iOS included) and a way to chat from anywhere.

Security model
- Only ONE chat is ever served: the one linked with a short-lived, single-use pairing code created from the signed-in web app.
  Everyone else gets a one-line refusal (rate-limited) and nothing else.
- The webhook is public by necessity; Telegram authenticates itself with a secret header derived from the bot token.
- The bot token is a secret: it is stored server-side, never returned by any endpoint, and scrubbed from error text.
- Buttons on reminder messages carry a signed, single-purpose action (snooze one reminder), not any credential.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import httpx

from src.agent import actions, timeutil
from src.agent.push import reminder_payloads
from src.config.settings import Settings

logger = logging.getLogger(__name__)

API = "https://api.telegram.org"
MAX_MESSAGE = 3900                                  # Telegram's hard limit is 4096 characters
PAIR_TTL_SECONDS = 600
PAIR_MAX_ATTEMPTS = 10
PAIR_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I confusion
TOKEN_RE = re.compile(r"^\d{6,12}:[A-Za-z0-9_-]{30,60}$")
HANDLER_TIMEOUT = 150
STRANGER_REPLY_INTERVAL = 60.0

Handler = Callable[[str, str], Awaitable[str]]


class TelegramError(Exception):
    """A failure with a message that is safe to show in the UI (never contains the token)."""


def split_message(text: str, limit: int = MAX_MESSAGE) -> list[str]:
    """Split on paragraph / line / space boundaries so long answers arrive as readable chunks."""
    text = text.strip() or "…"
    chunks: list[str] = []
    while len(text) > limit:
        cut = max(text.rfind("\n\n", 0, limit), text.rfind("\n", 0, limit), text.rfind(" ", 0, limit))
        if cut < limit // 2:
            cut = limit
        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    chunks.append(text)
    return [c for c in chunks if c]


class TelegramBridge:
    def __init__(self, store: Any, settings: Settings, http: httpx.AsyncClient, handler: Handler | None = None) -> None:
        self.store, self.settings, self.http, self.handler = store, settings, http, handler
        self.stats: dict[str, Any] = {"sent": 0, "received": 0, "last_sent_at": None, "last_error": None}
        self._token: str | None = None
        self._bot: dict[str, Any] | None = None
        self._last_update: int | None = None
        self._tasks: set[asyncio.Task] = set()
        self._stranger_replied: dict[int, float] = {}

    # ── token & derived secrets ─────────────────────────────────────
    async def token(self) -> str | None:
        if self.settings.telegram_bot_token.strip():
            return self.settings.telegram_bot_token.strip()
        if self._token:
            return self._token
        row = await self.store.fetchone("SELECT value FROM app_settings WHERE id = 'telegram_token'")
        self._token = row["value"] if row else None
        return self._token

    async def configured(self) -> bool:
        return bool(await self.token())

    @staticmethod
    def _derive(token: str, label: bytes) -> bytes:
        return hmac.new(token.encode(), label, hashlib.sha256).digest()

    async def webhook_secret(self) -> str | None:
        token = await self.token()
        return base64.urlsafe_b64encode(self._derive(token, b"tapan-tg-webhook-v1")).decode().rstrip("=")[:48] if token else None

    async def _signer(self) -> actions.ActionSigner | None:
        token = await self.token()
        return actions.ActionSigner(token.encode(), b"tapan-action-tg") if token else None

    def _scrub(self, text: str, token: str | None) -> str:
        return text.replace(token, "***") if token else text

    # ── Bot API ─────────────────────────────────────────────────────
    async def _call(self, method: str, payload: dict[str, Any] | None = None, *, token: str | None = None) -> Any:
        token = token or await self.token()
        if not token:
            raise TelegramError("Telegram is not set up yet.")
        for attempt in range(2):
            try:
                resp = await self.http.post(f"{API}/bot{token}/{method}", json=payload or {}, timeout=20.0)
            except httpx.HTTPError as exc:                          # the exception text can contain the URL (and so the token)
                raise TelegramError(f"Could not reach Telegram ({type(exc).__name__}).") from None
            try:
                data = resp.json()
            except ValueError:
                raise TelegramError(f"Telegram sent an unreadable response (HTTP {resp.status_code}).") from None
            if resp.status_code == 429 and attempt == 0:
                await asyncio.sleep(min(float((data.get("parameters") or {}).get("retry_after", 1)), 5))
                continue
            if not data.get("ok"):
                raise TelegramError(self._scrub(str(data.get("description") or f"HTTP {resp.status_code}"), token)[:200])
            return data.get("result")
        raise TelegramError("Telegram is rate limiting requests. Try again in a moment.")

    async def bot_info(self) -> dict[str, Any] | None:
        if self._bot is None and await self.configured():
            try:
                self._bot = await self._call("getMe")
            except TelegramError as exc:
                self.stats["last_error"] = str(exc)
        return self._bot

    async def set_token(self, token: str) -> dict[str, Any]:
        token = token.strip()
        if not TOKEN_RE.match(token):
            raise TelegramError("That does not look like a bot token. It looks like 123456789:ABC… and comes from @BotFather.")
        bot = await self._call("getMe", token=token)                 # proves the token is real before we store it
        await self.store.execute(
            "INSERT INTO app_settings (id, value, updated_at) VALUES ('telegram_token', ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (token, datetime.now(timezone.utc).isoformat()),
        )
        self._token, self._bot = token, bot
        await self.unlink()                                          # a different bot means the old chat link no longer applies
        return bot

    async def remove_token(self) -> None:
        await self.store.execute("DELETE FROM app_settings WHERE id IN ('telegram_token', 'telegram_chat', 'telegram_pair')")
        self._token = self._bot = None

    async def ensure_webhook(self, base_url: str) -> None:
        base = base_url.strip().rstrip("/")
        if not base.startswith("https://"):
            raise TelegramError("Telegram needs a public https:// address, so this works on your hosted site, not on localhost.")
        await self._call("setWebhook", {
            "url": f"{base}/telegram/webhook", "secret_token": await self.webhook_secret(),
            "allowed_updates": ["message", "callback_query"], "max_connections": 2,
        })

    async def startup(self) -> None:
        """Best effort at boot: (re)register the webhook when we know our public address."""
        import os

        base = self.settings.public_url or os.getenv("RENDER_EXTERNAL_URL", "")
        if base and await self.configured():
            try:
                await self.ensure_webhook(base)
            except TelegramError as exc:
                self.stats["last_error"] = str(exc)
                logger.warning("Telegram webhook setup failed: %s", exc)

    # ── linking ─────────────────────────────────────────────────────
    async def linked_chat(self) -> dict[str, Any] | None:
        row = await self.store.fetchone("SELECT value FROM app_settings WHERE id = 'telegram_chat'")
        try:
            return json.loads(row["value"]) if row else None
        except ValueError:
            return None

    async def unlink(self) -> None:
        await self.store.execute("DELETE FROM app_settings WHERE id IN ('telegram_chat', 'telegram_pair')")

    async def _save(self, key: str, value: dict[str, Any]) -> None:
        await self.store.execute(
            "INSERT INTO app_settings (id, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, json.dumps(value), datetime.now(timezone.utc).isoformat()),
        )

    async def create_pairing(self) -> dict[str, str]:
        bot = await self.bot_info()
        if not bot:
            raise TelegramError("Telegram is not set up yet.")
        code = "".join(secrets.choice(PAIR_ALPHABET) for _ in range(8))
        await self._save("telegram_pair", {"code": code, "exp": time.time() + PAIR_TTL_SECONDS, "attempts": 0})
        return {"code": code, "bot": bot.get("username", ""), "link": f"https://t.me/{bot.get('username', '')}?start={code}", "expires_in": PAIR_TTL_SECONDS}

    async def _try_pair(self, supplied: str, chat: dict[str, Any]) -> bool:
        row = await self.store.fetchone("SELECT value FROM app_settings WHERE id = 'telegram_pair'")
        if not row:
            return False
        pair = json.loads(row["value"])
        if time.time() > pair.get("exp", 0) or pair.get("attempts", 0) >= PAIR_MAX_ATTEMPTS:
            await self.store.execute("DELETE FROM app_settings WHERE id = 'telegram_pair'")
            return False
        if not hmac.compare_digest(pair["code"].encode(), supplied.strip().upper().encode()):
            pair["attempts"] = pair.get("attempts", 0) + 1
            await self._save("telegram_pair", pair)
            return False
        await self.store.execute("DELETE FROM app_settings WHERE id = 'telegram_pair'")      # single use
        name = " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")])) or chat.get("username") or "your chat"
        await self._save("telegram_chat", {"chat_id": chat["id"], "name": name, "linked_at": datetime.now(timezone.utc).isoformat()})
        return True

    async def status(self) -> dict[str, Any]:
        linked = await self.linked_chat()
        bot = await self.bot_info() if await self.configured() else None
        return {
            "configured": await self.configured(), "from_env": bool(self.settings.telegram_bot_token.strip()),
            "bot": (bot or {}).get("username"), "linked": bool(linked), "linked_name": (linked or {}).get("name"),
            "sent": self.stats["sent"], "received": self.stats["received"],
            "last_sent_at": self.stats["last_sent_at"], "last_error": self.stats["last_error"],
        }

    # ── sending ─────────────────────────────────────────────────────
    async def send(self, text: str, *, chat_id: int | None = None, buttons: list[list[tuple[str, str]]] | None = None) -> int:
        if chat_id is None:
            linked = await self.linked_chat()
            if not linked:
                raise TelegramError("No Telegram chat is linked yet.")
            chat_id = linked["chat_id"]
        chunks = split_message(text)
        for i, chunk in enumerate(chunks):
            payload: dict[str, Any] = {"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True}
            if buttons and i == len(chunks) - 1:
                payload["reply_markup"] = {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row] for row in buttons]}
            try:
                await self._call("sendMessage", payload)
            except TelegramError as exc:
                self.stats["last_error"] = str(exc)
                raise
        self.stats["sent"] += len(chunks)
        self.stats["last_sent_at"] = datetime.now(timezone.utc).isoformat()
        self.stats["last_error"] = None
        return len(chunks)

    async def notify_reminders(self, rows: list[dict[str, Any]], now: datetime) -> dict[str, int]:
        result = {"sent": 0, "removed": 0, "failed": 0}
        if not await self.configured() or not await self.linked_chat():
            return result
        signer = await self._signer()
        for payload in reminder_payloads(rows, now):
            buttons = None
            if payload.get("reminder_id") is not None and signer:
                rid = payload["reminder_id"]
                buttons = [[(f"Snooze {m} min" if m < 60 else "Snooze 1 h", f"z:{m}:{rid}:{signer.sign('snooze', rid, m)}") for m in actions.SNOOZE_CHOICES]]
            try:
                await self.send(f"⏰ {payload['title']}: {payload['body']}" if payload["title"] != "Reminder" else f"⏰ {payload['body']}", buttons=buttons)
                result["sent"] += 1
            except TelegramError:
                result["failed"] += 1
        return result

    # ── receiving ───────────────────────────────────────────────────
    def schedule(self, update: dict[str, Any]) -> None:
        """Process in the background: Telegram wants a fast HTTP 200 and retries if the (slow) LLM answer blocks it."""
        task = asyncio.create_task(self._safe_handle(update))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _safe_handle(self, update: dict[str, Any]) -> None:
        try:
            await self.handle_update(update)
        except Exception:
            logger.exception("Telegram update failed")

    async def _already_handled(self, update_id: Any) -> bool:
        if not isinstance(update_id, int):
            return False
        if self._last_update is None:
            row = await self.store.fetchone("SELECT value FROM app_settings WHERE id = 'telegram_last_update'")
            self._last_update = int(row["value"]) if row else -1
        if update_id <= self._last_update:
            return True                                              # Telegram redelivers when our 200 was slow (e.g. cold start)
        self._last_update = update_id
        await self._save_raw("telegram_last_update", str(update_id))
        return False

    async def _save_raw(self, key: str, value: str) -> None:
        await self.store.execute(
            "INSERT INTO app_settings (id, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, value, datetime.now(timezone.utc).isoformat()),
        )

    async def handle_update(self, update: dict[str, Any]) -> None:
        if await self._already_handled(update.get("update_id")):
            return
        self.stats["received"] += 1
        if isinstance(update.get("callback_query"), dict):
            await self._handle_callback(update["callback_query"])
        elif isinstance(update.get("message"), dict):
            await self._handle_message(update["message"])

    async def _reply(self, chat_id: int, text: str) -> None:
        try:
            await self.send(text, chat_id=chat_id)
        except TelegramError:
            pass

    async def _handle_message(self, msg: dict[str, Any]) -> None:
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        if chat.get("type") != "private" or not isinstance(chat_id, int):
            return                                                   # groups, channels: never
        text = (msg.get("text") or "").strip()
        linked = await self.linked_chat()
        is_owner = bool(linked) and linked["chat_id"] == chat_id

        if text.startswith("/start"):
            argument = text.split(maxsplit=1)[1] if " " in text else ""
            if is_owner:
                await self._reply(chat_id, "You are already linked. Just write to me like in the app.")
            elif argument and await self._try_pair(argument, chat):
                await self._reply(chat_id, "Linked. Reminders will arrive here, and you can chat with me from this conversation.\nType /help for tips.")
            else:
                await self._stranger(chat_id)
            return
        if not is_owner:
            await self._stranger(chat_id)
            return
        if not text:
            await self._reply(chat_id, "I can only read text messages for now.")
            return
        if text.startswith("/help"):
            await self._reply(chat_id, "Talk to me normally: “remind me to call mom tomorrow 9am”, “what’s the weather”, “add a task…”.\n/today gives your day at a glance.")
            return
        if text.startswith("/today"):
            text = "Give me a briefing on my day"
        if not self.handler:
            await self._reply(chat_id, "I am not ready yet. Try again in a moment.")
            return
        try:
            await self._call("sendChatAction", {"chat_id": chat_id, "action": "typing"})
        except TelegramError:
            pass
        try:
            answer = await asyncio.wait_for(self.handler("telegram", text), timeout=HANDLER_TIMEOUT)
        except Exception:
            logger.exception("Telegram chat handler failed")
            answer = "Sorry, something went wrong on my side. Please try again."
        await self._reply(chat_id, answer)

    async def _stranger(self, chat_id: int) -> None:
        now = time.monotonic()
        if now - self._stranger_replied.get(chat_id, -1e9) < STRANGER_REPLY_INTERVAL:
            return
        self._stranger_replied[chat_id] = now
        if len(self._stranger_replied) > 500:
            self._stranger_replied.clear()
        await self._reply(chat_id, "This is a private assistant.")

    async def _handle_callback(self, cq: dict[str, Any]) -> None:
        cq_id = cq.get("id")
        message = cq.get("message") or {}
        chat_id = (message.get("chat") or {}).get("id")
        linked = await self.linked_chat()

        async def answer(text: str) -> None:
            try:
                await self._call("answerCallbackQuery", {"callback_query_id": cq_id, "text": text[:180]})
            except TelegramError:
                pass

        if not linked or linked["chat_id"] != chat_id:
            await answer("Not allowed.")
            return
        parts = str(cq.get("data") or "").split(":")
        signer = await self._signer()
        try:
            _, minutes, rid, sig = parts
            minutes, rid = int(minutes), int(rid)
        except ValueError:
            await answer("That button is not valid.")
            return
        if not signer or not signer.verify("snooze", rid, minutes, sig) or minutes not in actions.SNOOZE_CHOICES:
            await answer("That button is not valid.")
            return
        result = await actions.snooze(self.store, self.settings, rid, minutes)
        if result is None:
            await answer("That reminder no longer exists.")
            return
        when = result["due"].astimezone(timeutil.get_tz(self.settings))
        label = f"Snoozed until {when:%I:%M %p}".replace(" 0", " ", 1) if when else "Snoozed"
        await answer(label)
        try:                                                           # remove the buttons so it cannot be tapped twice
            await self._call("editMessageReplyMarkup", {"chat_id": chat_id, "message_id": message.get("message_id"), "reply_markup": {"inline_keyboard": []}})
        except TelegramError:
            pass
        await self._reply(chat_id, f"⏰ {label}: {result['title']}")
