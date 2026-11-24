"""Function calling engine for LLM-based tool selection and parameter extraction."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from src.llm.llm_dispatcher import LLMDispatcher
from src.tools.tool_schema import ToolSchema

logger = logging.getLogger(__name__)


@dataclass
class ToolCall:
    """Represents a tool call with extracted parameters."""
    tool_name: str
    parameters: dict[str, Any]
    confidence: float = 1.0


class FunctionCallingEngine:
    """Engine for LLM-based function calling (like Cursor/Copilot)."""

    def __init__(self, llm_dispatcher: LLMDispatcher) -> None:
        self.llm = llm_dispatcher

    async def select_and_extract(
        self,
        user_text: str,
        available_tools: list[ToolSchema],
        context: dict[str, Any] | None = None,
    ) -> list[ToolCall]:
        """Use LLM to select tools and extract parameters from user input."""
        if not available_tools:
            return []

        # Format tools for LLM
        tools_json = [tool.to_openai_format() for tool in available_tools]
        
        # Build prompt for function calling
        prompt = self._build_function_calling_prompt(user_text, tools_json, context)
        
        try:
            # Use LLM to select tools and extract parameters
            response = await self.llm.generate_text(
                system="You are a tool selection and parameter extraction assistant. Analyze the user's request and determine which tools to call with what parameters. Return valid JSON only.",
                context=prompt,
                user=user_text,
                temperature=0.1,
                json_mode=True,
            )
            
            # Parse LLM response
            parsed = json.loads(response)
            tool_calls = []
            
            # Handle single tool call or array
            calls = parsed if isinstance(parsed, list) else [parsed]
            
            for call in calls:
                tool_name = call.get("tool_name") or call.get("name")
                params = call.get("parameters") or call.get("params") or {}
                
                if tool_name:
                    tool_calls.append(
                        ToolCall(
                            tool_name=tool_name,
                            parameters=params,
                            confidence=float(call.get("confidence", 1.0)),
                        )
                    )

            if not tool_calls:
                logger.warning("No valid tool calls in LLM response, falling back to heuristic selection")
                return self._heuristic_fallback(user_text, available_tools)

            return tool_calls
        except Exception as e:
            logger.warning("Function calling failed: %s, falling back to heuristic", e)
            return self._heuristic_fallback(user_text, available_tools)

    def _build_function_calling_prompt(
        self,
        user_text: str,
        tools_json: list[dict[str, Any]],
        context: dict[str, Any] | None,
    ) -> str:
        """Build prompt for function calling."""
        prompt = "Available tools:\n"
        for tool in tools_json:
            prompt += f"- {tool['name']}: {tool['description']}\n"
            if tool.get("parameters", {}).get("properties"):
                prompt += "  Parameters:\n"
                for param_name, param_spec in tool["parameters"]["properties"].items():
                    required = param_name in tool["parameters"].get("required", [])
                    prompt += f"    - {param_name} ({param_spec['type']}): {param_spec['description']}"
                    if required:
                        prompt += " [REQUIRED]"
                    prompt += "\n"
        
        if context:
            prompt += f"\nContext: {json.dumps(context, indent=2)}\n"
        
        prompt += (
            "\nAnalyze the user's request and return JSON array of tool calls:\n"
            "[{\"tool_name\": \"...\", \"parameters\": {...}, \"confidence\": 0.0-1.0}]\n"
            "Extract all parameters from user text. If multiple tools needed, return multiple calls."
        )
        
        return prompt

    def _heuristic_fallback(
        self,
        user_text: str,
        available_tools: list[ToolSchema],
    ) -> list[ToolCall]:
        """Fallback to heuristic tool selection when LLM fails."""
        lowered = user_text.lower()
        tool_calls = []
        
        # Simple keyword matching
        for tool in available_tools:
            if tool.name == "finance_tool":
                if any(word in lowered for word in ("account", "balance", "transaction", "transfer", "money", "finance")):
                    tool_calls.append(ToolCall(tool_name=tool.name, parameters={}, confidence=0.7))
            elif tool.name == "reminder_tool":
                if any(word in lowered for word in ("remind", "reminder", "remember")):
                    tool_calls.append(ToolCall(tool_name=tool.name, parameters={}, confidence=0.7))
            elif tool.name == "calendar_tool":
                if any(word in lowered for word in ("schedule", "meeting", "calendar", "event")):
                    tool_calls.append(ToolCall(tool_name=tool.name, parameters={}, confidence=0.7))
            elif tool.name == "people_tool":
                if any(word in lowered for word in ("friend", "person", "who is", "relation")):
                    tool_calls.append(ToolCall(tool_name=tool.name, parameters={}, confidence=0.7))
        
        return tool_calls[:1]  # Return first match only for fallback
