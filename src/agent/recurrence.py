"""Recurring reminders: rules, wall-clock arithmetic and plain-English descriptions.

Rules are stored as small JSON on the reminder row. All arithmetic is done on the *wall clock* in the user's time zone, so
"every day at 9:00" stays 9:00 across daylight-saving changes, and "monthly on the 31st" means the last day of shorter months
without drifting (the anchor day is remembered, not recomputed from the clamped date).
"""

from __future__ import annotations

import json
import calendar
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any

REPEATS = ("daily", "weekdays", "weekly", "monthly", "yearly")
WEEKDAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_ALIASES = {"day": "daily", "everyday": "daily", "week": "weekly", "month": "monthly", "year": "yearly", "annually": "yearly",
            "weekday": "weekdays", "workdays": "weekdays", "workday": "weekdays"}
MAX_EVERY = 365
MAX_STEPS = 100_000                       # guard against a pathological rule; ~270 years of daily steps


class RuleError(ValueError):
    """A recurrence request that cannot be honoured (message is shown to the user)."""


@dataclass(frozen=True)
class Rule:
    repeat: str
    every: int = 1
    days: tuple[int, ...] = field(default_factory=tuple)      # weekly: weekday numbers (Mon=0)
    day: int | None = None                                    # monthly/yearly: the anchor day of month

    def to_json(self) -> str:
        return json.dumps({"repeat": self.repeat, "every": self.every, "days": list(self.days), "day": self.day})

    @classmethod
    def from_json(cls, text: str | None) -> "Rule | None":
        if not text:
            return None
        try:
            data = json.loads(text)
            return cls(str(data["repeat"]), int(data.get("every", 1)), tuple(int(d) for d in data.get("days") or ()), data.get("day"))
        except (ValueError, KeyError, TypeError):
            return None


def _weekday(value: Any) -> int:
    if isinstance(value, int) or (isinstance(value, str) and value.strip().isdigit()):
        n = int(value)
        if 0 <= n <= 6:
            return n
        raise RuleError(f"Weekday number {n} is out of range (0 = Monday … 6 = Sunday).")
    text = str(value).strip().lower()
    for i, name in enumerate(WEEKDAY_NAMES):
        if text and (name == text or name.startswith(text[:3]) and len(text) >= 3 and name.startswith(text)):
            return i
    raise RuleError(f"I don't know the weekday “{value}”.")


def build_rule(repeat: str | None, every: Any = None, days: Any = None, anchor: datetime | None = None) -> Rule | None:
    """Validate and normalise what the model sends. None means 'does not repeat'."""
    if repeat is None or str(repeat).strip().lower() in ("", "none", "once", "no", "never", "false"):
        return None
    kind = _ALIASES.get(str(repeat).strip().lower(), str(repeat).strip().lower())
    if kind not in REPEATS:
        raise RuleError(f"Unsupported repeat “{repeat}”. Use one of: {', '.join(REPEATS)}.")
    try:
        n = int(every) if every not in (None, "") else 1
    except (TypeError, ValueError):
        raise RuleError("“every” must be a whole number.") from None
    if not 1 <= n <= MAX_EVERY:
        raise RuleError(f"“every” must be between 1 and {MAX_EVERY}.")
    if kind == "weekdays" and n != 1:
        raise RuleError("“weekdays” cannot be combined with every N.")
    chosen: tuple[int, ...] = ()
    if kind == "weekly":
        raw = days if isinstance(days, (list, tuple)) else ([d for d in str(days).replace(",", " ").split()] if days else [])
        chosen = tuple(sorted({_weekday(d) for d in raw})) or ((anchor.weekday(),) if anchor else ())
        if not chosen:
            raise RuleError("A weekly reminder needs at least one weekday.")
    elif days:
        raise RuleError("“days” only applies to weekly reminders.")
    anchor_day = anchor.day if anchor and kind in ("monthly", "yearly") else None
    return Rule(kind, n, chosen, anchor_day)


# ── arithmetic ──────────────────────────────────────────────────────
def _at(d: date, t: time, tz: tzinfo) -> datetime:
    return datetime.combine(d, t, tzinfo=tz)                  # wall-clock construction: DST-correct, never shifts the hour


def _add_months(year: int, month: int, n: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + n
    return index // 12, index % 12 + 1


def _clamp(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def step(rule: Rule, current: datetime, tz: tzinfo, anchor: datetime | None = None) -> datetime:
    """The occurrence after `current` (same wall-clock time of day)."""
    local = current.astimezone(tz)
    d, t = local.date(), local.timetz().replace(tzinfo=None)
    if rule.repeat == "daily":
        return _at(d + timedelta(days=rule.every), t, tz)
    if rule.repeat == "weekdays":
        nxt = d + timedelta(days=1)
        while nxt.weekday() >= 5:
            nxt += timedelta(days=1)
        return _at(nxt, t, tz)
    if rule.repeat == "weekly":
        origin = (anchor or current).astimezone(tz).date()
        week0 = origin - timedelta(days=origin.weekday())      # Monday of the anchor week: defines which weeks "count" for every=N
        nxt = d + timedelta(days=1)
        for _ in range(7 * rule.every + 8):
            in_week = ((nxt - week0).days // 7) % rule.every == 0
            if nxt.weekday() in rule.days and in_week:
                return _at(nxt, t, tz)
            nxt += timedelta(days=1)
        raise RuleError("Could not compute the next weekly occurrence.")
    if rule.repeat == "monthly":
        y, m = _add_months(d.year, d.month, rule.every)
        return _at(_clamp(y, m, rule.day or d.day), t, tz)
    if rule.repeat == "yearly":
        return _at(_clamp(d.year + rule.every, d.month, rule.day or d.day), t, tz)
    raise RuleError(f"Unsupported repeat “{rule.repeat}”.")


def latest_and_next(rule: Rule, due: datetime, now: datetime, tz: tzinfo, anchor: datetime | None = None) -> tuple[datetime, datetime]:
    """Given the stored due time, return (the most recent occurrence <= now, the first occurrence > now).

    If the server slept through several occurrences, only the latest one fires, once: a daily reminder that was missed for
    three days is one notification, not three, and the next one is scheduled in the future.
    """
    current = due
    for _ in range(MAX_STEPS):
        nxt = step(rule, current, tz, anchor)
        if nxt > now:
            return current, nxt
        current = nxt
    raise RuleError("Recurrence did not converge.")


def next_after(rule: Rule, due: datetime, now: datetime, tz: tzinfo, anchor: datetime | None = None) -> datetime:
    return latest_and_next(rule, due, now, tz, anchor)[1]


# ── words ───────────────────────────────────────────────────────────
def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def describe(rule: Rule | None) -> str | None:
    if rule is None:
        return None
    n = rule.every
    if rule.repeat == "daily":
        return "every day" if n == 1 else f"every {n} days"
    if rule.repeat == "weekdays":
        return "every weekday"
    if rule.repeat == "weekly":
        names = ", ".join(WEEKDAY_NAMES[d].capitalize()[:3] for d in rule.days)
        return f"every {'week' if n == 1 else f'{n} weeks'} on {names}"
    if rule.repeat == "monthly":
        return f"{'every month' if n == 1 else f'every {n} months'} on the {_ordinal(rule.day)}" if rule.day else ("every month" if n == 1 else f"every {n} months")
    if rule.repeat == "yearly":
        return "every year" if n == 1 else f"every {n} years"
    return rule.repeat
