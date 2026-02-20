"""Reminder management tool."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from src.models import MemoryContext, ReasoningOutput, ToolExecutionResult
from src.storage.sqlite_store import SQLiteStore
from src.utils.date_time_parser import RelativeDateTimeParser


class ReminderTool:
    name = "reminder_tool"
    description = "Create and list reminders from natural text."

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
        del reasoning, memory
        lowered = user_text.lower()
        if any(word in lowered for word in ("show reminders", "list reminders", "what are my reminders")):
            include_done = "all" in lowered
            overdue_only = "overdue" in lowered
            return await self._list_reminders(session_id, include_done=include_done, overdue_only=overdue_only)

        if any(token in lowered for token in ("mark done", "done reminder", "complete reminder")):
            return await self._mark_done(session_id, user_text)
        if any(token in lowered for token in ("delete reminder", "remove reminder")):
            return await self._delete_reminder(session_id, user_text)
        if "update reminder" in lowered:
            return await self._update_reminder(session_id, user_text)

        title = self._extract_title(user_text)
        due, _ = self.date_parser.parse(user_text)
        due_iso = due.isoformat() if due else None

        await self.sqlite_store.execute(
            """
            INSERT INTO reminders (session_id, title, due_at, status, created_at)
            VALUES (?, ?, ?, 'pending', ?)
            """,
            (session_id, title, due_iso, datetime.now(timezone.utc).isoformat()),
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

    async def _list_reminders(
        self,
        session_id: str,
        include_done: bool = False,
        overdue_only: bool = False,
    ) -> ToolExecutionResult:
        clauses = ["session_id = ?"]
        params: list[object] = [session_id]
        if not include_done:
            clauses.append("status = 'pending'")
        if overdue_only:
            clauses.append("due_at IS NOT NULL AND due_at <= ?")
            params.append(datetime.now(timezone.utc).isoformat())
        where_sql = " AND ".join(clauses)
        reminders = await self.sqlite_store.fetchall(
            f"""
            SELECT id, title, due_at, status
            FROM reminders
            WHERE {where_sql}
            ORDER BY id DESC
            LIMIT 20
            """,
            tuple(params),
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

    async def _mark_done(self, session_id: str, user_text: str) -> ToolExecutionResult:
        reminder_id = self._extract_id(user_text)
        if reminder_id is not None:
            await self.sqlite_store.execute(
                """
                UPDATE reminders
                SET status = 'done'
                WHERE session_id = ? AND id = ?
                """,
                (session_id, reminder_id),
            )
            return ToolExecutionResult(
                tool_name=self.name,
                success=True,
                output_text=f"Reminder #{reminder_id} marked as done.",
                data={"id": reminder_id},
            )

        text_hint = self._extract_text_hint(user_text)
        if text_hint:
            await self.sqlite_store.execute(
                """
                UPDATE reminders
                SET status = 'done'
                WHERE session_id = ? AND title LIKE ?
                """,
                (session_id, f"%{text_hint}%"),
            )
            return ToolExecutionResult(
                tool_name=self.name,
                success=True,
                output_text=f"Marked reminders matching '{text_hint}' as done.",
                data={"text": text_hint},
            )
        return ToolExecutionResult(
            tool_name=self.name,
            success=False,
            output_text="Tell me the reminder id or text to mark as done.",
        )

    async def _delete_reminder(self, session_id: str, user_text: str) -> ToolExecutionResult:
        reminder_id = self._extract_id(user_text)
        if reminder_id is not None:
            await self.sqlite_store.execute(
                "DELETE FROM reminders WHERE session_id = ? AND id = ?",
                (session_id, reminder_id),
            )
            return ToolExecutionResult(
                tool_name=self.name,
                success=True,
                output_text=f"Deleted reminder #{reminder_id}.",
                data={"id": reminder_id},
            )

        text_hint = self._extract_text_hint(user_text)
        if text_hint:
            await self.sqlite_store.execute(
                "DELETE FROM reminders WHERE session_id = ? AND title LIKE ?",
                (session_id, f"%{text_hint}%"),
            )
            return ToolExecutionResult(
                tool_name=self.name,
                success=True,
                output_text=f"Deleted reminders matching '{text_hint}'.",
                data={"text": text_hint},
            )
        return ToolExecutionResult(
            tool_name=self.name,
            success=False,
            output_text="Tell me the reminder id or text to delete.",
        )

    async def _update_reminder(self, session_id: str, user_text: str) -> ToolExecutionResult:
        reminder_id = self._extract_id(user_text)
        if reminder_id is None:
            return ToolExecutionResult(
                tool_name=self.name,
                success=False,
                output_text="Use an id to update reminder, for example: update reminder 3 to ...",
            )
        title_match = re.search(r"\bto\s+(.+)", user_text, flags=re.IGNORECASE)
        new_title = title_match.group(1).strip() if title_match else None
        due, _ = self.date_parser.parse(user_text)
        due_iso = due.isoformat() if due else None

        existing = await self.sqlite_store.fetchone(
            "SELECT title, due_at FROM reminders WHERE session_id = ? AND id = ?",
            (session_id, reminder_id),
        )
        if not existing:
            return ToolExecutionResult(
                tool_name=self.name,
                success=False,
                output_text=f"I could not find reminder #{reminder_id}.",
            )

        await self.sqlite_store.execute(
            """
            UPDATE reminders
            SET title = ?, due_at = ?
            WHERE session_id = ? AND id = ?
            """,
            (
                new_title or existing["title"],
                due_iso or existing["due_at"],
                session_id,
                reminder_id,
            ),
        )
        return ToolExecutionResult(
            tool_name=self.name,
            success=True,
            output_text=f"Updated reminder #{reminder_id}.",
            data={"id": reminder_id, "title": new_title, "due_at": due_iso},
            should_store_semantic=True,
        )

    @staticmethod
    def _extract_title(text: str) -> str:
        patterns = [
            r"remind me to\s+(.+)",
            r"remember to\s+(.+)",
            r"don't let me forget to\s+(.+)",
            r"mujhe\s+(.+)\s+yaad dila",
            r"(.+)\s+yaad dila",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                value = match.group(1).strip(" .")
                value = re.sub(r"^(bro|bhai|yaar)\s+", "", value, flags=re.IGNORECASE)
                return value
        clean = re.sub(r"^(bro|bhai|yaar)\s+", "", text.strip(), flags=re.IGNORECASE)
        return clean[:120]

    @staticmethod
    def _extract_id(text: str) -> int | None:
        match = re.search(r"(?:reminder\s*)?#?(\d+)", text, flags=re.IGNORECASE)
        if not match:
            return None
        return int(match.group(1))

    @staticmethod
    def _extract_text_hint(text: str) -> str | None:
        match = re.search(r"(?:delete|remove|done|complete)\s+reminder\s+(.+)", text, flags=re.IGNORECASE)
        if match:
            value = match.group(1).strip(" .")
            if value:
                return value
        return None
