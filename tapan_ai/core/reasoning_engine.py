"""Reasoning layer: combine input + memory to infer intent and actions."""

from __future__ import annotations

import logging
from typing import Any

from tapan_ai.llm.llm_dispatcher import LLMDispatcher
from tapan_ai.models import MemoryContext, PerceptionOutput, ReasoningOutput


class ReasoningEngine:
    def __init__(self, llm_dispatcher: LLMDispatcher) -> None:
        self.llm_dispatcher = llm_dispatcher
        self.logger = logging.getLogger(self.__class__.__name__)

    async def reason(
        self,
        user_text: str,
        perception: PerceptionOutput,
        memory: MemoryContext,
    ) -> ReasoningOutput:
        payload: dict[str, Any] = {
            "user_text": user_text,
            "perception": {
                "tone": perception.tone,
                "emotional_state": perception.emotional_state,
                "ambiguity_score": perception.ambiguity_score,
                "entities": perception.entities,
            },
            "memory": {
                "episodic_count": len(memory.episodic_memories),
                "semantic_count": len(memory.semantic_memories),
                "persona": memory.persona_profile,
                "relationships": memory.relationship_graph[:3],
            },
        }
        raw = await self.llm_dispatcher.infer_reasoning(payload)
        self.logger.info(
            "Reasoning output generated",
            extra={"event": "reasoning_complete", "context": {"raw": raw}},
        )
        return ReasoningOutput(
            inferred_intent=str(raw.get("inferred_intent", "general_conversation")),
            confidence=float(raw.get("confidence", 0.5)),
            needs_clarification=bool(raw.get("needs_clarification", False)),
            clarification_question=raw.get("clarification_question"),
            possible_actions=[str(item) for item in raw.get("possible_actions", ["respond_conversationally"])],
            tool_candidates=[str(item) for item in raw.get("tool_candidates", [])],
            uncertainty=float(raw.get("uncertainty", 0.5)),
            rationale=str(raw.get("rationale", "")),
        )

