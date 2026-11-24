"""Timezone-aware helpers shared by skills and the scheduler."""

from __future__ import annotations

from datetime import datetime, tzinfo

from src.config.settings import Settings


def get_tz(settings: Settings) -> tzinfo:
    if settings.timezone:
        try:
            from zoneinfo import ZoneInfo

            return ZoneInfo(settings.timezone)
        except Exception:  # unknown zone or missing tzdata on Windows
            pass
    return datetime.now().astimezone().tzinfo  # type: ignore[return-value]


def now(settings: Settings) -> datetime:
    return datetime.now(get_tz(settings))


def parse_when(text: str | None, settings: Settings) -> datetime | None:
    """Parse an ISO-8601 string or natural language ('tomorrow 5pm') into an aware datetime."""
    if not text or not str(text).strip():
        return None
    raw = str(text).strip()
    tz = get_tz(settings)
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=tz)
    except ValueError:
        pass
    try:
        import dateparser

        base = now(settings).replace(tzinfo=None)
        dt = dateparser.parse(raw, settings={"PREFER_DATES_FROM": "future", "RELATIVE_BASE": base})
        return dt.replace(tzinfo=tz) if dt else None
    except Exception:
        return None


def as_aware(value: str | None, settings: Settings) -> datetime | None:
    """Parse a stored ISO string; naive values are assumed to be in the user's timezone."""
    return parse_when(value, settings) if value else None
