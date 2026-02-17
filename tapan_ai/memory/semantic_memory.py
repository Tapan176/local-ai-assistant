"""Semantic fact memory with vector retrieval."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from tapan_ai.storage.sqlite_store import SQLiteStore
from tapan_ai.storage.vector_store import BaseVectorStore


class SemanticMemory:
    def __init__(self, sqlite_store: SQLiteStore, vector_store: BaseVectorStore) -> None:
        self.sqlite_store = sqlite_store
        self.vector_store = vector_store

    async def upsert_fact(self, fact_key: str, fact_value: str, confidence: float = 0.7) -> None:
        now = datetime.utcnow().isoformat()
        await self.sqlite_store.execute(
            """
            INSERT INTO semantic_facts (fact_key, fact_value, confidence, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (fact_key, fact_value, confidence, now),
        )

    async def remember_text(self, text: str, metadata: dict[str, Any] | None = None) -> str:
        metadata = metadata or {}
        doc_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        await self.sqlite_store.execute(
            """
            INSERT INTO semantic_documents (id, text_value, metadata_json, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (doc_id, text, json.dumps(metadata, ensure_ascii=True), now),
        )
        await self.vector_store.upsert(doc_id, text, metadata)
        return doc_id

    async def retrieve(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        vector_hits = await self.vector_store.query(query, limit=limit)
        fact_rows = await self.sqlite_store.fetchall(
            """
            SELECT fact_key, fact_value, confidence, updated_at
            FROM semantic_facts
            WHERE fact_key LIKE ? OR fact_value LIKE ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (f"%{query}%", f"%{query}%", limit),
        )
        if not fact_rows:
            fact_rows = await self.sqlite_store.fetchall(
                """
                SELECT fact_key, fact_value, confidence, updated_at
                FROM semantic_facts
                ORDER BY confidence DESC, id DESC
                LIMIT 2
                """
            )
        for row in fact_rows:
            vector_hits.append(
                {
                    "id": f"fact:{row['fact_key']}",
                    "text": f"{row['fact_key']}: {row['fact_value']}",
                    "metadata": {"confidence": row["confidence"], "updated_at": row["updated_at"]},
                    "score": float(row["confidence"]),
                }
            )
        vector_hits.sort(key=lambda item: item.get("score", 0.0), reverse=True)
        return vector_hits[:limit]

    async def consolidate(self) -> int:
        duplicates = await self.sqlite_store.fetchall(
            """
            SELECT fact_key, COUNT(*) AS total
            FROM semantic_facts
            GROUP BY fact_key
            HAVING COUNT(*) > 1
            """
        )
        removed = 0
        for item in duplicates:
            fact_key = item["fact_key"]
            keep = await self.sqlite_store.fetchone(
                """
                SELECT id
                FROM semantic_facts
                WHERE fact_key = ?
                ORDER BY confidence DESC, id DESC
                LIMIT 1
                """,
                (fact_key,),
            )
            if not keep:
                continue
            keep_id = int(keep["id"])
            await self.sqlite_store.execute(
                """
                DELETE FROM semantic_facts
                WHERE fact_key = ? AND id <> ?
                """,
                (fact_key, keep_id),
            )
            removed += int(item["total"]) - 1
        return removed
