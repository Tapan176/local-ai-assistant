"""Chronological conversation and event memory."""

from __future__ import annotations

import json

from src.models import ConversationTurn, model_dump_compat
from src.storage.sqlite_store import SQLiteStore
from src.storage.supermemory_store import SupermemoryStore


class EpisodicMemory:
    def __init__(self, sqlite_store: SQLiteStore, supermemory_store: SupermemoryStore) -> None:
        self.sqlite_store = sqlite_store
        self.supermemory = supermemory_store

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

        # Index the turn for semantic retrieval via Supermemory
        semantic_text = f"User: {turn.user_text}\nAssistant: {turn.assistant_text}"
        await self.supermemory.add_memory(
            content=semantic_text,
            container_tag=f"session_{turn.session_id}",
            metadata={
                "timestamp": turn.timestamp.isoformat(),
                "emotional_state": turn.emotional_state,
            }
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
        """Search past episodes — try Supermemory first, SQLite LIKE fallback."""
        # 1. Semantic search via Supermemory
        results = await self.supermemory.search_memory(
            query=query,
            filters={"container_tag": f"session_{session_id}"}
        )
        out: list[dict] = []
        for res in results:
            metadata = res.get("metadata", {}) if isinstance(res, dict) else {}
            content = res.get("content", str(res)) if isinstance(res, dict) else str(res)
            score = res.get("score", 1.0) if isinstance(res, dict) else 1.0
            out.append({
                "session_id": session_id,
                "timestamp": metadata.get("timestamp", ""),
                "emotional_state": metadata.get("emotional_state", ""),
                "text": content,
                "score": score,
                "source": "supermemory"
            })

        # 2. Fallback to SQLite text search if Supermemory returned nothing
        if not out:
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
            for row in rows:
                row["metadata"] = self.sqlite_store.parse_json_field(row.pop("metadata_json", "{}"))
                out.append(row)
        return out[:limit]

