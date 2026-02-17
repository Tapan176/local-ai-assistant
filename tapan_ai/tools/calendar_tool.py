"""Calendar scheduling tool."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

try:
    import dateparser  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    dateparser = None

from tapan_ai.models import MemoryContext, ReasoningOutput, ToolExecutionResult
from tapan_ai.storage.sqlite_store import SQLiteStore


class CalendarTool:
    name = "calendar_tool"
    description = "Create and inspect calendar events."

    def __init__(self, sqlite_store: SQLiteStore) -> None:
        self.sqlite_store = sqlite_store

    async def execute(
        self,
        session_id: str,
        user_text: str,
        reasoning: ReasoningOutput,
        memory: MemoryContext,
    ) -> ToolExecutionResult:
        del session_id, reasoning, memory
        lowered = user_text.lower()
        if any(word in lowered for word in ("what's next", "next event", "upcoming meetings", "upcoming events")):
            return await self._upcoming_events()

        start = self._parse_datetime(user_text)
        if start is None:
            return ToolExecutionResult(
                tool_name=self.name,
                success=False,
                output_text="I can schedule that, but I need a clear date or time.",
            )
        end = start + timedelta(hours=1)
        title = self._extract_title(user_text)

        await self.sqlite_store.execute(
            """
            INSERT INTO calendar_events (title, start_at, end_at, location, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (title, start.isoformat(), end.isoformat(), "", user_text[:160], datetime.utcnow().isoformat()),
        )
        msg = f"Scheduled '{title}' for {start.strftime('%Y-%m-%d %H:%M')}."
        return ToolExecutionResult(
            tool_name=self.name,
            success=True,
            output_text=msg,
            data={"title": title, "start_at": start.isoformat(), "end_at": end.isoformat()},
            should_store_semantic=True,
        )

    async def _upcoming_events(self) -> ToolExecutionResult:
        now_iso = datetime.utcnow().isoformat()
        rows = await self.sqlite_store.fetchall(
            """
            SELECT title, start_at, end_at
            FROM calendar_events
            WHERE start_at >= ?
            ORDER BY start_at
            LIMIT 5
            """,
            (now_iso,),
        )
        if not rows:
            text = "No upcoming events found."
        else:
            lines = [f"{row['title']} at {row['start_at']}" for row in rows]
            text = "Upcoming events:\n" + "\n".join(lines)
        return ToolExecutionResult(
            tool_name=self.name,
            success=True,
            output_text=text,
            data={"events": rows},
        )

    @staticmethod
    def _extract_title(text: str) -> str:
        patterns = [
            r"schedule\s+(.+?)\s+(?:on|at|for)\b",
            r"add\s+(.+?)\s+(?:on|at|for)\b",
            r"meeting with\s+(.+?)\s+(?:on|at|for)\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip().title()
        return text.strip()[:120]

    @staticmethod
    def _parse_datetime(text: str) -> datetime | None:
        if dateparser is not None:
            return dateparser.parse(text, settings={"PREFER_DATES_FROM": "future"})

        lowered = text.lower()
        now = datetime.utcnow().replace(second=0, microsecond=0)
        if "tomorrow" in lowered:
            base = now + timedelta(days=1)
        elif "next week" in lowered:
            base = now + timedelta(days=7)
        elif "today" in lowered:
            base = now
        else:
            return None

        time_match = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", lowered)
        if not time_match:
            return base
        hour = int(time_match.group(1))
        minute = int(time_match.group(2) or 0)
        meridiem = time_match.group(3)
        if meridiem == "pm" and hour < 12:
            hour += 12
        if meridiem == "am" and hour == 12:
            hour = 0
        if meridiem is None and hour < 8:
            hour += 12
        return base.replace(hour=hour % 24, minute=minute)
