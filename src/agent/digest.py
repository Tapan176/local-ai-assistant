"""Daily briefing push: one short message each morning with what needs attention today.

Deliberately not an LLM call: it is built from your own data by fixed rules, so it is instant, free, and never says something made up.
It goes to every channel that is set up (phone notification, Telegram) and also appears in the open app.

Rules that matter:
  * Off until the user turns it on (Settings -> Daily briefing). The time is in the configured time zone.
  * Sent at most once a day, even with two instances overlapping during a deploy: the day is claimed with one atomic statement.
  * If the server was asleep at the set time it still sends when it wakes, but only within a few hours of that time; a "good morning"
    at 3 pm is noise, so a day that is missed is skipped, not sent late.
  * Nothing to report is still a (short) message, because silence would look like a broken feature.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from src.agent import expenses, timeutil, workspace
from src.agent.expenses import ExpenseError, money
from src.config.settings import Settings

CONFIG_KEY = "digest_config"
LAST_KEY = "digest_last"
LATE_WINDOW = timedelta(hours=4)
DEFAULT = {"enabled": False, "time": "08:00"}
_TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
MAX_LISTED = 3


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def get_config(store: Any) -> dict[str, Any]:
    row = await store.fetchone("SELECT value FROM app_settings WHERE id = ?", (CONFIG_KEY,))
    if not row:
        return dict(DEFAULT)
    try:
        data = json.loads(row["value"])
        enabled, at = bool(data.get("enabled")), str(data.get("time", DEFAULT["time"]))
        return {"enabled": enabled, "time": at if _TIME.match(at) else DEFAULT["time"]}
    except (ValueError, AttributeError):
        return dict(DEFAULT)


async def set_config(store: Any, enabled: bool, at: str) -> dict[str, Any]:
    at = str(at or "").strip()
    if not _TIME.match(at):
        raise ExpenseError("Give the time as hours and minutes, like 08:00.")
    await store.execute(
        "INSERT INTO app_settings (id, value, updated_at) VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (CONFIG_KEY, json.dumps({"enabled": bool(enabled), "time": at}), _now_iso()),
    )
    return {"enabled": bool(enabled), "time": at}


async def claim_today(store: Any, today: str) -> bool:
    """True for exactly one caller per day. The row is only changed when it does not already say today."""
    row = await store.fetchone(
        "INSERT INTO app_settings (id, value, updated_at) VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at "
        "WHERE app_settings.value <> excluded.value RETURNING id",
        (LAST_KEY, today, _now_iso()),
    )
    return bool(row)


def due(config: dict[str, Any], now: datetime) -> bool:
    """Is it time? Enabled, past the set time, and not more than LATE_WINDOW past it."""
    if not config["enabled"]:
        return False
    hh, mm = (int(x) for x in config["time"].split(":"))
    at = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return at <= now <= at + LATE_WINDOW


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _titles(items: list[str]) -> str:
    shown = items[:MAX_LISTED]
    more = len(items) - len(shown)
    return ", ".join(shown) + (f" and {more} more" if more > 0 else "")


async def compose(store: Any, settings: Settings) -> tuple[str, str]:
    """(title, body) from today's data. Plain text, a few lines."""
    now = timeutil.now(settings)
    today = now.date()
    cur = settings.currency
    lines: list[str] = []

    payments, _banks = await expenses._load(store, settings)           # noqa: SLF001 - same package, same rules as the Money screen
    unpaid = [(p, e) for p in payments for e in p["emis"] if e["status"] != "paid"]
    overdue = [(p, e) for p, e in unpaid if e["status"] == "overdue"]
    today_iso = today.isoformat()
    soon_iso = (today + timedelta(days=3)).isoformat()
    due_today = [(p, e) for p, e in unpaid if e["status"] != "overdue" and e["due_date"] == today_iso]
    soon = [(p, e) for p, e in unpaid if e["status"] != "overdue" and today_iso < e["due_date"] <= soon_iso]
    total = lambda rows: sum(e["amount_minor"] for _, e in rows)   # noqa: E731
    if overdue:
        lines.append(f"Overdue: {_plural(len(overdue), 'payment')}, {money(total(overdue), cur)} ({_titles([p['title'] for p, _ in overdue])})")
    if due_today:
        lines.append(f"Due today: {money(total(due_today), cur)} ({_titles([p['title'] for p, _ in due_today])})")
    if soon:
        lines.append(f"Next 3 days: {_plural(len(soon), 'payment')}, {money(total(soon), cur)}")

    try:
        tasks = await workspace.list_tasks(store, settings, "open")
    except ExpenseError:
        tasks = []
    late = [t["title"] for t in tasks if t["overdue"]]
    todays = [t["title"] for t in tasks if t["due_today"] and not t["overdue"]]
    if late:
        lines.append(f"Overdue tasks: {_titles(late)}")
    if todays:
        lines.append(f"Tasks today: {_titles(todays)}")

    rows = await store.fetchall("SELECT title, due_at FROM reminders WHERE status = 'pending' AND due_at IS NOT NULL ORDER BY due_at LIMIT 300")
    today_reminders = []
    for r in rows:
        due = timeutil.as_aware(r["due_at"], settings)
        if due is not None and due.astimezone(now.tzinfo).date() == today:
            today_reminders.append(f"{due.astimezone(now.tzinfo):%H:%M} {r['title']}")
    if today_reminders:
        lines.append(f"Reminders today: {_titles(today_reminders)}")

    title = f"Good morning · {now:%a} {now.day} {now:%b}"
    return title, "\n".join(lines) if lines else "Nothing due today. Enjoy the day."


async def send_if_due(store: Any, settings: Settings, notifier: Any, config: dict[str, Any] | None = None) -> bool:
    """Called from the scheduler's tick. Returns True when a briefing went out."""
    config = config if config is not None else await get_config(store)
    now = timeutil.now(settings)
    if not due(config, now) or not await claim_today(store, now.date().isoformat()):
        return False
    await deliver(store, settings, notifier)
    return True


async def deliver(store: Any, settings: Settings, notifier: Any) -> dict[str, Any]:
    title, body = await compose(store, settings)
    await store.execute(
        "INSERT INTO notifications (kind, title, body, created_at) VALUES ('digest', ?, ?, ?)", (title, body, _now_iso()),
    )
    result = await notifier.notify_digest(title, body) if notifier is not None else {}
    return {"title": title, "body": body, "delivery": result}
