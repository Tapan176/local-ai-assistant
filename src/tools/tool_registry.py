"""Dynamic tool registry used by the planning layer."""

from __future__ import annotations

from typing import Protocol

from src.models import MemoryContext, ReasoningOutput, ToolExecutionResult
from src.tools.tool_schema import ToolSchema


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
        self._schemas: dict[str, ToolSchema] = {}

    def register(self, tool: ToolProtocol, schema: ToolSchema | None = None) -> None:
        """Register a tool with optional schema."""
        self._tools[tool.name] = tool
        if schema:
            self._schemas[tool.name] = schema

    def register_schema(self, tool_name: str, schema: ToolSchema) -> None:
        """Register schema for a tool."""
        self._schemas[tool_name] = schema

    def get_schema(self, tool_name: str) -> ToolSchema | None:
        """Get schema for a tool."""
        return self._schemas.get(tool_name)

    def get_all_schemas(self) -> list[ToolSchema]:
        """Get all registered tool schemas."""
        return list(self._schemas.values())

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

