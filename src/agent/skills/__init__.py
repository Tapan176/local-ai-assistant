"""Skill registry assembly."""

from __future__ import annotations

from typing import Any

from src.agent.skill import SkillRegistry
from src.config.settings import Settings

from . import briefing, core, expenses, graph, legacy, local, notebook, web


def build_registry(settings: Settings, finance: Any = None, people: Any = None, calendar: Any = None) -> SkillRegistry:
    registry = SkillRegistry()
    core.register(registry)
    web.register(registry)
    briefing.register(registry)
    expenses.register(registry)
    notebook.register(registry)
    graph.register(registry)
    if finance and people and calendar:
        legacy.register(registry, finance, people, calendar)
    if settings.local_skills_enabled:
        local.register(registry)
    return registry
