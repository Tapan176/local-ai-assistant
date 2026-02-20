"""Error recovery engine for intelligent retries and fallback execution."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from src.core.function_calling_engine import FunctionCallingEngine
from src.models import MemoryContext, ReasoningOutput, ToolExecutionResult
from src.tools.tool_registry import ToolRegistry
from src.tools.tool_schema import ToolSchema


@dataclass(slots=True)
class RecoveryAttempt:
    """Single recovery attempt metadata."""

    strategy: str
    tool_name: str
    input_text: str
    success: bool
    verification_passed: bool | None
    output_text: str
    verification: dict[str, Any] | None = None


@dataclass(slots=True)
class RecoveryResult:
    """Aggregate result of recovery attempts."""

    recovered: bool
    final_result: ToolExecutionResult
    attempts: list[RecoveryAttempt] = field(default_factory=list)
    clarification_question: str | None = None


VerificationFn = Callable[[ToolExecutionResult, str, str], Awaitable[Any | None]]


class ErrorRecoveryEngine:
    """Retry tool operations, then fallback to alternatives, then clarify."""

    def __init__(
        self,
        function_calling_engine: FunctionCallingEngine,
        max_same_tool_retries: int = 2,
        max_alternative_tools: int = 2,
    ) -> None:
        self.function_calling = function_calling_engine
        self.max_same_tool_retries = max_same_tool_retries
        self.max_alternative_tools = max_alternative_tools

    async def recover(
        self,
        *,
        session_id: str,
        user_intent: str,
        attempted_user_text: str,
        failed_result: ToolExecutionResult,
        reasoning: ReasoningOutput,
        memory: MemoryContext,
        available_schemas: list[ToolSchema],
        tool_registry: ToolRegistry,
        verify_fn: VerificationFn | None = None,
        step_description: str = "",
    ) -> RecoveryResult:
        """Attempt recovery after failed or mismatched tool execution."""
        attempts: list[RecoveryAttempt] = []
        failed_tool = failed_result.tool_name

        # 1. Retry with same tool and repaired text.
        retry_inputs = self._build_retry_inputs(
            tool_name=failed_tool,
            user_intent=user_intent,
            attempted_user_text=attempted_user_text,
            failure_output=failed_result.output_text,
            step_description=step_description,
        )
        if retry_inputs:
            # Allow repeated retries with the same prompt for transient failures.
            while len(retry_inputs) < self.max_same_tool_retries:
                retry_inputs.append(retry_inputs[-1])
        for retry_text in retry_inputs[: self.max_same_tool_retries]:
            retry_result = await tool_registry.execute(
                tool_name=failed_tool,
                session_id=session_id,
                user_text=retry_text,
                reasoning=reasoning,
                memory=memory,
            )
            verification_obj = await self._verify_if_needed(
                verify_fn=verify_fn,
                result=retry_result,
                operation_text=retry_text,
                user_intent=user_intent,
            )
            verification_passed = self._verification_passed(verification_obj)
            attempts.append(
                RecoveryAttempt(
                    strategy="same_tool_retry",
                    tool_name=failed_tool,
                    input_text=retry_text,
                    success=retry_result.success,
                    verification_passed=verification_passed,
                    output_text=retry_result.output_text,
                    verification=self._dump_verification(verification_obj),
                )
            )
            if self._effective_success(retry_result, verification_passed):
                return RecoveryResult(recovered=True, final_result=retry_result, attempts=attempts)

        # 2. Try alternative tools.
        alternatives = await self._suggest_alternative_tools(
            user_intent=user_intent,
            failed_tool=failed_tool,
            reasoning=reasoning,
            available_schemas=available_schemas,
        )
        for alt_tool in alternatives[: self.max_alternative_tools]:
            alt_result = await tool_registry.execute(
                tool_name=alt_tool,
                session_id=session_id,
                user_text=user_intent,
                reasoning=reasoning,
                memory=memory,
            )
            verification_obj = await self._verify_if_needed(
                verify_fn=verify_fn,
                result=alt_result,
                operation_text=user_intent,
                user_intent=user_intent,
            )
            verification_passed = self._verification_passed(verification_obj)
            attempts.append(
                RecoveryAttempt(
                    strategy="alternative_tool",
                    tool_name=alt_tool,
                    input_text=user_intent,
                    success=alt_result.success,
                    verification_passed=verification_passed,
                    output_text=alt_result.output_text,
                    verification=self._dump_verification(verification_obj),
                )
            )
            if self._effective_success(alt_result, verification_passed):
                return RecoveryResult(recovered=True, final_result=alt_result, attempts=attempts)

        question = self._build_clarification_question(
            failed_tool=failed_tool,
            user_intent=user_intent,
            failure_output=failed_result.output_text,
        )
        return RecoveryResult(
            recovered=False,
            final_result=failed_result,
            attempts=attempts,
            clarification_question=question,
        )

    @staticmethod
    def _effective_success(result: ToolExecutionResult, verification_passed: bool | None) -> bool:
        if not result.success:
            return False
        if verification_passed is None:
            return True
        return verification_passed

    async def _verify_if_needed(
        self,
        *,
        verify_fn: VerificationFn | None,
        result: ToolExecutionResult,
        operation_text: str,
        user_intent: str,
    ) -> Any | None:
        if verify_fn is None:
            return None
        return await verify_fn(result, operation_text, user_intent)

    @staticmethod
    def _verification_passed(verification_obj: Any | None) -> bool | None:
        if verification_obj is None:
            return None
        return bool(getattr(verification_obj, "success", False))

    @staticmethod
    def _dump_verification(verification_obj: Any | None) -> dict[str, Any] | None:
        if verification_obj is None:
            return None
        if hasattr(verification_obj, "model_dump"):
            return verification_obj.model_dump()
        if hasattr(verification_obj, "dict"):
            return verification_obj.dict()
        return {"value": str(verification_obj)}

    def _build_retry_inputs(
        self,
        *,
        tool_name: str,
        user_intent: str,
        attempted_user_text: str,
        failure_output: str,
        step_description: str,
    ) -> list[str]:
        candidates: list[str] = []
        seen: set[str] = set()

        def add(candidate: str) -> None:
            value = candidate.strip()
            if not value:
                return
            key = value.lower()
            if key in seen:
                return
            seen.add(key)
            candidates.append(value)

        if step_description:
            add(step_description)
        add(user_intent)
        if attempted_user_text and attempted_user_text.lower() != user_intent.lower():
            add(attempted_user_text)

        repaired = self._repair_text(tool_name, user_intent, failure_output)
        if repaired:
            add(repaired)

        return candidates

    def _repair_text(self, tool_name: str, source_text: str, failure_output: str) -> str:
        lowered_source = source_text.lower()
        lowered_failure = failure_output.lower()
        amount = self._extract_amount(source_text)

        if tool_name == "finance_tool":
            if ("need an amount" in lowered_failure or "needs an amount" in lowered_failure) and "balance" in lowered_source:
                account = self._extract_account_hint(source_text)
                if account:
                    return f"show balance of {account}"
                return "show balance"

            if "format like: transfer" in lowered_failure:
                normalized = self._normalize_transfer(source_text, amount)
                if normalized:
                    return normalized

            if amount is not None and any(word in lowered_source for word in ("add", "deposit", "credit")):
                account = self._extract_account_hint(source_text)
                if account:
                    return f"add {amount:g} to {account}"

        if tool_name == "calendar_tool" and "date or time" in lowered_failure:
            return "show upcoming events"

        return ""

    def _normalize_transfer(self, text: str, amount: float | None) -> str:
        if amount is None:
            return ""

        transfer_match = re.search(
            r"from\s+([a-zA-Z][a-zA-Z0-9_\-\s]{1,30})\s+(?:to|into)\s+([a-zA-Z][a-zA-Z0-9_\-\s]{1,30})",
            text,
            flags=re.IGNORECASE,
        )
        if not transfer_match:
            return ""

        source = transfer_match.group(1).strip()
        target = transfer_match.group(2).strip()
        return f"transfer {amount:g} from {source} to {target}"

    async def _suggest_alternative_tools(
        self,
        *,
        user_intent: str,
        failed_tool: str,
        reasoning: ReasoningOutput,
        available_schemas: list[ToolSchema],
    ) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = {failed_tool}

        def add(tool_name: str) -> None:
            if not tool_name:
                return
            if tool_name in seen:
                return
            seen.add(tool_name)
            ordered.append(tool_name)

        for candidate in reasoning.tool_candidates:
            add(candidate)

        tool_calls = await self.function_calling.select_and_extract(
            user_intent,
            available_schemas,
            context={"mode": "error_recovery", "failed_tool": failed_tool},
        )
        for call in tool_calls:
            add(call.tool_name)

        keyword_tool = self._keyword_tool_guess(user_intent)
        if keyword_tool:
            add(keyword_tool)

        return ordered

    @staticmethod
    def _keyword_tool_guess(user_text: str) -> str | None:
        lowered = user_text.lower()
        if any(word in lowered for word in ("remind", "reminder", "remember")):
            return "reminder_tool"
        if any(word in lowered for word in ("schedule", "event", "meeting", "calendar")):
            return "calendar_tool"
        if any(word in lowered for word in ("friend", "person", "who is", "relationship", "contact")):
            return "people_tool"
        if any(word in lowered for word in ("account", "transaction", "balance", "transfer", "money", "finance")):
            return "finance_tool"
        return None

    @staticmethod
    def _extract_amount(text: str) -> float | None:
        match = re.search(r"(?<!\w)(\d+(?:\.\d+)?)(?!\w)", text)
        if not match:
            return None
        try:
            return float(match.group(1))
        except ValueError:
            return None

    @staticmethod
    def _extract_account_hint(text: str) -> str | None:
        patterns = [
            r"\b(?:to|from|of|in)\s+([a-zA-Z][a-zA-Z0-9_\-]{1,30})",
            r"\baccount\s+([a-zA-Z][a-zA-Z0-9_\-]{1,30})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip().title()
        return None

    @staticmethod
    def _build_clarification_question(
        *,
        failed_tool: str,
        user_intent: str,
        failure_output: str,
    ) -> str:
        lowered = failure_output.lower()

        if "amount" in lowered:
            return "I need the exact amount to continue. What amount should I use?"
        if "source account" in lowered or "destination account" in lowered:
            return "Please share both source and destination account names."
        if "date or time" in lowered:
            return "Please provide a specific date/time, for example 'tomorrow at 5 pm'."
        if "id" in lowered:
            return "Please share the item ID so I can complete this action."
        if failed_tool == "finance_tool":
            return "Please confirm the finance action with account name and amount."
        if failed_tool == "calendar_tool":
            return "Please share the event title and exact date/time."
        if failed_tool == "reminder_tool":
            return "Please tell me the reminder text and when it should trigger."
        if failed_tool == "people_tool":
            return "Please tell me the person's name and relationship."
        return f"I could not complete '{user_intent}'. Can you share one more detail?"
