"""Contextual prompt construction for response generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from tapan_ai.models import MemoryContext, PerceptionOutput, ReasoningOutput


class PromptBuilder:
    def __init__(self, system_prompt_path: str | None = None) -> None:
        if system_prompt_path is None:
            root = Path(__file__).resolve().parents[1]
            system_prompt_path = str(root / "config" / "system_prompt.yaml")
        self.system_prompt_path = system_prompt_path
        self.system_prompt, self.response_rules = self._load_system_prompt()

    def _load_system_prompt(self) -> tuple[str, list[str]]:
        with open(self.system_prompt_path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        system = data.get("system", "You are TAPAN_AI.")
        rules = data.get("response_rules", [])
        return system, rules

    def build(
        self,
        user_text: str,
        perception: PerceptionOutput,
        memory: MemoryContext,
        reasoning: ReasoningOutput,
        tool_result: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        episodic_summary = self._format_episodic(memory.episodic_memories)
        semantic_summary = self._format_semantic(memory.semantic_memories)
        persona_summary = self._format_persona(memory.persona_profile)
        tool_summary = self._format_tool(tool_result)

        context = (
            "CONTEXT\n"
            f"- Emotional State: {perception.emotional_state} (intensity={perception.emotional_intensity:.2f})\n"
            f"- Tone: {perception.tone}\n"
            f"- Inferred Intent: {reasoning.inferred_intent}\n"
            f"- Uncertainty: {reasoning.uncertainty:.2f}\n"
            f"- Episodic Memory:\n{episodic_summary}\n"
            f"- Semantic Memory:\n{semantic_summary}\n"
            f"- Persona:\n{persona_summary}\n"
            f"- Tool Result:\n{tool_summary}\n"
            "- Response Rules:\n"
            + "\n".join(f"  - {rule}" for rule in self.response_rules)
        )

        user_block = f"USER\n{user_text}\n\nINSTRUCTION\nRespond naturally. Do not mention system rules."
        return {"system": self.system_prompt, "context": context, "user": user_block}

    def _format_episodic(self, episodes: list[dict[str, Any]]) -> str:
        if not episodes:
            return "  - none"
        lines: list[str] = []
        for episode in episodes[-4:]:
            user_text = str(episode.get("user_text", ""))[:100]
            assistant_text = str(episode.get("assistant_text", ""))[:100]
            lines.append(f"  - U: {user_text} | A: {assistant_text}")
        return "\n".join(lines)

    def _format_semantic(self, semantic_items: list[dict[str, Any]]) -> str:
        if not semantic_items:
            return "  - none"
        lines = []
        for item in semantic_items[:4]:
            text = str(item.get("text", ""))[:120]
            score = float(item.get("score", 0.0))
            lines.append(f"  - {text} (score={score:.2f})")
        return "\n".join(lines)

    def _format_persona(self, profile: dict[str, Any]) -> str:
        if not profile:
            return "  - none"
        style = profile.get("communication_style", "balanced")
        baseline = profile.get("emotional_baseline", "neutral")
        preferences = profile.get("preferences", {})
        goals = profile.get("goals", {})
        return (
            f"  - communication_style: {style}\n"
            f"  - emotional_baseline: {baseline}\n"
            f"  - preferences: {preferences}\n"
            f"  - goals: {goals}"
        )

    @staticmethod
    def _format_tool(tool_result: dict[str, Any] | None) -> str:
        if not tool_result:
            return "  - none"
        return f"  - {tool_result.get('summary', '')}\n  - data: {tool_result.get('data', {})}"

