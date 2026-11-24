"""Skill abstraction: a named, JSON-schema-described async function the LLM can call."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import httpx

from src.agent import timeutil
from src.config.settings import Settings
from src.storage.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)

MAX_RESULT_CHARS = 6000
SKILL_TIMEOUT_SECONDS = 30


@dataclass(slots=True)
class SkillContext:
    settings: Settings
    store: SQLiteStore
    http: httpx.AsyncClient
    session_id: str = ""

    def now(self):
        return timeutil.now(self.settings)


Handler = Callable[[SkillContext, dict[str, Any]], Awaitable[Any]]


def schema(properties: dict[str, dict[str, Any]] | None = None, required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": properties or {}, "required": required or []}


@dataclass(slots=True)
class Skill:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Handler
    local_only: bool = False

    def to_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": self.parameters},
        }


@dataclass(slots=True)
class SkillRegistry:
    skills: dict[str, Skill] = field(default_factory=dict)

    def add(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        handler: Handler,
        local_only: bool = False,
    ) -> None:
        self.skills[name] = Skill(name, description, parameters, handler, local_only)

    def names(self) -> list[str]:
        return sorted(self.skills)

    def tools(self) -> list[dict[str, Any]]:
        return [s.to_openai_tool() for s in self.skills.values()]

    async def execute(self, name: str, args: dict[str, Any], ctx: SkillContext) -> tuple[bool, str]:
        """Run a skill. Never raises: failures come back as text so the model can self-correct."""
        skill = self.skills.get(name)
        if skill is None:
            return False, f"Unknown tool '{name}'. Available: {', '.join(self.names())}"
        if "_invalid_json" in args:
            return False, "Your arguments were not valid JSON. Call the tool again with valid JSON arguments."

        missing = [k for k in skill.parameters.get("required", []) if args.get(k) in (None, "")]
        if missing:
            return False, f"Missing required argument(s): {', '.join(missing)}"

        try:
            result = await asyncio.wait_for(skill.handler(ctx, args), timeout=SKILL_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            return False, f"Tool '{name}' timed out after {SKILL_TIMEOUT_SECONDS}s."
        except Exception as exc:
            logger.exception("Skill %s failed", name)
            return False, f"Tool '{name}' failed: {exc}"

        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
        if len(text) > MAX_RESULT_CHARS:
            text = text[:MAX_RESULT_CHARS] + f"\n…[truncated {len(text) - MAX_RESULT_CHARS} chars]"
        return True, text
