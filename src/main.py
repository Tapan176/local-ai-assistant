"""Application composition root for TAPAN_AI v1."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from fastapi import FastAPI

from src.config.settings import Settings, get_settings
from src.core.emotional_engine import EmotionalEngine
from src.core.orchestrator import Orchestrator
from src.core.output_sanitizer import OutputSanitizer
from src.core.perception_engine import PerceptionEngine
from src.core.health_check import HealthChecker
from src.core.performance_monitor import PerformanceMonitor
from src.core.planning_engine import PlanningEngine
from src.core.proactive_engine import ProactiveEngine
from src.core.reference_resolver import ReferenceResolver
from src.core.reasoning_engine import ReasoningEngine
from src.core.self_reflection import SelfReflectionEngine
from src.core.state_manager import StateManager
from src.core.data_inspector import DataInspector
from src.core.result_verifier import ResultVerifier
from src.interfaces.cli import run_cli as run_cli_interface
from src.interfaces.websocket_api import create_api
from src.llm.llm_dispatcher import LLMDispatcher
from src.llm.prompt_builder import PromptBuilder
from src.memory.episodic_memory import EpisodicMemory
from src.memory.memory_retriever import MemoryRetriever
from src.memory.memory_saver import MemorySaver
from src.memory.persona_memory import PersonaMemory
from src.memory.semantic_memory import SemanticMemory
from src.storage.sqlite_store import SQLiteStore
from src.storage.supermemory_store import SupermemoryStore
from src.tools.calendar_tool import CalendarTool
from src.tools.finance_tool import FinanceTool
from src.tools.people_tool import PeopleTool
from src.tools.reminder_tool import ReminderTool
from src.tools.schemas import get_all_tool_schemas
from src.tools.tool_registry import ToolRegistry


@dataclass(slots=True)
class Runtime:
    settings: Settings
    sqlite_store: SQLiteStore
    orchestrator: Orchestrator
    state_manager: StateManager
    data_inspector: DataInspector
    result_verifier: ResultVerifier
    health_checker: HealthChecker | None = None


async def build_runtime(settings: Settings | None = None) -> Runtime:
    settings = settings or get_settings()
    sqlite_store = SQLiteStore(settings.sqlite_path)
    await sqlite_store.initialize()

    supermemory_store = SupermemoryStore(settings.supermemory_api_key)

    episodic_memory = EpisodicMemory(sqlite_store, supermemory_store)
    semantic_memory = SemanticMemory(sqlite_store, supermemory_store)
    persona_memory = PersonaMemory(sqlite_store, supermemory_store)
    memory_retriever = MemoryRetriever(
        episodic_memory=episodic_memory,
        semantic_memory=semantic_memory,
        persona_memory=persona_memory,
        supermemory_store=supermemory_store,
        max_items=settings.max_memory_items,
    )
    memory_saver = MemorySaver(
        episodic_memory=episodic_memory,
        semantic_memory=semantic_memory,
        persona_memory=persona_memory,
        supermemory_store=supermemory_store,
    )

    llm_dispatcher = LLMDispatcher(settings)
    prompt_builder = PromptBuilder()

    emotional_engine = EmotionalEngine()
    perception_engine = PerceptionEngine(emotional_engine, spacy_model=settings.spacy_model)
    reasoning_engine = ReasoningEngine(llm_dispatcher)
    planning_engine = PlanningEngine()
    self_reflection = SelfReflectionEngine()
    proactive_engine = ProactiveEngine(sqlite_store)
    output_sanitizer = OutputSanitizer()
    reference_resolver = ReferenceResolver()
    performance_monitor = PerformanceMonitor()
    state_manager = StateManager(sqlite_store)
    data_inspector = DataInspector(sqlite_store)
    result_verifier = ResultVerifier(sqlite_store, data_inspector, state_manager)

    tool_registry = ToolRegistry()
    # Register tools
    tool_registry.register(FinanceTool(sqlite_store))
    tool_registry.register(ReminderTool(sqlite_store))
    tool_registry.register(PeopleTool(sqlite_store, supermemory_store))
    tool_registry.register(CalendarTool(sqlite_store))
    
    # Register tool schemas (for function calling)
    schemas = get_all_tool_schemas()
    for schema in schemas:
        tool_registry.register_schema(schema.name, schema)

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
        output_sanitizer=output_sanitizer,
        reference_resolver=reference_resolver,
        proactive_engine=proactive_engine,
        performance_monitor=performance_monitor,
        result_verifier=result_verifier,
    )
    
    health_checker = HealthChecker(
        sqlite_store=sqlite_store,
        llm_dispatcher=llm_dispatcher,
        supermemory_store=supermemory_store,
    )
    
    return Runtime(
        settings=settings,
        sqlite_store=sqlite_store,
        orchestrator=orchestrator,
        state_manager=state_manager,
        data_inspector=data_inspector,
        result_verifier=result_verifier,
        health_checker=health_checker,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime = asyncio.run(build_runtime(settings=settings))
    return create_api(runtime.orchestrator, runtime.settings, runtime.health_checker)


def run_cli() -> None:
    async def _runner() -> None:
        runtime = await build_runtime()
        await run_cli_interface(runtime.orchestrator, runtime.settings)

    asyncio.run(_runner())


def run_api() -> None:
    import uvicorn
    import webbrowser
    import threading
    import time

    settings = get_settings()
    
    def open_browser():
        time.sleep(1.5)
        webbrowser.open(f"http://{settings.api_host}:{settings.api_port}")

    threading.Thread(target=open_browser, daemon=True).start()
    
    app = create_app(settings=settings)
    uvicorn.run(app, host=settings.api_host, port=settings.api_port, log_level=settings.log_level.lower())


if __name__ == "__main__":
    run_api()
