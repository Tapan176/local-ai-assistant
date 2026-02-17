"""Application composition root for TAPAN_AI v2."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from fastapi import FastAPI

from tapan_ai.config.settings import Settings, get_settings
from tapan_ai.core.emotional_engine import EmotionalEngine
from tapan_ai.core.orchestrator import Orchestrator
from tapan_ai.core.perception_engine import PerceptionEngine
from tapan_ai.core.planning_engine import PlanningEngine
from tapan_ai.core.reasoning_engine import ReasoningEngine
from tapan_ai.core.self_reflection import SelfReflectionEngine
from tapan_ai.interfaces.cli import run_cli as run_cli_interface
from tapan_ai.interfaces.websocket_api import create_api
from tapan_ai.llm.llm_dispatcher import LLMDispatcher
from tapan_ai.llm.prompt_builder import PromptBuilder
from tapan_ai.memory.episodic_memory import EpisodicMemory
from tapan_ai.memory.memory_retriever import MemoryRetriever
from tapan_ai.memory.memory_saver import MemorySaver
from tapan_ai.memory.persona_memory import PersonaMemory
from tapan_ai.memory.semantic_memory import SemanticMemory
from tapan_ai.storage.graph_store import GraphStore
from tapan_ai.storage.sqlite_store import SQLiteStore
from tapan_ai.storage.vector_store import create_vector_store
from tapan_ai.tools.calendar_tool import CalendarTool
from tapan_ai.tools.finance_tool import FinanceTool
from tapan_ai.tools.people_tool import PeopleTool
from tapan_ai.tools.reminder_tool import ReminderTool
from tapan_ai.tools.tool_registry import ToolRegistry


@dataclass(slots=True)
class Runtime:
    settings: Settings
    sqlite_store: SQLiteStore
    orchestrator: Orchestrator


async def build_runtime(settings: Settings | None = None) -> Runtime:
    settings = settings or get_settings()
    sqlite_store = SQLiteStore(settings.sqlite_path)
    await sqlite_store.initialize()

    vector_store = create_vector_store(settings)
    graph_store = GraphStore(sqlite_store)

    episodic_memory = EpisodicMemory(sqlite_store)
    semantic_memory = SemanticMemory(sqlite_store, vector_store)
    persona_memory = PersonaMemory(sqlite_store)
    memory_retriever = MemoryRetriever(
        episodic_memory=episodic_memory,
        semantic_memory=semantic_memory,
        persona_memory=persona_memory,
        graph_store=graph_store,
        max_items=settings.max_memory_items,
    )
    memory_saver = MemorySaver(
        episodic_memory=episodic_memory,
        semantic_memory=semantic_memory,
        persona_memory=persona_memory,
        graph_store=graph_store,
    )

    llm_dispatcher = LLMDispatcher(settings)
    prompt_builder = PromptBuilder()

    emotional_engine = EmotionalEngine()
    perception_engine = PerceptionEngine(emotional_engine)
    reasoning_engine = ReasoningEngine(llm_dispatcher)
    planning_engine = PlanningEngine()
    self_reflection = SelfReflectionEngine()

    tool_registry = ToolRegistry()
    tool_registry.register(FinanceTool(sqlite_store))
    tool_registry.register(ReminderTool(sqlite_store))
    tool_registry.register(PeopleTool(sqlite_store, graph_store))
    tool_registry.register(CalendarTool(sqlite_store))

    orchestrator = Orchestrator(
        perception_engine=perception_engine,
        memory_retriever=memory_retriever,
        reasoning_engine=reasoning_engine,
        planning_engine=planning_engine,
        tool_registry=tool_registry,
        prompt_builder=prompt_builder,
        llm_dispatcher=llm_dispatcher,
        self_reflection=self_reflection,
        memory_saver=memory_saver,
    )
    return Runtime(settings=settings, sqlite_store=sqlite_store, orchestrator=orchestrator)


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime = asyncio.run(build_runtime(settings=settings))
    return create_api(runtime.orchestrator, runtime.settings)


def run_cli() -> None:
    async def _runner() -> None:
        runtime = await build_runtime()
        await run_cli_interface(runtime.orchestrator, runtime.settings)

    asyncio.run(_runner())


def run_api() -> None:
    import uvicorn

    settings = get_settings()
    app = create_app(settings=settings)
    uvicorn.run(app, host=settings.api_host, port=settings.api_port)


if __name__ == "__main__":
    run_cli()

