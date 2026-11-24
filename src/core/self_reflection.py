"""Self-reflection loop for coherence and memory policy updates."""

from __future__ import annotations

import re

from src.models import MemoryContext, PlanDecision, ReflectionReport


class SelfReflectionEngine:
    async def reflect(
        self,
        user_text: str,
        assistant_text: str,
        plan: PlanDecision,
        memory: MemoryContext,
    ) -> ReflectionReport:
        user_tokens = set(re.findall(r"[a-zA-Z0-9_]+", user_text.lower()))
        reply_tokens = set(re.findall(r"[a-zA-Z0-9_]+", assistant_text.lower()))
        overlap = len(user_tokens & reply_tokens)
        denominator = max(1, len(user_tokens))
        lexical_alignment = overlap / denominator

        length_penalty = 0.0 if len(assistant_text) >= 12 else 0.25
        plan_penalty = 0.0 if plan.action_type in {"respond", "clarify", "tool"} else 0.35
        coherence = max(0.0, min(1.0, 0.45 + lexical_alignment - length_penalty - plan_penalty))

        missed_context = bool(memory.semantic_memories and lexical_alignment < 0.12)
        contradiction_risk = 0.4 if ("not" in assistant_text.lower() and "yes" in assistant_text.lower()) else 0.08

        should_store_semantic = any(
            phrase in user_text.lower()
            for phrase in ("my name is", "i like", "my goal is", "my brother", "my sister", "account")
        )
        persona_updates: dict[str, str] = {}
        if plan.action_type == "clarify" and coherence < 0.45:
            persona_updates["clarification_style"] = "more_direct"
        if len(user_text.split()) <= 3:
            persona_updates["response_length"] = "concise"

        emotional_shift = None
        if "thank" in user_text.lower() and "stressed" in memory.persona_profile.get("emotional_baseline", ""):
            emotional_shift = "improving"

        return ReflectionReport(
            coherence_score=coherence,
            missed_context=missed_context,
            contradiction_risk=contradiction_risk,
            should_store_semantic=should_store_semantic,
            persona_updates=persona_updates,
            emotional_shift=emotional_shift,
        )

