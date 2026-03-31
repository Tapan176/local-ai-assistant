"""Semantic fact memory with vector retrieval."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from src.storage.sqlite_store import SQLiteStore
from src.storage.supermemory_store import SupermemoryStore


class SemanticMemory:
    def __init__(self, sqlite_store: SQLiteStore, supermemory_store: SupermemoryStore) -> None:
        self.sqlite_store = sqlite_store
        self.supermemory = supermemory_store

    async def upsert_fact(self, fact_key: str, fact_value: str, confidence: float = 0.7) -> None:
        now = datetime.now(timezone.utc).isoformat()
        # Check if fact already exists; update if so
        existing = await self.sqlite_store.fetchone(
            "SELECT id FROM semantic_facts WHERE fact_key = ?", (fact_key,)
        )
        if existing:
            await self.sqlite_store.execute(
                "UPDATE semantic_facts SET fact_value = ?, confidence = ?, updated_at = ? WHERE fact_key = ?",
                (fact_value, confidence, now, fact_key),
            )
        else:
            await self.sqlite_store.execute(
                "INSERT INTO semantic_facts (fact_key, fact_value, confidence, updated_at) VALUES (?, ?, ?, ?)",
                (fact_key, fact_value, confidence, now),
            )

    async def remember_text(self, text: str, metadata: dict[str, Any] | None = None) -> str:
        metadata = metadata or {}
        doc_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        await self.sqlite_store.execute(
            """
            INSERT OR IGNORE INTO semantic_documents (id, text_value, metadata_json, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (doc_id, text, json.dumps(metadata, ensure_ascii=True), now),
        )
        await self.supermemory.add_memory(
            content=text,
            container_tag="semantic",
            metadata={"doc_id": doc_id, **(metadata or {})},
        )
        return doc_id

    async def retrieve(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        # 1. Semantic search via Supermemory
        results = await self.supermemory.search_memory(
            query=query, filters={"container_tag": "semantic"}
        )
        hits: list[dict[str, Any]] = []
        for res in results:
            if isinstance(res, dict):
                hits.append({
                    "id": res.get("id", ""),
                    "text": res.get("content", str(res)),
                    "metadata": res.get("metadata", {}),
                    "score": res.get("score", 1.0),
                })
            else:
                hits.append({"id": "", "text": str(res), "metadata": {}, "score": 1.0})

        # 2. Merge in SQLite facts
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
            hits.append(
                {
                    "id": f"fact:{row['fact_key']}",
                    "text": f"{row['fact_key']}: {row['fact_value']}",
                    "metadata": {"confidence": row["confidence"], "updated_at": row["updated_at"]},
                    "score": float(row["confidence"]),
                }
            )
        hits.sort(key=lambda item: item.get("score", 0.0), reverse=True)
        return hits[:limit]

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
