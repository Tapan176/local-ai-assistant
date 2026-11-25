"""Download everything the assistant keeps about the user as one JSON file (a backup you can read, and the way out of the app).

Allow-list on purpose: tables and settings are exported only if they are listed here, so a table added later (or a secret kept in
``app_settings``) can never leak into a file that ends up in a Downloads folder. Never exported: the Telegram bot token, the push
signing key, push subscriptions, the access token, and the daily picture counter.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.agent import spending, weather

TABLES = (
    "memories", "people", "calendar_events", "reminders", "tasks", "notes",
    "ex_banks", "ex_payments", "ex_emis", "ex_spend", "ex_subs",
    "kg_nodes", "kg_edges", "financial_accounts", "financial_transactions", "persona_profile", "episodes",
)
SETTING_KEYS = (spending.BUDGET_KEY, weather.HOME_KEY)
FORMAT = 1


async def build(store: Any, settings: Any) -> dict[str, Any]:
    tables: dict[str, list[dict[str, Any]]] = {}
    for name in TABLES:
        tables[name] = await store.fetchall(f"SELECT * FROM {name} ORDER BY 1")
    marks = ",".join("?" * len(SETTING_KEYS))
    tables["settings"] = await store.fetchall(f"SELECT id, value FROM app_settings WHERE id IN ({marks}) ORDER BY id", SETTING_KEYS)
    return {
        "app": "TAPAN_AI",
        "format": FORMAT,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "currency": getattr(settings, "currency", ""),
        "note": "Money amounts are stored in minor units (paise/cents): 150000 means 1,500.00. Chat history is under 'episodes'.",
        "counts": {k: len(v) for k, v in tables.items()},
        "tables": tables,
    }
