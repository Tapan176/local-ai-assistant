"""Web Push (VAPID) for reminders: key management, subscription storage and delivery.

Design notes
- The browser encrypts nothing itself: *we* encrypt each message to the subscription's public key (RFC 8291) and the
  push service (Google / Mozilla / Apple / Microsoft) only ever sees ciphertext. Reminder titles never reach them in clear.
- VAPID keys come from TAPAN_VAPID_PRIVATE_KEY if set, otherwise they are generated once and kept in ``app_settings``
  so every instance and every restart agrees. Subscriptions are bound to the public key: if the key ever changes the
  web page notices and resubscribes by itself.
- ``subscription.endpoint`` is a URL chosen by the client and *our server POSTs to it*, so it is an SSRF vector.
  It must be https and belong to a known push service; anything else is rejected before it is stored or used.
- The VAPID ``sub`` claim is shared with those push services. It is never derived from a personal email address.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlparse

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from src.agent.actions import SNOOZE_CHOICES, ActionSigner
from src.config.settings import Settings

try:  # optional at import time so the rest of the app (and the test suite) still runs without it
    from py_vapid import Vapid02
    from pywebpush import WebPushException, webpush
except ImportError:  # pragma: no cover - depends on the install
    Vapid02 = webpush = None  # type: ignore[assignment]

    class WebPushException(Exception):  # type: ignore[no-redef]
        response: Any = None

logger = logging.getLogger(__name__)

ALLOWED_PUSH_HOST_SUFFIXES = (
    "fcm.googleapis.com",            # Chrome, Edge (non-Windows), Samsung Internet, Opera, Brave
    "push.services.mozilla.com",     # Firefox
    "push.apple.com",                # Safari / iOS home-screen apps
    "notify.windows.com",            # Edge on Windows (WNS)
)
MAX_SUBSCRIPTIONS = 20
MAX_ENDPOINT_LENGTH = 2048
SEND_TIMEOUT_SECONDS = 10
GONE_STATUS_CODES = {404, 410}        # the push service says this subscription no longer exists
BATCH_THRESHOLD = 3                   # more reminders than this firing together are sent as ONE summary notification

Sender = Callable[..., Any]


# ── helpers ─────────────────────────────────────────────────────────
def b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def generate_private_key() -> str:
    """A new VAPID private key as base64url of the 32-byte scalar."""
    key = ec.generate_private_key(ec.SECP256R1())
    return b64e(key.private_numbers().private_value.to_bytes(32, "big"))


def public_key_for(private_b64: str) -> str:
    """The matching public key in the form browsers want as ``applicationServerKey`` (65-byte uncompressed point)."""
    key = ec.derive_private_key(int.from_bytes(b64d(private_b64), "big"), ec.SECP256R1())
    return b64e(key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint))


def host_allowed(host: str, extra_suffixes: tuple[str, ...] = ()) -> bool:
    host = host.lower().rstrip(".")
    return any(host == s or host.endswith("." + s) for s in ALLOWED_PUSH_HOST_SUFFIXES + extra_suffixes)


def validate_subscription(sub: Any, *, allow_any_endpoint: bool = False) -> tuple[str, str, str]:
    """Return (endpoint, p256dh, auth) or raise ValueError with a message that is safe to show to the user."""
    if not isinstance(sub, dict):
        raise ValueError("Subscription must be an object.")
    endpoint = sub.get("endpoint")
    keys = sub.get("keys") if isinstance(sub.get("keys"), dict) else {}
    p256dh, auth = keys.get("p256dh"), keys.get("auth")
    if not (isinstance(endpoint, str) and isinstance(p256dh, str) and isinstance(auth, str)):
        raise ValueError("Subscription needs an endpoint and keys.p256dh / keys.auth.")
    if len(endpoint) > MAX_ENDPOINT_LENGTH:
        raise ValueError("Endpoint is too long.")
    parsed = urlparse(endpoint)
    if not allow_any_endpoint:
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("Endpoint must be an https URL.")
        if parsed.username or parsed.password or parsed.port not in (None, 443):
            raise ValueError("Endpoint must not contain credentials or a custom port.")
        if not host_allowed(parsed.hostname):
            raise ValueError("Endpoint is not a recognised push service.")
    try:
        point = b64d(p256dh)
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), point)
        if len(point) != 65:
            raise ValueError("bad length")
    except Exception as exc:
        raise ValueError("keys.p256dh is not a valid P-256 public key.") from exc
    try:
        if len(b64d(auth)) != 16:
            raise ValueError("bad length")
    except Exception as exc:
        raise ValueError("keys.auth must be 16 bytes (base64url).") from exc
    return endpoint, p256dh, auth


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def reminder_payloads(rows: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    """Turn freshly fired reminders into notification payloads: one each, or a single summary for a burst.

    ``rows`` are ``{"id", "title", "due": aware datetime}``. A reminder that fires well after its time (the server was
    asleep, or a deploy was in progress) says when it was actually due, so the lock screen never lies.
    """
    url = "/web/index.html?panel=today"
    if not rows:
        return []
    if len(rows) > BATCH_THRESHOLD:
        titles = [_clip(r["title"], 40) for r in rows[:3]]
        extra = len(rows) - len(titles)
        body = "; ".join(titles) + (f" and {extra} more" if extra > 0 else "")
        return [{"title": f"{len(rows)} reminders", "body": body, "tag": "reminders-batch", "url": url}]
    payloads = []
    for r in rows:
        late_minutes = (now - r["due"]).total_seconds() / 60
        body = _clip(r["title"], 120)
        if late_minutes >= 3:
            body += f" · was due {r['due'].astimezone(now.tzinfo):%I:%M %p}".replace(" 0", " ", 1)
        payloads.append({"title": "Reminder", "body": body, "tag": f"reminder-{r['id']}", "url": url, "reminder_id": r["id"]})
    return payloads


def _default_sender(subscription_info: dict, data: str, vapid_private_key: str, vapid_claims: dict, ttl: int,
                    urgency: str, timeout: int) -> Any:
    return webpush(
        subscription_info=subscription_info,
        data=data,
        vapid_private_key=Vapid02.from_raw(vapid_private_key.encode("ascii")),
        vapid_claims=vapid_claims,                      # pywebpush adds `aud`/`exp` to this dict, so never reuse one
        ttl=ttl,
        headers={"Urgency": urgency},
        timeout=timeout,
    )


class PushService:
    def __init__(self, store: Any, settings: Settings, *, sender: Sender | None = None, allow_any_endpoint: bool = False) -> None:
        self.store = store
        self.settings = settings
        self._sender = sender or _default_sender
        self._custom_sender = sender is not None
        self._allow_any = allow_any_endpoint            # tests only: lets a local fake push server stand in for FCM
        self._private: str | None = None
        self._lock = asyncio.Lock()

    # ── availability & keys ─────────────────────────────────────────
    @property
    def available(self) -> bool:
        return bool(self.settings.push_enabled and (self._custom_sender or webpush is not None))

    @property
    def subject(self) -> str:
        return self.settings.vapid_subject or os.getenv("RENDER_EXTERNAL_URL") or "mailto:push@tapan-ai.invalid"

    async def _private_key(self) -> str:
        if self._private:
            return self._private
        async with self._lock:
            if self._private:
                return self._private
            configured = self.settings.vapid_private_key.strip()
            if configured:
                public_key_for(configured)               # fail fast on a malformed key instead of at first send
                self._private = configured
                return configured
            row = await self.store.fetchone("SELECT value FROM app_settings WHERE id = 'vapid_private_key'")
            if not row:
                # INSERT OR IGNORE: if two instances race on first start, the loser simply reads the winner's key.
                await self.store.execute(
                    "INSERT OR IGNORE INTO app_settings (id, value, updated_at) VALUES ('vapid_private_key', ?, ?)",
                    (generate_private_key(), datetime.now(timezone.utc).isoformat()),
                )
                row = await self.store.fetchone("SELECT value FROM app_settings WHERE id = 'vapid_private_key'")
            self._private = row["value"]
            return self._private

    async def public_key(self) -> str | None:
        if not self.available:
            return None
        return public_key_for(await self._private_key())

    # ── subscriptions ───────────────────────────────────────────────
    async def subscribe(self, sub: Any, user_agent: str = "") -> None:
        endpoint, p256dh, auth = validate_subscription(sub, allow_any_endpoint=self._allow_any)
        now = datetime.now(timezone.utc).isoformat()
        await self.store.execute(
            "INSERT INTO push_subscriptions (endpoint, p256dh, auth, user_agent, created_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(endpoint) DO UPDATE SET p256dh = excluded.p256dh, auth = excluded.auth, "
            "user_agent = excluded.user_agent, last_error = NULL",
            (endpoint, p256dh, auth, _clip(user_agent, 200), now),
        )
        extra = await self.store.fetchall(                # keep the table bounded; the oldest devices are the stalest
            "SELECT id FROM push_subscriptions ORDER BY id DESC LIMIT 1000 OFFSET ?", (MAX_SUBSCRIPTIONS,)
        )
        for row in extra:
            await self.store.execute("DELETE FROM push_subscriptions WHERE id = ?", (row["id"],))

    async def unsubscribe(self, endpoint: str) -> None:
        await self.store.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))

    async def count(self) -> int:
        return int((await self.store.fetchone("SELECT COUNT(*) AS n FROM push_subscriptions"))["n"])

    # ── delivery ────────────────────────────────────────────────────
    async def send(self, payload: dict[str, Any], *, ttl: int = 86400, urgency: str = "high") -> dict[str, int]:
        """Deliver one notification to every subscribed device. Never raises; returns {sent, removed, failed}."""
        summary = {"sent": 0, "removed": 0, "failed": 0}
        if not self.available:
            return summary
        try:
            private = await self._private_key()
            subs = await self.store.fetchall("SELECT id, endpoint, p256dh, auth FROM push_subscriptions")
        except Exception:
            logger.exception("Push: could not load keys or subscriptions")
            return summary
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        outcomes = await asyncio.gather(*(self._send_one(s, data, private, ttl, urgency) for s in subs))
        for outcome in outcomes:
            summary[outcome] += 1
        return summary

    async def _send_one(self, sub: dict[str, Any], data: str, private: str, ttl: int, urgency: str) -> str:
        info = {"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}}
        try:
            await asyncio.to_thread(
                self._sender, info, data, private, {"sub": self.subject}, ttl, urgency, SEND_TIMEOUT_SECONDS
            )
        except WebPushException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in GONE_STATUS_CODES:
                await self.store.execute("DELETE FROM push_subscriptions WHERE id = ?", (sub["id"],))
                logger.info("Push: removed expired subscription (HTTP %s)", status)
                return "removed"
            await self._record_error(sub["id"], f"HTTP {status}" if status else str(exc))
            return "failed"
        except Exception as exc:                          # network error, timeout, encryption problem
            await self._record_error(sub["id"], f"{type(exc).__name__}: {exc}")
            return "failed"
        await self.store.execute(
            "UPDATE push_subscriptions SET last_success_at = ?, last_error = NULL WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), sub["id"]),
        )
        return "sent"

    async def _record_error(self, sub_id: int, message: str) -> None:
        logger.warning("Push delivery failed: %s", _clip(message, 200))
        try:
            await self.store.execute("UPDATE push_subscriptions SET last_error = ? WHERE id = ?", (_clip(message, 300), sub_id))
        except Exception:
            logger.debug("could not record push error", exc_info=True)

    async def action_signer(self) -> ActionSigner:
        """Signs notification buttons. Derived from the VAPID key, so it needs no extra secret and survives restarts."""
        return ActionSigner(b64d(await self._private_key()), b"tapan-action-push")

    async def notify_digest(self, title: str, body: str) -> dict[str, int]:
        """The morning briefing: one message, normal urgency, kept for six hours if the phone is off."""
        return await self.send({"title": title, "body": _clip(body, 400), "tag": "daily-digest", "url": "/web/index.html?panel=today"}, ttl=6 * 3600, urgency="normal")

    async def notify_reminders(self, rows: list[dict[str, Any]], now: datetime) -> dict[str, int]:
        total = {"sent": 0, "removed": 0, "failed": 0}
        signer = None
        if self.available:
            try:
                signer = await self.action_signer()
            except Exception:                    # buttons are a bonus: never lose the reminder itself over them
                logger.exception("Push: could not prepare action buttons")
        for payload in reminder_payloads(rows, now):
            rid = payload.get("reminder_id")
            if rid is not None and signer is not None:
                payload["actions"] = [{"action": f"snooze{m}", "title": "Snooze 10 min" if m < 60 else "Snooze 1 h"} for m in SNOOZE_CHOICES]
                payload["sigs"] = {str(m): signer.sign("snooze", rid, m) for m in SNOOZE_CHOICES}
            for key, value in (await self.send(payload)).items():
                total[key] += value
        return total
