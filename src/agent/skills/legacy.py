"""Expose the original NL-driven tools (finance, people, calendar) as agent skills.

Those tools parse a natural-language command themselves, so each wrapper takes a single
plain-English ``request`` and hands it over unchanged.
"""

from __future__ import annotations

from typing import Any

from src.agent.skill import SkillContext, SkillRegistry, schema
from src.models import MemoryContext, ReasoningOutput


def _wrap(tool: Any):
    async def handler(ctx: SkillContext, args: dict[str, Any]) -> str:
        reasoning = ReasoningOutput(inferred_intent=tool.name, confidence=1.0)
        result = await tool.execute(
            session_id=ctx.session_id, user_text=str(args["request"]), reasoning=reasoning, memory=MemoryContext()
        )
        return result.output_text if result.success else f"Failed: {result.output_text}"

    return handler


def _request_schema(hint: str) -> dict[str, Any]:
    return schema({"request": {"type": "string", "description": hint}}, ["request"])


def register(registry: SkillRegistry, finance: Any, people: Any, calendar: Any) -> None:
    registry.add(
        "finance_assistant",
        "Track money: accounts, balances, transactions, transfers. Pass a short plain-English command such as "
        "'add 400 to axis', 'transfer 200 from axis to wallet', 'show balances', 'create account savings with 5000'.",
        _request_schema("Plain-English finance command"),
        _wrap(finance),
    )
    registry.add(
        "people_assistant",
        "Remember and look up people and relationships. Commands like 'Ravi is my manager', 'who is Ravi', 'list people'.",
        _request_schema("Plain-English people command"),
        _wrap(people),
    )
    registry.add(
        "calendar_assistant",
        "Manage calendar events. Commands like 'schedule design review tomorrow at 5 pm', 'show my events today'.",
        _request_schema("Plain-English calendar command"),
        _wrap(calendar),
    )
