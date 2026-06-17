"""Contextual proactive suggestions based on memory and structured state."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from src.storage.sqlite_store import SQLiteStore


class ProactiveEngine:
    def __init__(self, sqlite_store: SQLiteStore) -> None:
        self.sqlite_store = sqlite_store

    async def suggest(self, session_id: str, emotional_state: str) -> list[dict[str, Any]]:
        suggestions: list[dict[str, Any]] = []
        suggestions.extend(await self._finance_suggestions())
        suggestions.extend(await self._reminder_suggestions(session_id))
        suggestions.extend(self._emotional_suggestions(emotional_state))

        priority_score = {"high": 0, "medium": 1, "low": 2}
        suggestions.sort(key=lambda item: priority_score.get(item.get("priority", "low"), 3))
        return suggestions[:3]

    async def _finance_suggestions(self) -> list[dict[str, Any]]:
        rows = await self.sqlite_store.fetchall(
            "SELECT account_name, balance FROM financial_accounts ORDER BY balance ASC LIMIT 1"
        )
        if not rows:
            return []
        account = rows[0]
        balance = float(account.get("balance", 0.0))
        if 0 < balance < 1000:
            return [
                {
                    "type": "finance",
                    "priority": "high",
                    "message": f"{account['account_name']} is low on balance (Rs {balance:.2f}).",
                    "action": "review_balance",
                }
            ]
        return []

    async def _reminder_suggestions(self, session_id: str) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc).isoformat()
        rows = await self.sqlite_store.fetchall(
            """
            SELECT id, title, due_at
            FROM reminders
            WHERE session_id = ?
              AND status = 'pending'
              AND due_at IS NOT NULL
              AND due_at <= ?
            ORDER BY due_at ASC
            LIMIT 3
            """,
            (session_id, now),
        )
        if not rows:
            return []
        titles = ", ".join(item["title"] for item in rows[:2])
        return [
            {
                "type": "reminder",
                "priority": "high",
                "message": f"You have overdue reminders: {titles}.",
                "action": "list_overdue",
            }
        ]

    @staticmethod
    def _emotional_suggestions(emotional_state: str) -> list[dict[str, Any]]:
        if emotional_state in {"stressed", "sad"}:
            return [
                {
                    "type": "wellbeing",
                    "priority": "medium",
                    "message": "You seem like you could use a breather. Want me to help you reset with a quick 2-minute plan?",
                    "action": "micro_reset",
                }
            ]
        hour = datetime.now(timezone.utc).hour
        if 17 <= hour <= 22:
            return [
                {
                    "type": "planning",
                    "priority": "low",
                    "message": "It's evening — want a quick review of what's done and what's ahead tomorrow?",
                    "action": "day_review",
                }
            ]
        if 5 <= hour <= 9:
            return [
                {
                    "type": "planning",
                    "priority": "low",
                    "message": "Good morning! Want me to run through your reminders and schedule for today?",
                    "action": "morning_brief",
                }
            ]
        return []

