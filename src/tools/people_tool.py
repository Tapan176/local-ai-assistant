"""People/relationship memory tool."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from src.models import MemoryContext, ReasoningOutput, ToolExecutionResult
from src.storage.supermemory_store import SupermemoryStore
from src.storage.sqlite_store import SQLiteStore


class PeopleTool:
    name = "people_tool"
    description = "Store and retrieve relationship information."

    def __init__(self, sqlite_store: SQLiteStore, supermemory_store: SupermemoryStore) -> None:
        self.sqlite_store = sqlite_store
        self.supermemory = supermemory_store

    async def execute(
        self,
        session_id: str,
        user_text: str,
        reasoning: ReasoningOutput,
        memory: MemoryContext,
    ) -> ToolExecutionResult:
        del session_id, reasoning, memory
        lowered = user_text.lower()

        if any(token in lowered for token in ("list people", "show people", "friend list", "list relations", "show friends", "my contacts")):
            return await self._list_people()
        if any(token in lowered for token in ("delete person", "remove person", "delete relation", "remove relation")):
            return await self._delete_person(user_text)

        # "name X relation Y" or "name X, relation Y"
        name_relation_match = re.search(
            r"\bname\s+([a-zA-Z][a-zA-Z\s]{0,30}?)\s+(?:relation|rel)\s*[:=]?\s*([a-zA-Z][a-zA-Z\s]{0,30})",
            user_text,
            flags=re.IGNORECASE,
        )
        if name_relation_match:
            name = name_relation_match.group(1).strip().title()
            relation = name_relation_match.group(2).strip().lower()
            if name and relation:
                await self.sqlite_store.execute(
                    """
                    INSERT INTO people (name, relationship, notes, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(name) DO UPDATE SET
                        relationship = excluded.relationship,
                        notes = excluded.notes,
                        updated_at = excluded.updated_at
                    """,
                    (name, relation, "", datetime.now(timezone.utc).isoformat()),
                )
                await self.supermemory.add_memory(
                    content=f"user is {relation} of {name}",
                    container_tag="relationships",
                    metadata={"source": "user", "target": name, "relation": relation},
                )
                return ToolExecutionResult(
                    tool_name=self.name,
                    success=True,
                    output_text=f"Saved. {name} is your {relation}.",
                    data={"source": "user", "target": name, "relation": relation},
                    should_store_semantic=True,
                )

        who_match = re.search(r"\bwho is\s+([a-zA-Z][a-zA-Z]{1,30})", user_text, flags=re.IGNORECASE)
        if who_match:
            name = who_match.group(1).title()
            row = await self.sqlite_store.fetchone(
                "SELECT name, relationship, notes FROM people WHERE lower(name) = lower(?)",
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
                output_text="I can store people info. Say e.g. 'Roy is my friend' or 'add a friend Roy' or 'name Roy relation friend'.",
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
            (name, relationship, notes, datetime.now(timezone.utc).isoformat()),
        )
        await self.supermemory.add_memory(
            content=f"user is {relationship} of {name}",
            container_tag="relationships",
            metadata={"source": "user", "target": name, "relation": relationship},
        )

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

    async def _list_people(self) -> ToolExecutionResult:
        rows = await self.sqlite_store.fetchall(
            """
            SELECT name, relationship, notes
            FROM people
            ORDER BY updated_at DESC, name ASC
            LIMIT 30
            """
        )
        if not rows:
            return ToolExecutionResult(
                tool_name=self.name,
                success=True,
                output_text="No people saved yet.",
                data={"people": []},
            )
        lines = [f"{row['name']} ({row['relationship']})" for row in rows]
        return ToolExecutionResult(
            tool_name=self.name,
            success=True,
            output_text="People in memory:\n" + "\n".join(lines),
            data={"people": rows},
        )

    async def _delete_person(self, user_text: str) -> ToolExecutionResult:
        name = self._extract_person_name_for_delete(user_text)
        if not name:
            return ToolExecutionResult(
                tool_name=self.name,
                success=False,
                output_text="Tell me the person's name to remove.",
            )
        await self.sqlite_store.execute(
            "DELETE FROM people WHERE lower(name) = lower(?)",
            (name,),
        )
        return ToolExecutionResult(
            tool_name=self.name,
            success=True,
            output_text=f"Removed {name} from people memory.",
            data={"target": name},
            should_store_semantic=True,
        )

    @staticmethod
    def _extract_person_relation(text: str) -> tuple[str, str, str] | None:
        # "add a friend Roy who has a joyful nature" / "add friend Roy"
        add_friend = re.search(
            r"add\s+(?:a\s+)?friend\s+([a-zA-Z][a-zA-Z\s]{0,30}?)(?:\s+who\s+has\s+(?:a\s+)?(.+?))?(?:\s*\.|$)",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if add_friend:
            name = add_friend.group(1).strip().title()
            notes = (add_friend.group(2).strip() if add_friend.group(2) else "").strip(" .,")
            if name:
                return name, "friend", notes

        # "add contact X as Y" / "add person X, relation Y"
        add_contact = re.search(
            r"add\s+(?:contact|person)\s+([a-zA-Z][a-zA-Z\s]{0,30}?)(?:\s+as\s+|\s*,\s*relation\s+)([a-zA-Z][a-zA-Z\s]{0,30})",
            text,
            flags=re.IGNORECASE,
        )
        if add_contact:
            name = add_contact.group(1).strip().title()
            relation = add_contact.group(2).strip().lower()
            if name and relation:
                return name, relation, ""

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

    @staticmethod
    def _extract_person_name_for_delete(text: str) -> str | None:
        match = re.search(
            r"(?:delete|remove)\s+(?:person|relation)?\s*([a-zA-Z][a-zA-Z]{1,30})",
            text,
            flags=re.IGNORECASE,
        )
        if not match:
            return None
        return match.group(1).title()
