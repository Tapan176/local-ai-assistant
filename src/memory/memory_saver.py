"""Automatic persistence for episodes, semantic facts, and persona updates."""

from __future__ import annotations

import re
from typing import Any

from src.models import ConversationTurn, ReflectionReport
from src.storage.supermemory_store import SupermemoryStore

from .episodic_memory import EpisodicMemory
from .persona_memory import PersonaMemory
from .semantic_memory import SemanticMemory


class MemorySaver:
    def __init__(
        self,
        episodic_memory: EpisodicMemory,
        semantic_memory: SemanticMemory,
        persona_memory: PersonaMemory,
        supermemory_store: SupermemoryStore,
    ) -> None:
        self.episodic_memory = episodic_memory
        self.semantic_memory = semantic_memory
        self.persona_memory = persona_memory
        self.supermemory = supermemory_store

    async def save_turn(
        self,
        turn: ConversationTurn,
        reflection: ReflectionReport,
        perception_tone: str,
        tool_data: dict[str, Any] | None = None,
    ) -> None:
        await self.episodic_memory.add_turn(turn)
        await self.semantic_memory.remember_text(
            text=f"User: {turn.user_text}\nAssistant: {turn.assistant_text}",
            metadata={"session_id": turn.session_id, "tool": turn.tool_used or ""},
        )

        if reflection.should_store_semantic:
            for key, value in self._extract_semantic_facts(turn.user_text).items():
                await self.semantic_memory.upsert_fact(key, value, confidence=0.8)
            await self.semantic_memory.consolidate()

        if tool_data:
            await self._update_graph_from_tool(tool_data)

        await self.persona_memory.learn_from_text(turn.user_text)
        await self.persona_memory.evolve_from_reflection(
            emotional_state=turn.emotional_state,
            reflection_score=reflection.coherence_score,
            detected_tone=perception_tone,
        )

    def _extract_semantic_facts(self, text: str) -> dict[str, str]:
        lowered = text.lower()
        facts: dict[str, str] = {}

        name_match = re.search(r"\bmy name is\s+([a-zA-Z][a-zA-Z\s]{1,40})", lowered)
        if name_match:
            facts["user_name"] = name_match.group(1).strip().title()

        likes_match = re.search(r"\bi like\s+([a-zA-Z0-9\s]{2,60})", lowered)
        if likes_match:
            facts["user_preference"] = likes_match.group(1).strip()

        goal_match = re.search(r"\bmy goal is to\s+([a-zA-Z0-9\s]{3,100})", lowered)
        if goal_match:
            facts["user_goal"] = goal_match.group(1).strip()

        return facts

    async def _update_graph_from_tool(self, tool_data: dict[str, Any]) -> None:
        source = tool_data.get("source")
        target = tool_data.get("target")
        relation = tool_data.get("relation")
        if source and target and relation:
            await self.supermemory.add_memory(
                content=f"{source} is {relation} of {target}",
                container_tag="relationships",
                metadata={"source": str(source), "target": str(target), "relation": str(relation)},
            )
