"""Reminder management tool."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

try:
    import dateparser  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    dateparser = None

from tapan_ai.models import MemoryContext, ReasoningOutput, ToolExecutionResult
from tapan_ai.storage.sqlite_store import SQLiteStore


class ReminderTool:
    name = "reminder_tool"
    description = "Create and list reminders from natural text."

    def __init__(self, sqlite_store: SQLiteStore) -> None:
        self.sqlite_store = sqlite_store

    async def execute(
        self,
        session_id: str,
        user_text: str,
        reasoning: ReasoningOutput,
        memory: MemoryContext,
    ) -> ToolExecutionResult:
        del reasoning, memory
        lowered = user_text.lower()
        if any(word in lowered for word in ("show reminders", "list reminders", "what are my reminders")):
            return await self._list_reminders(session_id)

        title = self._extract_title(user_text)
        due = self._parse_datetime(user_text)
        due_iso = due.isoformat() if due else None

        await self.sqlite_store.execute(
            """
            INSERT INTO reminders (session_id, title, due_at, status, created_at)
            VALUES (?, ?, ?, 'pending', ?)
            """,
            (session_id, title, due_iso, datetime.utcnow().isoformat()),
        )

        if due_iso:
            msg = f"Reminder saved: '{title}' at {due.strftime('%Y-%m-%d %H:%M')}."
        else:
            msg = f"Reminder saved: '{title}'. Tell me the time whenever you want."

        return ToolExecutionResult(
            tool_name=self.name,
            success=True,
            output_text=msg,
            data={"title": title, "due_at": due_iso},
            should_store_semantic=True,
        )

    async def _list_reminders(self, session_id: str) -> ToolExecutionResult:
        reminders = await self.sqlite_store.fetchall(
            """
            SELECT id, title, due_at, status
            FROM reminders
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT 10
            """,
            (session_id,),
        )
        if not reminders:
            text = "No reminders yet."
        else:
            lines = []
            for item in reminders:
                due = item["due_at"] or "unscheduled"
                lines.append(f"#{item['id']} {item['title']} ({due}) [{item['status']}]")
            text = "Your reminders:\n" + "\n".join(lines)
        return ToolExecutionResult(
            tool_name=self.name,
            success=True,
            output_text=text,
            data={"reminders": reminders},
        )

    @staticmethod
    def _extract_title(text: str) -> str:
        patterns = [
            r"remind me to\s+(.+)",
            r"remember to\s+(.+)",
            r"don't let me forget to\s+(.+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip(" .")
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
        else:
            base = now if any(token in lowered for token in ("today", "tonight")) else None
        if base is None:
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
