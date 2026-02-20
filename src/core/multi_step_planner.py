"""Multi-step planning engine for complex task decomposition (like Cursor/Copilot)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from src.core.function_calling_engine import FunctionCallingEngine, ToolCall
from src.llm.llm_dispatcher import LLMDispatcher
from src.models import MemoryContext, PerceptionOutput, ReasoningOutput
from src.tools.tool_schema import ToolSchema

logger = logging.getLogger(__name__)


@dataclass
class TaskStep:
    """Represents a single step in a multi-step plan."""
    step_number: int
    description: str
    tool_calls: list[ToolCall]
    dependencies: list[int] = field(default_factory=list)  # Step numbers this depends on
    expected_result: str = ""


@dataclass
class ExecutionPlan:
    """Complete execution plan for a multi-step task."""
    steps: list[TaskStep]
    goal: str
    estimated_steps: int


class MultiStepPlanner:
    """Plans multi-step operations by decomposing complex tasks."""

    def __init__(
        self,
        llm_dispatcher: LLMDispatcher,
        function_calling_engine: FunctionCallingEngine,
    ) -> None:
        self.llm = llm_dispatcher
        self.function_calling = function_calling_engine

    async def plan(
        self,
        user_text: str,
        reasoning: ReasoningOutput,
        perception: PerceptionOutput,
        memory: MemoryContext,
        available_tools: list[ToolSchema],
    ) -> ExecutionPlan | None:
        """Decompose user request into multi-step plan."""
        
        # Check if task is complex enough for multi-step planning
        if not self._needs_multi_step(user_text, reasoning):
            return None
        
        try:
            # Use LLM to decompose task
            decomposition = await self._decompose_task(user_text, available_tools)
            
            if not decomposition or len(decomposition) <= 1:
                return None
            
            # Build execution plan
            steps = []
            for idx, step_desc in enumerate(decomposition, 1):
                # Extract tool calls for this step
                tool_calls = await self.function_calling.select_and_extract(
                    step_desc,
                    available_tools,
                    context={"step_number": idx, "total_steps": len(decomposition)},
                )
                
                if tool_calls:
                    steps.append(
                        TaskStep(
                            step_number=idx,
                            description=step_desc,
                            tool_calls=tool_calls,
                            dependencies=[],
                        )
                    )
            
            if steps:
                return ExecutionPlan(
                    steps=steps,
                    goal=user_text,
                    estimated_steps=len(steps),
                )
        except Exception as e:
            logger.warning("Multi-step planning failed: %s", e)
        
        return None

    async def adapt_plan(
        self,
        *,
        original_goal: str,
        failed_step_description: str,
        failure_reason: str,
        completed_steps: list[str],
        remaining_step_descriptions: list[str],
        available_tools: list[ToolSchema],
    ) -> ExecutionPlan | None:
        """Adapt remaining plan after intermediate execution failure."""
        if not remaining_step_descriptions:
            return None

        if self._failure_needs_user_input(failure_reason):
            # No autonomous adaptation if we need missing required details.
            return None

        try:
            adapted_descriptions = await self._adapt_remaining_steps_with_llm(
                original_goal=original_goal,
                failed_step_description=failed_step_description,
                failure_reason=failure_reason,
                completed_steps=completed_steps,
                remaining_steps=remaining_step_descriptions,
                available_tools=available_tools,
            )
        except Exception as e:
            logger.warning("Adaptive replanning failed: %s", e)
            adapted_descriptions = []

        # Fallback: skip failed step and continue with untouched remainder.
        if not adapted_descriptions:
            adapted_descriptions = remaining_step_descriptions

        return await self._build_plan_from_descriptions(
            step_descriptions=adapted_descriptions,
            goal=original_goal,
            available_tools=available_tools,
        )

    def _needs_multi_step(self, user_text: str, reasoning: ReasoningOutput) -> bool:
        """Determine if task requires multi-step planning."""
        lowered = user_text.lower()
        
        # Indicators of multi-step tasks
        multi_step_indicators = [
            "and then",
            "and also",
            "after that",
            "first",
            "then",
            "next",
            "finally",
            "set up",
            "configure",
            "initialize",
        ]
        
        # Check for multiple intents or actions
        has_multiple_actions = (
            user_text.count(" and ") >= 1
            or any(indicator in lowered for indicator in multi_step_indicators)
            or reasoning.confidence < 0.6  # Low confidence might indicate complexity
        )
        
        return has_multiple_actions

    async def _decompose_task(
        self,
        user_text: str,
        available_tools: list[ToolSchema],
    ) -> list[str]:
        """Decompose task into steps using LLM."""
        tool_names = [tool.name for tool in available_tools]
        
        prompt = (
            f"User request: {user_text}\n\n"
            f"Available tools: {', '.join(tool_names)}\n\n"
            "Break down this request into sequential steps. Each step should be a single action.\n"
            "Return JSON array of step descriptions:\n"
            '["step 1 description", "step 2 description", ...]'
        )
        
        try:
            response = await self.llm.generate_text(
                system="You are a task decomposition assistant. Break complex tasks into clear sequential steps.",
                context=prompt,
                user="",
                temperature=0.2,
                json_mode=True,
            )
            
            parsed = json.loads(response)
            if isinstance(parsed, list):
                return [str(step) for step in parsed]
        except Exception as e:
            logger.warning("Task decomposition failed: %s", e)
        
        # Fallback: simple split on "and"
        if " and " in user_text.lower():
            parts = user_text.split(" and ")
            return [part.strip() for part in parts if part.strip()]
        
        return [user_text]

    async def _adapt_remaining_steps_with_llm(
        self,
        *,
        original_goal: str,
        failed_step_description: str,
        failure_reason: str,
        completed_steps: list[str],
        remaining_steps: list[str],
        available_tools: list[ToolSchema],
    ) -> list[str]:
        tool_names = [tool.name for tool in available_tools]
        prompt = (
            f"Original goal: {original_goal}\n"
            f"Failed step: {failed_step_description}\n"
            f"Failure reason: {failure_reason}\n"
            f"Completed steps summary: {json.dumps(completed_steps)}\n"
            f"Remaining steps before adaptation: {json.dumps(remaining_steps)}\n"
            f"Available tools: {', '.join(tool_names)}\n\n"
            "Adapt the remaining plan to maximize progress despite the failed step.\n"
            "Rules:\n"
            "1) Keep only executable steps.\n"
            "2) Avoid repeating completed work.\n"
            "3) Return JSON array of step descriptions only.\n"
        )
        response = await self.llm.generate_text(
            system="You adapt multi-step task plans after execution failures.",
            context=prompt,
            user="",
            temperature=0.15,
            json_mode=True,
        )
        parsed = json.loads(response)
        if not isinstance(parsed, list):
            return []
        return [str(item).strip() for item in parsed if str(item).strip()]

    async def _build_plan_from_descriptions(
        self,
        *,
        step_descriptions: list[str],
        goal: str,
        available_tools: list[ToolSchema],
    ) -> ExecutionPlan | None:
        steps: list[TaskStep] = []
        for idx, step_desc in enumerate(step_descriptions, 1):
            tool_calls = await self.function_calling.select_and_extract(
                step_desc,
                available_tools,
                context={"step_number": idx, "total_steps": len(step_descriptions), "mode": "adaptive_replan"},
            )
            if not tool_calls:
                continue
            steps.append(
                TaskStep(
                    step_number=idx,
                    description=step_desc,
                    tool_calls=tool_calls,
                    dependencies=[],
                )
            )

        if not steps:
            return None
        return ExecutionPlan(steps=steps, goal=goal, estimated_steps=len(steps))

    @staticmethod
    def _failure_needs_user_input(failure_reason: str) -> bool:
        lowered = failure_reason.lower()
        blockers = [
            "need the exact amount",
            "need an amount",
            "provide a specific date/time",
            "please share the item id",
            "please share both source and destination account names",
            "tell me the reminder text and when",
            "can you share one more detail",
        ]
        return any(token in lowered for token in blockers)
