"""SQLite repository foundation for TAPAN_AI v2."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    user_text TEXT NOT NULL,
    assistant_text TEXT NOT NULL,
    emotional_state TEXT NOT NULL,
    tool_used TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS semantic_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fact_key TEXT NOT NULL,
    fact_value TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.5,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS persona_profile (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    communication_style TEXT NOT NULL DEFAULT 'balanced',
    emotional_baseline TEXT NOT NULL DEFAULT 'neutral',
    preferences_json TEXT NOT NULL DEFAULT '{}',
    goals_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS financial_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_name TEXT UNIQUE NOT NULL,
    balance REAL NOT NULL DEFAULT 0.0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS financial_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_name TEXT NOT NULL,
    amount REAL NOT NULL,
    kind TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    title TEXT NOT NULL,
    due_at TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    relationship TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS calendar_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    start_at TEXT,
    end_at TEXT,
    location TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS graph_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    target TEXT NOT NULL,
    relation TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS semantic_documents (
    id TEXT PRIMARY KEY,
    text_value TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);
"""


class SQLiteStore:
    """Async-friendly SQLite repository helper."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize_sync)

    def _initialize_sync(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)
            conn.execute(
                """
                INSERT OR IGNORE INTO persona_profile
                (id, communication_style, emotional_baseline, preferences_json, goals_json, updated_at)
                VALUES (1, 'balanced', 'neutral', '{}', '{}', datetime('now'))
                """
            )
            conn.commit()

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        return await asyncio.to_thread(self._execute_sync, sql, params)

    def _execute_sync(self, sql: str, params: tuple[Any, ...]) -> int:
        with self._connect() as conn:
            cur = conn.execute(sql, params)
            conn.commit()
            return cur.lastrowid

    async def fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._fetchone_sync, sql, params)

    def _fetchone_sync(self, sql: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(sql, params).fetchone()
            return dict(row) if row else None

    async def fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._fetchall_sync, sql, params)

    def _fetchall_sync(self, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [dict(row) for row in rows]

    @staticmethod
    def parse_json_field(value: str | None) -> dict[str, Any]:
        if not value:
            return {}
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}

