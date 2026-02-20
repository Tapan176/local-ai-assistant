"""Central cognitive orchestration pipeline."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from src.core.error_recovery_engine import ErrorRecoveryEngine, RecoveryAttempt
from src.core.function_calling_engine import FunctionCallingEngine
from src.core.multi_step_planner import MultiStepPlanner
from src.core.result_verifier import ResultVerifier
from src.llm.prompt_builder import PromptBuilder
from src.models import (
    ConversationTurn,
    MemoryContext,
    Operation,
    OrchestratorResponse,
    PlanDecision,
    ReasoningOutput,
    ToolExecutionResult,
    model_dump_compat,
)
from src.tools.tool_registry import ToolRegistry

from .output_sanitizer import OutputSanitizer
from .performance_monitor import PerformanceMonitor
from .perception_engine import PerceptionEngine
from .planning_engine import PlanningEngine
from .proactive_engine import ProactiveEngine
from .reference_resolver import ReferenceResolver
from .reasoning_engine import ReasoningEngine
from .self_reflection import SelfReflectionEngine
from src.llm.llm_dispatcher import LLMDispatcher
from src.memory.memory_retriever import MemoryRetriever
from src.memory.memory_saver import MemorySaver


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
        output_sanitizer: OutputSanitizer | None = None,
        reference_resolver: ReferenceResolver | None = None,
        proactive_engine: ProactiveEngine | None = None,
        performance_monitor: PerformanceMonitor | None = None,
        result_verifier: ResultVerifier | None = None,
        error_recovery_engine: ErrorRecoveryEngine | None = None,
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
        self.output_sanitizer = output_sanitizer or OutputSanitizer()
        self.reference_resolver = reference_resolver or ReferenceResolver()
        self.proactive_engine = proactive_engine
        self.performance_monitor = performance_monitor or PerformanceMonitor()
        self.result_verifier = result_verifier
        self._suggestion_history: dict[str, dict[str, str]] = {}
        self.logger = logging.getLogger(self.__class__.__name__)

        # Initialize function calling and multi-step planning
        self.function_calling = FunctionCallingEngine(llm_dispatcher)
        self.multi_step_planner = MultiStepPlanner(llm_dispatcher, self.function_calling)
        self.error_recovery_engine = error_recovery_engine or ErrorRecoveryEngine(self.function_calling)

    async def handle_user_input(self, session_id: str, user_text: str) -> OrchestratorResponse:
        start = self.performance_monitor.wrap_start()
        self.logger.info(
            "Pipeline start",
            extra={"event": "pipeline_start", "context": {"session_id": session_id}},
        )

        initial_memory = await self.memory_retriever.retrieve(session_id, user_text, [])
        resolved_user_text = self.reference_resolver.resolve(user_text, initial_memory.episodic_memories)

        baseline = str(initial_memory.persona_profile.get("emotional_baseline", "neutral"))
        perception = await self.perception_engine.perceive(resolved_user_text, emotional_baseline=baseline)
        memory = await self.memory_retriever.retrieve(session_id, resolved_user_text, perception.entities)
        reasoning = await self.reasoning_engine.reason(resolved_user_text, perception, memory)
        
        # Check for multi-step planning first
        available_schemas = self.tool_registry.get_all_schemas()
        multi_step_plan = await self.multi_step_planner.plan(
            resolved_user_text,
            reasoning,
            perception,
            memory,
            available_schemas,
        )

        plan = PlanDecision(
            action_type="respond",
            response_temperature=0.55,
            should_store_memory=True,
            should_schedule_followup=(perception.emotional_state in {"sad", "stressed"}),
        )
        tool_result = None
        assistant_text = ""
        verification_reports: list[dict[str, Any]] = []
        recovery_reports: list[dict[str, Any]] = []
        adaptation_reports: list[dict[str, Any]] = []

        if multi_step_plan:
            # Execute multi-step plan
            plan = PlanDecision(
                action_type="tool",
                tool_name="multi_step_plan",
                response_temperature=0.2,
                should_store_memory=True,
                should_schedule_followup=(perception.emotional_state in {"sad", "stressed"}),
            )
            (
                assistant_text,
                tool_result,
                verification_reports,
                recovery_reports,
                adaptation_reports,
            ) = await self._execute_multi_step_plan(
                multi_step_plan,
                session_id,
                reasoning,
                memory,
                resolved_user_text,
            )
        else:
            # Single-step execution (existing flow)
            plan = await self.planning_engine.plan(resolved_user_text, reasoning, perception, memory)

            if plan.action_type == "clarify":
                assistant_text = plan.clarification_question or "Could you clarify what you want me to do?"
            elif plan.action_type == "tool" and plan.tool_name:
                tool_result = await self.tool_registry.execute(
                    tool_name=plan.tool_name,
                    session_id=session_id,
                    user_text=resolved_user_text,
                    reasoning=reasoning,
                    memory=memory,
                )
                verification_report = await self._verify_tool_result(
                    tool_result=tool_result,
                    operation_description=resolved_user_text,
                    user_intent=resolved_user_text,
                )
                if verification_report is not None:
                    verification_reports.append(model_dump_compat(verification_report))

                recovery_clarification: str | None = None
                if self._needs_recovery(tool_result, verification_report):
                    recovery_result = await self.error_recovery_engine.recover(
                        session_id=session_id,
                        user_intent=resolved_user_text,
                        attempted_user_text=resolved_user_text,
                        failed_result=tool_result,
                        reasoning=reasoning,
                        memory=memory,
                        available_schemas=available_schemas,
                        tool_registry=self.tool_registry,
                        verify_fn=self._verify_tool_result,
                    )
                    recovery_reports.extend(self._serialize_recovery_attempts(recovery_result.attempts))
                    for attempt in recovery_result.attempts:
                        if attempt.verification:
                            verification_reports.append(attempt.verification)
                    tool_result = recovery_result.final_result
                    if not recovery_result.recovered:
                        recovery_clarification = recovery_result.clarification_question

                if recovery_clarification:
                    assistant_text = recovery_clarification
                else:
                    assistant_text = await self._render_tool_response(
                        user_text=resolved_user_text,
                        reasoning=reasoning,
                        perception_tone=perception.tone,
                        tool_result=model_dump_compat(tool_result),
                        temperature=plan.response_temperature,
                    )
                    final_verification = await self._verify_tool_result(
                        tool_result=tool_result,
                        operation_description=resolved_user_text,
                        user_intent=resolved_user_text,
                    )
                    if final_verification is not None:
                        verification_reports.append(model_dump_compat(final_verification))
                        if tool_result.success and not final_verification.success:
                            guidance = (
                                final_verification.suggestions[0]
                                if final_verification.suggestions
                                else "The result may not fully match your intent."
                            )
                            assistant_text = f"{assistant_text}\n\nVerification warning: {guidance}"
            else:
                assistant_text = await self._render_conversational_response(
                    user_text=resolved_user_text,
                    perception=perception,
                    memory=memory,
                    reasoning=reasoning,
                    temperature=plan.response_temperature,
                )
        assistant_text = self.output_sanitizer.sanitize(assistant_text)

        if self.proactive_engine and plan.action_type != "clarify":
            suggestions = await self.proactive_engine.suggest(session_id, perception.emotional_state)
            if suggestions and (plan.should_schedule_followup or plan.action_type == "tool"):
                pick = self._pick_suggestion(suggestions, reasoning.inferred_intent, perception.emotional_state)
                if pick and self._should_emit_suggestion(session_id, pick):
                    # Don't append if it would duplicate what we just said (e.g. balance already in message)
                    msg = pick["message"]
                    if msg and msg not in assistant_text and not any(
                        word in assistant_text.lower() for word in msg.lower().split()[:3]
                    ):
                        assistant_text = f"{assistant_text} {msg}"

        reflection = await self.self_reflection.reflect(
            user_text=resolved_user_text,
            assistant_text=assistant_text,
            plan=plan,
            memory=memory,
        )

        turn = ConversationTurn(
            session_id=session_id,
            user_text=resolved_user_text,
            assistant_text=assistant_text,
            emotional_state=perception.emotional_state,
            tool_used=tool_result.tool_name if tool_result else None,
            metadata={
                "raw_user_text": user_text,
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
                "raw_user_text": user_text,
                "resolved_user_text": resolved_user_text,
            },
        )
        if verification_reports:
            response.debug["verification"] = verification_reports
        if recovery_reports:
            response.debug["recovery"] = recovery_reports
        if adaptation_reports:
            response.debug["plan_adaptation"] = adaptation_reports
        self.performance_monitor.wrap_end("orchestrator_handle_user_input", start)
        perf_stats = self.performance_monitor.stats("orchestrator_handle_user_input")
        if perf_stats:
            response.debug["performance"] = perf_stats
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

        base = str(tool_result.get("output_text", "")).strip()
        # Single clean response: use only tool output when it's already complete (lists, multi-line, or long)
        if "\n" in base or len(base) > 120:
            return base
        # Optional one short followup only for mock/short responses
        if self.llm_dispatcher.settings.llm_provider.lower() == "mock":
            generated = self._default_tool_followup(reasoning.inferred_intent, perception_tone, tool_result)
        else:
            generated = await self.llm_dispatcher.generate_text(
                system="You are a concise conversational assistant. Reply in one short sentence only.",
                context=(
                    f"Tone: {perception_tone}\n"
                    f"Intent: {reasoning.inferred_intent}\n"
                    f"Tool output: {base}"
                ),
                user=user_text,
                temperature=max(0.35, temperature),
            )
        followup = (generated or "").strip()
        if not followup or followup.lower() in base.lower():
            return base
        if followup.endswith((".", "?", "!")):
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

    @staticmethod
    def _default_tool_followup(intent: str, tone: str, tool_result: dict[str, Any]) -> str:
        if intent == "financial_update":
            data = tool_result.get("data", {})
            output_text = str(tool_result.get("output_text", "")).lower()
            accounts_present = isinstance(data, dict) and "accounts" in data
            accounts = data.get("accounts", []) if isinstance(data, dict) else []
            if accounts_present and isinstance(accounts, list) and not accounts:
                return "Want me to create your first account now? Say the account name and optional opening balance."
            if "no transaction history" in output_text:
                return "Want me to add your first transaction entry?"
            if "created account" in output_text:
                return "Want me to show all account balances now?"
            return "Want me to show your latest transaction history?"
        if intent == "reminder_management":
            return "Should I add another related reminder?"
        if intent == "calendar_management":
            return "Do you want a prep reminder for this event?"
        if intent == "people_memory_update":
            return "Want me to store a quick note about this person too?"
        if tone in {"informal", "casual"}:
            return "Anything else you want me to handle right now?"
        return "Let me know if you want another action."

    @staticmethod
    def _pick_suggestion(
        suggestions: list[dict[str, Any]],
        intent: str,
        emotional_state: str,
    ) -> dict[str, Any] | None:
        if emotional_state in {"sad", "stressed"}:
            for item in suggestions:
                if item.get("type") == "wellbeing":
                    return item
        if intent == "financial_update":
            for item in suggestions:
                if item.get("type") == "finance":
                    return item
        if intent == "reminder_management":
            for item in suggestions:
                if item.get("type") == "reminder":
                    return item
        if intent == "calendar_management":
            for item in suggestions:
                if item.get("type") in {"planning", "reminder"}:
                    return item
        return None

    def _should_emit_suggestion(self, session_id: str, suggestion: dict[str, Any]) -> bool:
        suggestion_type = str(suggestion.get("type", "unknown"))
        now = datetime.now(timezone.utc)
        state = self._suggestion_history.get(session_id)
        if state and state.get("type") == suggestion_type:
            try:
                then = datetime.fromisoformat(state.get("timestamp", ""))
                if (now - then).total_seconds() < 180:
                    return False
            except Exception:
                pass
        self._suggestion_history[session_id] = {"type": suggestion_type, "timestamp": now.isoformat()}
        return True

    async def _execute_multi_step_plan(
        self,
        plan: Any,  # ExecutionPlan
        session_id: str,
        reasoning: ReasoningOutput,
        memory: MemoryContext,
        user_intent: str,
    ) -> tuple[
        str,
        ToolExecutionResult | None,
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
    ]:
        """Execute a multi-step plan (like Cursor/Copilot)."""
        from src.core.multi_step_planner import ExecutionPlan, TaskStep

        if not isinstance(plan, ExecutionPlan):
            return "", None, [], [], []

        results: list[str] = []
        last_tool_result: ToolExecutionResult | None = None
        verification_reports: list[dict[str, Any]] = []
        recovery_reports: list[dict[str, Any]] = []
        adaptation_reports: list[dict[str, Any]] = []
        available_schemas = self.tool_registry.get_all_schemas()
        pending_steps: list[TaskStep] = list(plan.steps)
        applied_adaptations = 0
        max_adaptations = 2
        completed_step_count = 0

        while pending_steps:
            step = pending_steps.pop(0)
            step_results = []
            for tool_call in step.tool_calls:
                # Execute tool with extracted parameters
                # For now, we still pass user_text but could enhance tools to accept structured params
                tool = self.tool_registry.get(tool_call.tool_name)
                if tool is None:
                    missing = ToolExecutionResult(
                        tool_name=tool_call.tool_name,
                        success=False,
                        output_text=f"Tool '{tool_call.tool_name}' is not registered.",
                    )
                    last_tool_result = missing
                    results.append(f"Step {step.step_number} failed: {missing.output_text}")
                    return (
                        "\n".join(results),
                        last_tool_result,
                        verification_reports,
                        recovery_reports,
                        adaptation_reports,
                    )

                # Build user text from tool call parameters
                param_text = self._build_user_text_from_params(
                    tool_call.parameters,
                    fallback_text=step.description,
                )
                result = await tool.execute(
                    session_id=session_id,
                    user_text=param_text,
                    reasoning=reasoning,
                    memory=memory,
                )

                verification_report = await self._verify_tool_result(
                    tool_result=result,
                    operation_description=step.description,
                    user_intent=user_intent,
                )
                if verification_report is not None:
                    verification_reports.append(model_dump_compat(verification_report))

                if self._needs_recovery(result, verification_report):
                    recovery_result = await self.error_recovery_engine.recover(
                        session_id=session_id,
                        user_intent=step.description,
                        attempted_user_text=param_text,
                        failed_result=result,
                        reasoning=reasoning,
                        memory=memory,
                        available_schemas=available_schemas,
                        tool_registry=self.tool_registry,
                        verify_fn=self._verify_tool_result,
                        step_description=step.description,
                    )
                    recovery_reports.extend(self._serialize_recovery_attempts(recovery_result.attempts))
                    for attempt in recovery_result.attempts:
                        if attempt.verification:
                            verification_reports.append(attempt.verification)

                    if recovery_result.recovered:
                        recovered_result = recovery_result.final_result
                        step_results.append(recovered_result)
                        last_tool_result = recovered_result
                        continue

                    remaining_descriptions = [s.description for s in pending_steps]
                    failure_reason = recovery_result.clarification_question or result.output_text
                    if remaining_descriptions and applied_adaptations < max_adaptations:
                        adapted = await self.multi_step_planner.adapt_plan(
                            original_goal=user_intent,
                            failed_step_description=step.description,
                            failure_reason=failure_reason,
                            completed_steps=list(results),
                            remaining_step_descriptions=remaining_descriptions,
                            available_tools=available_schemas,
                        )
                        if adapted and adapted.steps:
                            applied_adaptations += 1
                            adaptation_reports.append(
                                {
                                    "adaptation_index": applied_adaptations,
                                    "failed_step": step.description,
                                    "failure_reason": failure_reason,
                                    "remaining_before": remaining_descriptions,
                                    "remaining_after": [s.description for s in adapted.steps],
                                }
                            )
                            pending_steps = list(adapted.steps)
                            results.append(
                                f"Plan adapted after step failure ({step.description}). Continuing with updated steps."
                            )
                            break

                    reason = ""
                    if recovery_result.clarification_question:
                        reason = f" ({recovery_result.clarification_question})"
                    elif verification_report is not None and verification_report.suggestions:
                        reason = f" ({verification_report.suggestions[0]})"
                    results.append(f"Step {step.step_number} failed: {result.output_text}{reason}")
                    last_tool_result = result
                    return (
                        "\n".join(results),
                        last_tool_result,
                        verification_reports,
                        recovery_reports,
                        adaptation_reports,
                    )

                # Success path
                step_results.append(result)
                last_tool_result = result
            else:
                # Runs only when inner loop doesn't break.
                if step_results:
                    completed_step_count += 1
                    step_output = " ".join(r.output_text for r in step_results if r.success)
                    results.append(f"Step {completed_step_count}: {step_output}")
                continue

            # If we got here, inner loop broke due adaptive replan.
            continue

        # Combine all step results
        if results:
            assistant_text = "\n".join(results)
        else:
            assistant_text = "Completed the requested operations."

        return (
            assistant_text,
            last_tool_result,
            verification_reports,
            recovery_reports,
            adaptation_reports,
        )

    @staticmethod
    def _build_user_text_from_params(params: dict[str, Any], fallback_text: str = "") -> str:
        """Build natural language user text from structured parameters."""
        # Convert structured params back to natural language for tools
        # This is a bridge until tools support structured parameters directly
        parts = []

        operation = params.get("operation", "")
        if operation:
            parts.append(operation.replace("_", " "))

        if "account_name" in params:
            parts.append(f"account {params['account_name']}")
        if "amount" in params:
            parts.append(str(params["amount"]))
        if "source_account" in params and "target_account" in params:
            parts.append(f"from {params['source_account']} to {params['target_account']}")
        if "title" in params:
            parts.append(params["title"])
        if "due_at" in params:
            parts.append(f"at {params['due_at']}")

        if parts:
            return " ".join(parts)
        if fallback_text:
            return fallback_text
        return str(params)

    async def _verify_tool_result(
        self,
        tool_result: ToolExecutionResult,
        operation_description: str,
        user_intent: str,
    ) -> Any | None:
        """Run ResultVerifier (if configured) after a tool call."""
        if self.result_verifier is None:
            return None

        operation = self._build_operation(tool_result.tool_name, operation_description, tool_result.success)
        return await self.result_verifier.verify(tool_result, operation, user_intent)

    @staticmethod
    def _build_operation(tool_name: str, description: str, success: bool) -> Operation:
        """Infer operation metadata for post-execution verification."""
        lowered = description.lower()

        operation_type: str = "insert"
        if "transfer" in lowered or "move" in lowered:
            operation_type = "transfer"
        elif any(word in lowered for word in ("delete", "remove", "cancel")):
            operation_type = "delete"
        elif any(word in lowered for word in ("update", "edit", "rename", "set", "mark", "complete")):
            operation_type = "update"

        affected_table: str | None = None
        if tool_name == "finance_tool":
            if "transaction" in lowered:
                affected_table = "financial_transactions"
            else:
                affected_table = "financial_accounts"
        elif tool_name == "people_tool":
            affected_table = "people"
        elif tool_name == "reminder_tool":
            affected_table = "reminders"
        elif tool_name == "calendar_tool":
            affected_table = "calendar_events"

        return Operation(
            type=operation_type,  # type: ignore[arg-type]
            affected_table=affected_table,
            row_count_affected=(1 if success else 0),
            description=description,
        )

    @staticmethod
    def _needs_recovery(tool_result: ToolExecutionResult, verification_report: Any | None) -> bool:
        if not tool_result.success:
            return True
        if verification_report is None:
            return False
        return not bool(getattr(verification_report, "success", False))

    @staticmethod
    def _serialize_recovery_attempts(attempts: list[RecoveryAttempt]) -> list[dict[str, Any]]:
        serialized: list[dict[str, Any]] = []
        for attempt in attempts:
            serialized.append(
                {
                    "strategy": attempt.strategy,
                    "tool_name": attempt.tool_name,
                    "input_text": attempt.input_text,
                    "success": attempt.success,
                    "verification_passed": attempt.verification_passed,
                    "output_text": attempt.output_text,
                    "verification": attempt.verification,
                }
            )
        return serialized
