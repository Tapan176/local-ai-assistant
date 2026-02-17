"""People/relationship memory tool."""

from __future__ import annotations

import re
from datetime import datetime

from tapan_ai.models import MemoryContext, ReasoningOutput, ToolExecutionResult
from tapan_ai.storage.graph_store import GraphStore
from tapan_ai.storage.sqlite_store import SQLiteStore


class PeopleTool:
    name = "people_tool"
    description = "Store and retrieve relationship information."

    def __init__(self, sqlite_store: SQLiteStore, graph_store: GraphStore) -> None:
        self.sqlite_store = sqlite_store
        self.graph_store = graph_store

    async def execute(
        self,
        session_id: str,
        user_text: str,
        reasoning: ReasoningOutput,
        memory: MemoryContext,
    ) -> ToolExecutionResult:
        del session_id, reasoning, memory
        lowered = user_text.lower()

        who_match = re.search(r"\bwho is\s+([a-zA-Z][a-zA-Z]{1,30})", user_text, flags=re.IGNORECASE)
        if who_match:
            name = who_match.group(1).title()
            row = await self.sqlite_store.fetchone(
                "SELECT name, relationship, notes FROM people WHERE name = ?",
                (name,),
            )
            if not row:
                return ToolExecutionResult(
                    tool_name=self.name,
                    success=False,
                    output_text=f"I don't have saved details for {name} yet.",
                )
            return ToolExecutionResult(
                tool_name=self.name,
                success=True,
                output_text=f"{row['name']} is recorded as your {row['relationship']}. {row['notes']}".strip(),
                data=row,
            )

        parsed = self._extract_person_relation(user_text)
        if not parsed:
            return ToolExecutionResult(
                tool_name=self.name,
                success=False,
                output_text="I can store people info, but I need a name and relationship.",
            )

        name, relationship, notes = parsed
        await self.sqlite_store.execute(
            """
            INSERT INTO people (name, relationship, notes, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                relationship = excluded.relationship,
                notes = excluded.notes,
                updated_at = excluded.updated_at
            """,
            (name, relationship, notes, datetime.utcnow().isoformat()),
        )
        await self.graph_store.add_relationship("user", name, relationship)

        msg = f"Saved. {name} is marked as your {relationship}."
        if notes:
            msg += f" Note: {notes}"
        return ToolExecutionResult(
            tool_name=self.name,
            success=True,
            output_text=msg,
            data={"source": "user", "target": name, "relation": relationship, "notes": notes},
            should_store_semantic=True,
        )

    @staticmethod
    def _extract_person_relation(text: str) -> tuple[str, str, str] | None:
        patterns = [
            r"([A-Z][a-zA-Z]{1,30})\s+is my\s+([a-zA-Z]{2,30})",
            r"my\s+([a-zA-Z]{2,30})\s+is\s+([A-Z][a-zA-Z]{1,30})",
        ]
        for idx, pattern in enumerate(patterns):
            match = re.search(pattern, text)
            if match:
                if idx == 0:
                    name, relation = match.group(1), match.group(2)
                else:
                    relation, name = match.group(1), match.group(2)
                notes = text.replace(match.group(0), "").strip(" .,-")
                return name, relation.lower(), notes
        return None
