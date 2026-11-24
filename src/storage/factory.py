"""Pick the storage backend from settings: Postgres if TAPAN_DATABASE_URL is set, else local SQLite."""

from __future__ import annotations

from typing import Any

from src.config.settings import Settings
from src.storage.sqlite_store import SQLiteStore


def create_store(settings: Settings) -> Any:
    if settings.database_url:
        from src.storage.pg_store import PostgresStore  # imported lazily: psycopg is only needed in this mode

        return PostgresStore(settings.database_url)
    return SQLiteStore(settings.sqlite_path)
