"""Dynamic tool registry used by the planning layer."""

from __future__ import annotations

from typing import Protocol

from tapan_ai.models import MemoryContext, ReasoningOutput, ToolExecutionResult


class ToolProtocol(Protocol):
    name: str
    description: str

    async def execute(
        self,
        session_id: str,
        user_text: str,
        reasoning: ReasoningOutput,
        memory: MemoryContext,
    ) -> ToolExecutionResult:
        ...


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolProtocol] = {}

    def register(self, tool: ToolProtocol) -> None:
        self._tools[tool.name] = tool

    def names(self) -> list[str]:
        return sorted(self._tools.keys())

    def get(self, tool_name: str) -> ToolProtocol | None:
        return self._tools.get(tool_name)

    async def execute(
        self,
        tool_name: str,
        session_id: str,
        user_text: str,
        reasoning: ReasoningOutput,
        memory: MemoryContext,
    ) -> ToolExecutionResult:
        tool = self.get(tool_name)
        if tool is None:
            return ToolExecutionResult(
                tool_name=tool_name,
                success=False,
                output_text=f"I couldn't find the tool '{tool_name}'.",
            )
        return await tool.execute(session_id=session_id, user_text=user_text, reasoning=reasoning, memory=memory)

