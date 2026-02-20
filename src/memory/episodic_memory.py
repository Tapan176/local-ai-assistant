"""Chronological conversation and event memory."""

from __future__ import annotations

import json

from src.models import ConversationTurn, model_dump_compat
from src.storage.sqlite_store import SQLiteStore


class EpisodicMemory:
    def __init__(self, sqlite_store: SQLiteStore) -> None:
        self.sqlite_store = sqlite_store

    async def add_turn(self, turn: ConversationTurn) -> None:
        payload = model_dump_compat(turn)
        metadata = json.dumps(payload.get("metadata", {}), ensure_ascii=True)
        await self.sqlite_store.execute(
            """
            INSERT INTO episodes (
                session_id, timestamp, user_text, assistant_text,
                emotional_state, tool_used, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                turn.session_id,
                turn.timestamp.isoformat(),
                turn.user_text,
                turn.assistant_text,
                turn.emotional_state,
                turn.tool_used,
                metadata,
            ),
        )

    async def recent(self, session_id: str, limit: int = 8) -> list[dict]:
        rows = await self.sqlite_store.fetchall(
            """
            SELECT session_id, timestamp, user_text, assistant_text, emotional_state, tool_used, metadata_json
            FROM episodes
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (session_id, limit),
        )
        out = []
        for row in rows:
            row["metadata"] = self.sqlite_store.parse_json_field(row.pop("metadata_json", "{}"))
            out.append(row)
        out.reverse()
        return out

    async def search(self, session_id: str, query: str, limit: int = 5) -> list[dict]:
        pattern = f"%{query.strip()}%"
        rows = await self.sqlite_store.fetchall(
            """
            SELECT session_id, timestamp, user_text, assistant_text, emotional_state, tool_used, metadata_json
            FROM episodes
            WHERE session_id = ?
            AND (user_text LIKE ? OR assistant_text LIKE ?)
            ORDER BY id DESC
            LIMIT ?
            """,
            (session_id, pattern, pattern, limit),
        )
        out = []
        for row in rows:
            row["metadata"] = self.sqlite_store.parse_json_field(row.pop("metadata_json", "{}"))
            out.append(row)
        return out

