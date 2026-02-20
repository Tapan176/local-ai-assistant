"""Planning layer: choose response, clarification, or tool action."""

from __future__ import annotations

from src.models import MemoryContext, PerceptionOutput, PlanDecision, ReasoningOutput


class PlanningEngine:
    async def plan(
        self,
        user_text: str,
        reasoning: ReasoningOutput,
        perception: PerceptionOutput,
        memory: MemoryContext,
    ) -> PlanDecision:
        del memory
        if reasoning.needs_clarification or perception.ambiguity_score >= 0.72:
            question = reasoning.clarification_question or self._default_clarification(user_text, reasoning)
            return PlanDecision(
                action_type="clarify",
                clarification_question=question,
                response_temperature=0.35,
                should_store_memory=True,
            )

        if reasoning.tool_candidates and reasoning.confidence >= 0.56:
            tool_name = reasoning.tool_candidates[0]
            return PlanDecision(
                action_type="tool",
                tool_name=tool_name,
                response_temperature=self._temperature_for_intent(reasoning.inferred_intent, user_text),
                should_store_memory=True,
            )

        return PlanDecision(
            action_type="respond",
            response_temperature=self._temperature_for_intent(reasoning.inferred_intent, user_text),
            should_store_memory=True,
            should_schedule_followup=(perception.emotional_state in {"sad", "stressed"}),
        )

    @staticmethod
    def _temperature_for_intent(intent: str, user_text: str) -> float:
        lowered = user_text.lower()
        if intent in {"financial_update", "calendar_management", "reminder_management"}:
            return 0.2
        if intent in {"emotional_support"}:
            return 0.45
        if any(word in lowered for word in ("imagine", "brainstorm", "creative", "story", "idea")):
            return 0.82
        return 0.55

    @staticmethod
    def _default_clarification(user_text: str, reasoning: ReasoningOutput) -> str:
        if reasoning.tool_candidates:
            return (
                f"I can help with this as {reasoning.inferred_intent}. "
                "Can you share one more detail so I apply the right action?"
            )
        if len(user_text.split()) <= 3:
            return "Can you expand that a bit so I can respond accurately?"
        return "I want to make sure I got you right. What specific outcome do you want?"

