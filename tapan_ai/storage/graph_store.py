"""Simple graph relationship repository on top of SQLite."""

from __future__ import annotations

from datetime import datetime

from tapan_ai.storage.sqlite_store import SQLiteStore


class GraphStore:
    def __init__(self, sqlite_store: SQLiteStore) -> None:
        self.sqlite_store = sqlite_store

    async def add_relationship(
        self,
        source: str,
        target: str,
        relation: str,
        weight: float = 1.0,
    ) -> None:
        await self.sqlite_store.execute(
            """
            INSERT INTO graph_edges (source, target, relation, weight, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (source, target, relation, weight, datetime.utcnow().isoformat()),
        )

    async def find_related(self, entity: str, limit: int = 10) -> list[dict]:
        return await self.sqlite_store.fetchall(
            """
            SELECT source, target, relation, weight, created_at
            FROM graph_edges
            WHERE source = ? OR target = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (entity, entity, limit),
        )

