"""Calendar scheduling tool."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from src.models import MemoryContext, ReasoningOutput, ToolExecutionResult
from src.storage.sqlite_store import SQLiteStore
from src.utils.date_time_parser import RelativeDateTimeParser


class CalendarTool:
    name = "calendar_tool"
    description = "Create and inspect calendar events."

    def __init__(self, sqlite_store: SQLiteStore) -> None:
        self.sqlite_store = sqlite_store
        self.date_parser = RelativeDateTimeParser()

    async def execute(
        self,
        session_id: str,
        user_text: str,
        reasoning: ReasoningOutput,
        memory: MemoryContext,
    ) -> ToolExecutionResult:
        del session_id, reasoning, memory
        lowered = user_text.lower()
        if any(word in lowered for word in ("what's next", "next event", "upcoming meetings", "upcoming events", "agenda", "show tasks", "list tasks", "my tasks", "check tasks", "fetch")):
            return await self._upcoming_events()
        if "today" in lowered and any(word in lowered for word in ("tasks", "events", "agenda")):
             return await self._upcoming_events()

        if any(word in lowered for word in ("delete event", "remove event", "cancel event")):
            return await self._delete_event(user_text)

        start, parsed = self.date_parser.parse(user_text)
        if start is None:
            # Fallback: if user wants to "check" or "retrieve" but we missed the specific phrase above,
            # try to show events if "calendar" or "schedule" is mentioned in a query context.
            if any(w in lowered for w in ("check", "show", "list", "what is", "fetch", "get")):
                return await self._upcoming_events()

            return ToolExecutionResult(
                tool_name=self.name,
                success=False,
                output_text="I can schedule that, but I need a clear date or time.",
            )
        
        # Linter guard
        assert start is not None

        duration_hours = 1
        duration_match = re.search(r"for\s+(\d+)\s*(hour|hr|hours)", lowered)
        if duration_match:
            duration_hours = max(1, int(duration_match.group(1)))
        
        end = start + timedelta(hours=duration_hours)
        title = self._extract_title(user_text)
        
        if not parsed and len(title.split()) <= 2:
            return ToolExecutionResult(
                tool_name=self.name,
                success=False,
                output_text="I need a clearer schedule phrase, like 'schedule design review tomorrow at 5 pm'.",
            )

        await self.sqlite_store.execute(
            """
            INSERT INTO calendar_events (title, start_at, end_at, location, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (title, start.isoformat(), end.isoformat(), "", str(user_text)[:160], datetime.now(timezone.utc).isoformat()),
        )
        msg = f"Scheduled '{title}' for {start.strftime('%Y-%m-%d %H:%M')}."
        return ToolExecutionResult(
            tool_name=self.name,
            success=True,
            output_text=msg,
            data={
                "title": title,
                "start_at": start.isoformat(),
                "end_at": end.isoformat(),
                "duration_hours": duration_hours,
            },
            should_store_semantic=True,
        )

    async def _upcoming_events(self) -> ToolExecutionResult:
        now_iso = datetime.now(timezone.utc).isoformat()
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

    async def _delete_event(self, user_text: str) -> ToolExecutionResult:
        event_id = self._extract_id(user_text)
        if event_id is not None:
            await self.sqlite_store.execute("DELETE FROM calendar_events WHERE id = ?", (event_id,))
            return ToolExecutionResult(
                tool_name=self.name,
                success=True,
                output_text=f"Deleted event #{event_id}.",
                data={"id": event_id},
            )

        title_hint = self._extract_text_hint(user_text)
        if not title_hint:
            return ToolExecutionResult(
                tool_name=self.name,
                success=False,
                output_text="Tell me event id or title to remove.",
            )
        await self.sqlite_store.execute(
            "DELETE FROM calendar_events WHERE title LIKE ?",
            (f"%{title_hint}%",),
        )
        return ToolExecutionResult(
            tool_name=self.name,
            success=True,
            output_text=f"Deleted events matching '{title_hint}'.",
            data={"title_hint": title_hint},
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
    def _extract_id(text: str) -> int | None:
        match = re.search(r"(?:event\s*)?#?(\d+)", text, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
        return None

    @staticmethod
    def _extract_text_hint(text: str) -> str | None:
        match = re.search(r"(?:delete|remove|cancel)\s+event\s+(.+)", text, flags=re.IGNORECASE)
        if not match:
            return None
        value = match.group(1).strip(" .")
        return value or None
