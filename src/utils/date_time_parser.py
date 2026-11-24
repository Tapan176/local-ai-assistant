"""Robust relative datetime parsing with multilingual-friendly heuristics."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

try:
    import dateparser  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    dateparser = None


class RelativeDateTimeParser:
    _MONTHS = {
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "may": 5,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12,
    }

    def parse(self, text: str, reference: datetime | None = None) -> tuple[datetime | None, bool]:
        if not text:
            return None, False
        reference = reference or datetime.now(timezone.utc).replace(second=0, microsecond=0)
        lowered = text.lower().strip()

        time_hint = self._extract_time(lowered)

        if "day after tomorrow" in lowered or "parso" in lowered:
            base = reference + timedelta(days=2)
            return self._apply_time(base, time_hint), True
        if "tomorrow" in lowered or re.search(r"\bkal\b", lowered):
            base = reference + timedelta(days=1)
            return self._apply_time(base, time_hint), True
        if "next week" in lowered:
            base = reference + timedelta(days=7)
            return self._apply_time(base, time_hint), True
        if "next month" in lowered:
            base = reference + timedelta(days=30)
            return self._apply_time(base, time_hint), True
        if "next year" in lowered:
            try:
                base = reference.replace(year=reference.year + 1)
            except ValueError:
                base = reference + timedelta(days=365)
            return self._apply_time(base, time_hint), True

        in_years = re.search(r"(?:after|in)\s+(\d+)\s*years?", lowered)
        if in_years:
            years = int(in_years.group(1))
            try:
                base = reference.replace(year=reference.year + years)
            except ValueError:
                base = reference + timedelta(days=365 * years)
            return self._apply_time(base, time_hint), True

        in_months = re.search(r"(?:after|in)\s+(\d+)\s*months?", lowered)
        if in_months:
            months = int(in_months.group(1))
            base = reference + timedelta(days=30 * months)
            return self._apply_time(base, time_hint), True

        date_match = re.search(
            r"(?:on\s+)?(\d{1,2})\s*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*(?:\s+(\d{4}))?",
            lowered,
        )
        if date_match:
            day = int(date_match.group(1))
            month = self._MONTHS.get(date_match.group(2)[:3], 1)
            year = int(date_match.group(3)) if date_match.group(3) else reference.year
            try:
                dt = datetime(year, month, day, 9, 0)
                if dt < reference and not date_match.group(3):
                    dt = datetime(year + 1, month, day, 9, 0)
                return self._apply_time(dt, time_hint), True
            except ValueError:
                return None, False

        if time_hint is not None:
            maybe_today = self._apply_time(reference, time_hint)
            if maybe_today <= reference:
                maybe_today += timedelta(days=1)
            return maybe_today, True

        if dateparser is not None:
            parsed = dateparser.parse(lowered, settings={"PREFER_DATES_FROM": "future"})
            if parsed is not None:
                parsed = parsed.replace(second=0, microsecond=0)
                return parsed, True

        return None, False

    @staticmethod
    def _extract_time(text: str) -> tuple[int, int] | None:
        # Prefer explicit AM/PM expressions, then "at HH[:MM]".
        match = re.search(r"\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", text)
        if not match:
            match = re.search(r"\bat\s+(\d{1,2})(?::(\d{2}))?\b", text)
        if not match:
            match = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*baje\b", text)
        if not match:
            return None
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        meridiem = match.group(3) if len(match.groups()) >= 3 else None

        if meridiem is None and "baje" in text:
            if any(token in text for token in ("subah", "morning")):
                meridiem = "am"
            elif any(token in text for token in ("shaam", "evening", "raat", "night")):
                meridiem = "pm"

        if meridiem == "pm" and hour < 12:
            hour += 12
        if meridiem == "am" and hour == 12:
            hour = 0
        if meridiem is None and hour < 7:
            hour += 12
        return hour % 24, minute

    @staticmethod
    def _apply_time(base: datetime, time_hint: tuple[int, int] | None) -> datetime:
        if time_hint is None:
            return base.replace(hour=9, minute=0, second=0, microsecond=0)
        hour, minute = time_hint
        return base.replace(hour=hour, minute=minute, second=0, microsecond=0)
