"""Core reasoning engine implementation."""

from __future__ import annotations

import logging
from typing import Any

from src.llm.llm_dispatcher import LLMDispatcher
from src.models import MemoryContext, PerceptionOutput, ReasoningOutput, model_dump_compat

logger = logging.getLogger(__name__)


class ReasoningEngine:
    def __init__(self, llm_dispatcher: LLMDispatcher) -> None:
        self.llm = llm_dispatcher

    async def reason(
        self,
        user_text: str,
        perception: PerceptionOutput,
        memory: MemoryContext,
    ) -> ReasoningOutput:
        """Infer intent and determine next actions based on context."""
        
        # Prepare payload for LLM/Classifier
        payload = {
            "user_text": user_text,
            "perception": model_dump_compat(perception),
            "memory": {
                "episodic": memory.episodic_memories[:2],  # Limit context
                "semantic": memory.semantic_memories[:2],
                "persona": memory.persona_profile,
            },
        }

        try:
            # Delegate to LLM Dispatcher (which now handles semantic fast-path)
            raw_result = await self.llm.infer_reasoning(payload)
            
            # Ensure safe extraction of fields
            return ReasoningOutput(
                inferred_intent=raw_result.get("inferred_intent", "general_conversation"),
                confidence=float(raw_result.get("confidence", 0.0)),
                needs_clarification=bool(raw_result.get("needs_clarification", False)),
                clarification_question=raw_result.get("clarification_question"),
                possible_actions=raw_result.get("possible_actions", []),
                tool_candidates=raw_result.get("tool_candidates", []),
                uncertainty=float(raw_result.get("uncertainty", 1.0)),
                rationale=raw_result.get("rationale", ""),
            )
        except Exception as e:
            logger.error("Reasoning failed: %s", e)
            # Fallback safe reasoning
            return ReasoningOutput(
                inferred_intent="general_conversation",
                confidence=0.0,
                needs_clarification=False,
                uncertainty=1.0,
                rationale=f"Error during reasoning: {str(e)}",
            )
