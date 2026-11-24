"""Application composition root for TAPAN_AI v1."""

from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import dataclass, field
from typing import Any

import httpx
from fastapi import FastAPI

if sys.platform == "win32":
    # psycopg (Postgres) cannot run on Windows' default Proactor loop. This must happen before any event loop is
    # created, i.e. before asyncio.run(build_runtime(...)) — so it lives here, at the composition root.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from src.agent.loop import AgentLoop
from src.agent.notifier import Notifier
from src.agent.push import PushService
from src.agent.service import AgentOrchestrator, ReminderScheduler
from src.agent.skill import SkillContext, SkillRegistry
from src.agent.skills import build_registry

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
from src.integrations.telegram import TelegramBridge
from src.interfaces.cli import run_cli as run_cli_interface
from src.interfaces.websocket_api import create_api
from src.llm.llm_dispatcher import LLMDispatcher
from src.llm.prompt_builder import PromptBuilder
from src.memory.episodic_memory import EpisodicMemory
from src.memory.memory_retriever import MemoryRetriever
from src.memory.memory_saver import MemorySaver
from src.memory.persona_memory import PersonaMemory
from src.memory.semantic_memory import SemanticMemory
from src.storage.factory import create_store
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
    sqlite_store: Any  # SQLiteStore or PostgresStore (same interface)
    orchestrator: Any  # AgentOrchestrator (agent first, legacy pipeline as offline fallback)
    state_manager: StateManager | None
    data_inspector: DataInspector | None
    result_verifier: ResultVerifier | None
    health_checker: HealthChecker | None = None
    registry: SkillRegistry | None = None
    scheduler: ReminderScheduler | None = None
    http: httpx.AsyncClient | None = None
    llm_dispatcher: LLMDispatcher | None = None
    push: PushService | None = None
    telegram: TelegramBridge | None = None

    def skill_context(self, session_id: str) -> SkillContext:
        assert self.http is not None
        return SkillContext(settings=self.settings, store=self.sqlite_store, http=self.http, session_id=session_id)

    async def aclose(self) -> None:
        if self.scheduler:
            await self.scheduler.stop()
        if self.llm_dispatcher:
            await self.llm_dispatcher.chat_client.aclose()
        if hasattr(self.sqlite_store, "aclose"):
            await self.sqlite_store.aclose()
        if self.http:
            await self.http.aclose()


async def build_runtime(settings: Settings | None = None) -> Runtime:
    settings = settings or get_settings()
    if settings.environment.lower() != "local" and not settings.database_url:
        logging.getLogger(__name__).warning(
            "Hosted mode (TAPAN_ENV=%s) without TAPAN_DATABASE_URL: using local SQLite at %s. "
            "On most hosts that file is wiped on every restart/deploy — set TAPAN_DATABASE_URL (Postgres) or mount a disk.",
            settings.environment,
            settings.sqlite_path,
        )
    sqlite_store = create_store(settings)
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
    state_manager: StateManager | None = None
    data_inspector: DataInspector | None = None
    result_verifier: ResultVerifier | None = None
    if getattr(sqlite_store, "dialect", "sqlite") == "sqlite":
        # The legacy safety/verification layer introspects SQLite internals (PRAGMA, sqlite_master).
        state_manager = StateManager(sqlite_store)
        data_inspector = DataInspector(sqlite_store)
        result_verifier = ResultVerifier(sqlite_store, data_inspector, state_manager)

    tool_registry = ToolRegistry()
    # Register tools
    finance_tool = FinanceTool(sqlite_store)
    people_tool = PeopleTool(sqlite_store, supermemory_store)
    calendar_tool = CalendarTool(sqlite_store)
    tool_registry.register(finance_tool)
    tool_registry.register(ReminderTool(sqlite_store))
    tool_registry.register(people_tool)
    tool_registry.register(calendar_tool)
    
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
    
    # ── Jarvis agent layer ──────────────────────────────────────────
    http = httpx.AsyncClient(follow_redirects=False)
    registry = build_registry(settings, finance=finance_tool, people=people_tool, calendar=calendar_tool)

    def skill_ctx(session_id: str) -> SkillContext:
        return SkillContext(settings=settings, store=sqlite_store, http=http, session_id=session_id)

    agent = AgentLoop(settings, llm_dispatcher.chat_client, registry, sqlite_store, skill_ctx)
    agent_orchestrator = AgentOrchestrator(settings, agent, orchestrator, episodic_memory)

    push_service = PushService(sqlite_store, settings)
    telegram = TelegramBridge(sqlite_store, settings, http)

    async def telegram_chat(session_id: str, text: str) -> str:
        return (await agent_orchestrator.handle_user_input(session_id, text)).text

    telegram.handler = telegram_chat
    notifier = Notifier(push=push_service, telegram=telegram)       # every channel, each isolated from the others' failures

    return Runtime(
        settings=settings,
        sqlite_store=sqlite_store,
        orchestrator=agent_orchestrator,
        state_manager=state_manager,
        data_inspector=data_inspector,
        result_verifier=result_verifier,
        health_checker=health_checker,
        registry=registry,
        scheduler=ReminderScheduler(sqlite_store, settings, push=notifier),
        push=push_service,
        telegram=telegram,
        http=http,
        llm_dispatcher=llm_dispatcher,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime = asyncio.run(build_runtime(settings=settings))
    return create_api(runtime.orchestrator, runtime.settings, runtime.health_checker, runtime=runtime)


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

    if settings.environment.lower() == "local":  # never try to open a browser on a server

        def open_browser():
            time.sleep(1.5)
            webbrowser.open(f"http://{settings.api_host}:{settings.api_port}")

        threading.Thread(target=open_browser, daemon=True).start()

    app = create_app(settings=settings)
    uvicorn.run(
        app,
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.log_level.lower(),
        # On Windows uvicorn forces the Proactor loop, which psycopg cannot use; "none" defers to our selector policy.
        loop="none" if sys.platform == "win32" else "auto",
    )


if __name__ == "__main__":
    run_api()
