"""Unit tests for Phase 3 error recovery behavior."""

from __future__ import annotations

import asyncio

from src.core.error_recovery_engine import ErrorRecoveryEngine
from src.models import MemoryContext, ReasoningOutput, ToolExecutionResult
from src.tools.tool_registry import ToolRegistry


class FakeFunctionCalling:
    async def select_and_extract(self, user_text, available_tools, context=None):  # noqa: ANN001
        del user_text, available_tools, context
        return []


class DummyTool:
    def __init__(self, name: str, responses: list[tuple[bool, str]]) -> None:
        self.name = name
        self.description = "dummy"
        self._responses = responses
        self._index = 0

    async def execute(self, session_id, user_text, reasoning, memory):  # noqa: ANN001
        del session_id, user_text, reasoning, memory
        if not self._responses:
            return ToolExecutionResult(tool_name=self.name, success=False, output_text="No response configured.")

        idx = min(self._index, len(self._responses) - 1)
        success, text = self._responses[idx]
        self._index += 1
        return ToolExecutionResult(tool_name=self.name, success=success, output_text=text)


def _reasoning(tool_candidates: list[str]) -> ReasoningOutput:
    return ReasoningOutput(
        inferred_intent="test_intent",
        confidence=0.9,
        needs_clarification=False,
        clarification_question=None,
        possible_actions=[],
        tool_candidates=tool_candidates,
        uncertainty=0.1,
        rationale="test",
    )


def test_error_recovery_same_tool_retry_success():
    async def _run() -> None:
        registry = ToolRegistry()
        registry.register(DummyTool("flaky_tool", [(False, "temporary failure"), (True, "recovered")]))

        engine = ErrorRecoveryEngine(FakeFunctionCalling(), max_same_tool_retries=2, max_alternative_tools=1)
        failed = ToolExecutionResult(tool_name="flaky_tool", success=False, output_text="initial failure")

        result = await engine.recover(
            session_id="s1",
            user_intent="run flaky operation",
            attempted_user_text="run flaky operation",
            failed_result=failed,
            reasoning=_reasoning(["flaky_tool"]),
            memory=MemoryContext(),
            available_schemas=[],
            tool_registry=registry,
        )

        assert result.recovered
        assert result.final_result.success
        assert result.final_result.tool_name == "flaky_tool"
        assert any(a.strategy == "same_tool_retry" and a.success for a in result.attempts)

    asyncio.run(_run())


def test_error_recovery_fallback_to_alternative_tool():
    async def _run() -> None:
        registry = ToolRegistry()
        registry.register(DummyTool("primary_tool", [(False, "primary failed"), (False, "still failed")]))
        registry.register(DummyTool("backup_tool", [(True, "backup succeeded")]))

        engine = ErrorRecoveryEngine(FakeFunctionCalling(), max_same_tool_retries=1, max_alternative_tools=2)
        failed = ToolExecutionResult(tool_name="primary_tool", success=False, output_text="initial primary failure")

        result = await engine.recover(
            session_id="s2",
            user_intent="complete operation",
            attempted_user_text="complete operation",
            failed_result=failed,
            reasoning=_reasoning(["primary_tool", "backup_tool"]),
            memory=MemoryContext(),
            available_schemas=[],
            tool_registry=registry,
        )

        assert result.recovered
        assert result.final_result.success
        assert result.final_result.tool_name == "backup_tool"
        assert any(a.strategy == "alternative_tool" and a.tool_name == "backup_tool" for a in result.attempts)

    asyncio.run(_run())


def test_error_recovery_returns_clarification_on_terminal_failure():
    async def _run() -> None:
        registry = ToolRegistry()
        registry.register(DummyTool("finance_tool", [(False, "I need an amount"), (False, "I need an amount")]))

        engine = ErrorRecoveryEngine(FakeFunctionCalling(), max_same_tool_retries=1, max_alternative_tools=1)
        failed = ToolExecutionResult(tool_name="finance_tool", success=False, output_text="I need an amount")

        result = await engine.recover(
            session_id="s3",
            user_intent="update balance",
            attempted_user_text="update balance",
            failed_result=failed,
            reasoning=_reasoning(["finance_tool"]),
            memory=MemoryContext(),
            available_schemas=[],
            tool_registry=registry,
        )

        assert not result.recovered
        assert result.final_result.tool_name == "finance_tool"
        assert result.clarification_question is not None
        assert "amount" in result.clarification_question.lower()

    asyncio.run(_run())
