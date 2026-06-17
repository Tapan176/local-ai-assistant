"""Long-term persona memory and preference evolution."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from src.storage.sqlite_store import SQLiteStore
from src.storage.supermemory_store import SupermemoryStore


class PersonaMemory:
    def __init__(self, sqlite_store: SQLiteStore, supermemory_store: SupermemoryStore) -> None:
        self.sqlite_store = sqlite_store
        self.supermemory = supermemory_store

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
                "updated_at": datetime.now(timezone.utc).isoformat(),
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
                datetime.now(timezone.utc).isoformat(),
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

    async def learn_from_text(self, text: str) -> None:
        # local regex extraction for SQLite (instant recall)
        lowered = text.lower().strip()
        preferences: dict[str, Any] = {}
        goals: dict[str, Any] = {}

        name_match = re.search(r"\b(?:my name is|call me)\s+([a-zA-Z][a-zA-Z\s]{1,30})", lowered)
        if name_match:
            candidate = name_match.group(1).strip().split(" ")[0].title()
            preferences["user_name"] = candidate

        occupation_match = re.search(r"\b(?:i work as|i am a|i'm a)\s+([a-zA-Z][a-zA-Z\s]{2,30})", lowered)
        if occupation_match:
            preferences["occupation"] = occupation_match.group(1).strip().title()

        location_match = re.search(r"\b(?:i live in|i am from|i'm from|based in)\s+([a-zA-Z][a-zA-Z\s]{2,30})", lowered)
        if location_match:
            preferences["location"] = location_match.group(1).strip().title()

        like_match = re.search(r"\bi (?:like|love|prefer|enjoy)\s+([a-zA-Z0-9\s]{2,60})", lowered)
        if like_match:
            likes = preferences.get("likes", [])
            likes.append(like_match.group(1).strip())
            preferences["likes"] = list(dict.fromkeys(likes))[-10:]

        goal_match = re.search(r"\bmy goal is to\s+([a-zA-Z0-9\s]{3,120})", lowered)
        if goal_match:
            goals["primary_goal"] = goal_match.group(1).strip()

        if preferences or goals:
            await self.update_profile(preferences=preferences or None, goals=goals or None)
            
            # Offload ONLY the extracted insight to Supermemory persona tag (prevent node duplication)
            insight_parts = []
            if preferences:
                insight_parts.append(f"User preferences: {preferences}")
            if goals:
                insight_parts.append(f"User goals: {goals}")
            
            if insight_parts:
                await self.supermemory.add_memory(
                    content=" | ".join(insight_parts),
                    container_tag="persona",
                    metadata={"type": "observation"}
                )

    async def search_context(self, query: str) -> list[dict[str, Any]]:
        """Search Supermemory for persona information."""
        return await self.supermemory.search_memory(
            query=query, filters={"container_tag": "persona"}
        )
