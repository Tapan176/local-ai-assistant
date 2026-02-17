"""Central cognitive orchestration pipeline."""

from __future__ import annotations

import logging
from typing import Any

from tapan_ai.llm.prompt_builder import PromptBuilder
from tapan_ai.models import ConversationTurn, OrchestratorResponse, model_dump_compat
from tapan_ai.tools.tool_registry import ToolRegistry

from .perception_engine import PerceptionEngine
from .planning_engine import PlanningEngine
from .reasoning_engine import ReasoningEngine
from .self_reflection import SelfReflectionEngine
from tapan_ai.llm.llm_dispatcher import LLMDispatcher
from tapan_ai.memory.memory_retriever import MemoryRetriever
from tapan_ai.memory.memory_saver import MemorySaver


class Orchestrator:
    def __init__(
        self,
        perception_engine: PerceptionEngine,
        memory_retriever: MemoryRetriever,
        reasoning_engine: ReasoningEngine,
        planning_engine: PlanningEngine,
        tool_registry: ToolRegistry,
        prompt_builder: PromptBuilder,
        llm_dispatcher: LLMDispatcher,
        self_reflection: SelfReflectionEngine,
        memory_saver: MemorySaver,
    ) -> None:
        self.perception_engine = perception_engine
        self.memory_retriever = memory_retriever
        self.reasoning_engine = reasoning_engine
        self.planning_engine = planning_engine
        self.tool_registry = tool_registry
        self.prompt_builder = prompt_builder
        self.llm_dispatcher = llm_dispatcher
        self.self_reflection = self_reflection
        self.memory_saver = memory_saver
        self.logger = logging.getLogger(self.__class__.__name__)

    async def handle_user_input(self, session_id: str, user_text: str) -> OrchestratorResponse:
        self.logger.info(
            "Pipeline start",
            extra={"event": "pipeline_start", "context": {"session_id": session_id}},
        )

        baseline = "neutral"
        perception = await self.perception_engine.perceive(user_text, emotional_baseline=baseline)
        memory = await self.memory_retriever.retrieve(session_id, user_text, perception.entities)
        reasoning = await self.reasoning_engine.reason(user_text, perception, memory)
        plan = await self.planning_engine.plan(user_text, reasoning, perception, memory)

        tool_result = None
        if plan.action_type == "clarify":
            assistant_text = plan.clarification_question or "Could you clarify what you want me to do?"
        elif plan.action_type == "tool" and plan.tool_name:
            tool_result = await self.tool_registry.execute(
                tool_name=plan.tool_name,
                session_id=session_id,
                user_text=user_text,
                reasoning=reasoning,
                memory=memory,
            )
            assistant_text = await self._render_tool_response(
                user_text=user_text,
                reasoning=reasoning,
                perception_tone=perception.tone,
                tool_result=model_dump_compat(tool_result),
                temperature=plan.response_temperature,
            )
        else:
            assistant_text = await self._render_conversational_response(
                user_text=user_text,
                perception=perception,
                memory=memory,
                reasoning=reasoning,
                temperature=plan.response_temperature,
            )

        reflection = await self.self_reflection.reflect(
            user_text=user_text,
            assistant_text=assistant_text,
            plan=plan,
            memory=memory,
        )

        turn = ConversationTurn(
            session_id=session_id,
            user_text=user_text,
            assistant_text=assistant_text,
            emotional_state=perception.emotional_state,
            tool_used=tool_result.tool_name if tool_result else None,
            metadata={
                "plan": model_dump_compat(plan),
                "reasoning": model_dump_compat(reasoning),
                "reflection": model_dump_compat(reflection),
            },
        )
        if plan.should_store_memory:
            await self.memory_saver.save_turn(
                turn=turn,
                reflection=reflection,
                perception_tone=perception.tone,
                tool_data=(model_dump_compat(tool_result).get("data", {}) if tool_result else None),
            )

        references = [str(item.get("id", "")) for item in memory.semantic_memories[:3]]
        response = OrchestratorResponse(
            session_id=session_id,
            text=assistant_text,
            action_type=plan.action_type,
            tool_used=(tool_result.tool_name if tool_result else None),
            emotional_state=perception.emotional_state,
            reflection_score=reflection.coherence_score,
            memory_references=[ref for ref in references if ref],
            debug={
                "perception": model_dump_compat(perception),
                "reasoning": model_dump_compat(reasoning),
                "plan": model_dump_compat(plan),
                "reflection": model_dump_compat(reflection),
            },
        )
        self.logger.info(
            "Pipeline complete",
            extra={
                "event": "pipeline_complete",
                "context": {
                    "session_id": session_id,
                    "action_type": plan.action_type,
                    "tool": response.tool_used,
                },
            },
        )
        return response

    async def _render_tool_response(
        self,
        user_text: str,
        reasoning: Any,
        perception_tone: str,
        tool_result: dict[str, Any],
        temperature: float,
    ) -> str:
        if not tool_result.get("success", False):
            return str(tool_result.get("output_text", "I couldn't complete that tool action."))

        followup_prompt = (
            "Tool output is available. Compose one short natural follow-up line "
            "that aligns with user tone and intent. Keep it under 15 words."
        )
        generated = await self.llm_dispatcher.generate_text(
            system="You are a concise conversational assistant.",
            context=(
                f"Tone: {perception_tone}\n"
                f"Intent: {reasoning.inferred_intent}\n"
                f"Tool output: {tool_result.get('output_text', '')}"
            ),
            user=f"{followup_prompt}\nUser text: {user_text}",
            temperature=max(0.35, temperature),
        )
        base = str(tool_result.get("output_text", "")).strip()
        followup = generated.strip()
        if not followup:
            return base
        if followup.endswith("."):
            return f"{base} {followup}"
        return f"{base} {followup}."

    async def _render_conversational_response(
        self,
        user_text: str,
        perception: Any,
        memory: Any,
        reasoning: Any,
        temperature: float,
    ) -> str:
        prompt = self.prompt_builder.build(
            user_text=user_text,
            perception=perception,
            memory=memory,
            reasoning=reasoning,
            tool_result=None,
        )
        return await self.llm_dispatcher.generate_text(
            system=prompt["system"],
            context=prompt["context"],
            user=prompt["user"],
            temperature=temperature,
        )

