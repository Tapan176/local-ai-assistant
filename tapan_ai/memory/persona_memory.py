"""Long-term persona memory and preference evolution."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from tapan_ai.storage.sqlite_store import SQLiteStore


class PersonaMemory:
    def __init__(self, sqlite_store: SQLiteStore) -> None:
        self.sqlite_store = sqlite_store

    async def get_profile(self) -> dict[str, Any]:
        row = await self.sqlite_store.fetchone(
            """
            SELECT communication_style, emotional_baseline, preferences_json, goals_json, updated_at
            FROM persona_profile
            WHERE id = 1
            """
        )
        if not row:
            return {
                "communication_style": "balanced",
                "emotional_baseline": "neutral",
                "preferences": {},
                "goals": {},
                "updated_at": datetime.utcnow().isoformat(),
            }
        return {
            "communication_style": row["communication_style"],
            "emotional_baseline": row["emotional_baseline"],
            "preferences": self.sqlite_store.parse_json_field(row["preferences_json"]),
            "goals": self.sqlite_store.parse_json_field(row["goals_json"]),
            "updated_at": row["updated_at"],
        }

    async def update_profile(
        self,
        communication_style: str | None = None,
        emotional_baseline: str | None = None,
        preferences: dict[str, Any] | None = None,
        goals: dict[str, Any] | None = None,
    ) -> None:
        current = await self.get_profile()
        merged_preferences = dict(current.get("preferences", {}))
        merged_preferences.update(preferences or {})
        merged_goals = dict(current.get("goals", {}))
        merged_goals.update(goals or {})

        await self.sqlite_store.execute(
            """
            UPDATE persona_profile
            SET communication_style = ?,
                emotional_baseline = ?,
                preferences_json = ?,
                goals_json = ?,
                updated_at = ?
            WHERE id = 1
            """,
            (
                communication_style or current.get("communication_style", "balanced"),
                emotional_baseline or current.get("emotional_baseline", "neutral"),
                json.dumps(merged_preferences, ensure_ascii=True),
                json.dumps(merged_goals, ensure_ascii=True),
                datetime.utcnow().isoformat(),
            ),
        )

    async def evolve_from_reflection(
        self,
        emotional_state: str,
        reflection_score: float,
        detected_tone: str,
    ) -> None:
        profile = await self.get_profile()
        preferences = dict(profile.get("preferences", {}))
        style_count = preferences.get("style_counts", {})
        style_count[detected_tone] = int(style_count.get(detected_tone, 0)) + 1
        preferences["style_counts"] = style_count
        if reflection_score < 0.35:
            preferences["last_warning"] = "low_coherence"
        await self.update_profile(
            emotional_baseline=emotional_state,
            preferences=preferences,
        )

