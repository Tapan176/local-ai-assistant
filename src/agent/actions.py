"""Signed, narrowly-scoped notification actions (Snooze) that work without the main API token.

A notification button (web push or Telegram) must be able to act *without* carrying your access token: a service worker
cannot safely hold it, and Telegram callbacks are public. Each button instead carries a short HMAC signature over exactly
one thing ("snooze reminder 42 for 10 minutes"). It can do nothing else, and cannot be forged without the server's secret.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Any

from src.agent import timeutil
from src.config.settings import Settings

SNOOZE_CHOICES = (10, 60)                 # minutes offered on notifications
SIG_BYTES = 9                             # 72 bits: far beyond guessable, short enough for Telegram's 64-byte callback_data


class ActionSigner:
    def __init__(self, secret: bytes, context: bytes = b"tapan-action-v1") -> None:
        self._key = hmac.new(secret, context, hashlib.sha256).digest()

    def sign(self, action: str, reminder_id: int, minutes: int) -> str:
        mac = hmac.new(self._key, f"{action}:{int(reminder_id)}:{int(minutes)}".encode(), hashlib.sha256).digest()[:SIG_BYTES]
        return base64.urlsafe_b64encode(mac).rstrip(b"=").decode()

    def verify(self, action: str, reminder_id: int, minutes: int, signature: str) -> bool:
        try:
            return hmac.compare_digest(self.sign(action, reminder_id, minutes), str(signature))
        except (TypeError, ValueError):
            return False


async def snooze(store: Any, settings: Settings, reminder_id: int, minutes: int) -> dict[str, Any] | None:
    """Create a one-off reminder `minutes` from now with the same title. Returns {title, due} or None if the id is unknown.

    Always a *new* one-off (never edits the original), so snoozing a recurring reminder does not disturb its schedule.
    Idempotent within a minute: a double tap (or a Telegram retry) does not create two.
    """
    if minutes not in SNOOZE_CHOICES:
        raise ValueError("unsupported snooze length")
    row = await store.fetchone("SELECT title FROM reminders WHERE id = ?", (int(reminder_id),))
    if not row:
        return None
    due = timeutil.now(settings) + timedelta(minutes=minutes)
    window_start, window_end = due - timedelta(minutes=1), due + timedelta(minutes=1)
    for existing in await store.fetchall("SELECT due_at FROM reminders WHERE status = 'pending' AND title = ?", (row["title"],)):
        when = timeutil.as_aware(existing["due_at"], settings)
        if when and window_start <= when <= window_end:
            return {"title": row["title"], "due": when, "duplicate": True}
    await store.execute(
        "INSERT INTO reminders (session_id, title, due_at, status, created_at) VALUES ('snooze', ?, ?, 'pending', ?)",
        (row["title"], due.isoformat(), datetime.now(timezone.utc).isoformat()),
    )
    return {"title": row["title"], "due": due, "duplicate": False}
