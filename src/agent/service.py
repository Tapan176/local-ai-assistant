"""Facade + background services that tie the agent into the rest of the app."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from src.agent import recurrence, timeutil
from src.agent.loop import AgentLoop, EventCallback, summarize_steps
from src.config.settings import Settings
from src.core.orchestrator import Orchestrator
from src.memory.episodic_memory import EpisodicMemory
from src.models import ConversationTurn, OrchestratorResponse
from src.storage.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)


class AgentOrchestrator:
    """Same ``handle_user_input`` contract as :class:`Orchestrator`.

    Tries the tool-calling agent first. If no LLM provider is configured/reachable (offline,
    ``TAPAN_LLM_PROVIDER=mock``) or the agent errors, it degrades to the legacy pipeline.
    """

    def __init__(
        self,
        settings: Settings,
        agent: AgentLoop,
        legacy: Orchestrator,
        episodic_memory: EpisodicMemory,
    ) -> None:
        self.settings = settings
        self.agent = agent
        self.legacy = legacy
        self.episodic_memory = episodic_memory

    def __getattr__(self, item: str) -> Any:  # keep legacy attribute access (tool_registry, etc.) working
        if item in {"legacy", "agent", "settings", "episodic_memory"}:  # not yet initialised: avoid recursion
            raise AttributeError(item)
        return getattr(self.legacy, item)

    async def handle_user_input(
        self, session_id: str, user_text: str, on_event: EventCallback | None = None
    ) -> OrchestratorResponse:
        if self.settings.agent_enabled and self.settings.llm_provider.lower() != "mock":
            try:
                result = await self.agent.run(session_id, user_text, on_event=on_event)
            except Exception:
                logger.exception("Agent loop crashed; falling back to legacy pipeline")
                result = None
            if result is not None and result.text:
                await self._remember_turn(session_id, user_text, result.text, result.steps)
                last_tool = result.steps[-1].name if result.steps else None
                return OrchestratorResponse(
                    session_id=session_id,
                    text=result.text,
                    action_type="tool" if result.steps else "respond",
                    tool_used=last_tool,
                    debug={
                        "mode": "agent",
                        "provider": result.provider,
                        "model": result.model,
                        "rounds": result.rounds,
                        "steps": summarize_steps(result.steps),
                    },
                )
            logger.warning("No LLM answer available; using legacy offline pipeline")

        response = await self.legacy.handle_user_input(session_id, user_text)
        response.debug.setdefault("mode", "legacy")
        return response

    async def _remember_turn(self, session_id: str, user_text: str, assistant_text: str, steps: list) -> None:
        try:
            await self.episodic_memory.add_turn(
                ConversationTurn(
                    session_id=session_id,
                    user_text=user_text,
                    assistant_text=assistant_text,
                    tool_used=steps[-1].name if steps else None,
                    metadata={"mode": "agent", "tools": [s.name for s in steps]},
                )
            )
        except Exception:
            logger.exception("Could not persist conversation turn")


class ReminderScheduler:
    """Fires due reminders into the notifications table (the open page shows them) and pushes them to subscribed devices."""

    def __init__(self, store: SQLiteStore, settings: Settings, push: Any = None) -> None:
        self.store = store
        self.settings = settings
        self.push = push
        self._task: asyncio.Task | None = None
        # Heartbeat shown on the Status screen: lets you tell "server was asleep" from "scheduler is broken".
        self.stats: dict[str, Any] = {"started_at": datetime.now(timezone.utc).isoformat(), "ticks": 0, "last_tick_at": None,
                                      "fired_total": 0, "last_fired_at": None, "errors": 0, "last_error": None}

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="reminder-scheduler")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception as exc:
                self.stats["errors"] += 1
                self.stats["last_error"] = f"{type(exc).__name__}: {exc}"[:300]
                logger.exception("Reminder scheduler tick failed")
            await asyncio.sleep(self.settings.reminder_poll_seconds)

    async def tick(self) -> int:
        """Fire every pending reminder whose time has come. Returns how many fired."""
        now = timeutil.now(self.settings)
        self.stats["ticks"] += 1
        self.stats["last_tick_at"] = datetime.now(timezone.utc).isoformat()
        rows = await self.store.fetchall(
            "SELECT id, title, due_at, recurrence FROM reminders WHERE status = 'pending' AND due_at IS NOT NULL"
        )
        fired: list[dict[str, Any]] = []
        for row in rows:
            due = timeutil.as_aware(row["due_at"], self.settings)
            if due is None or due > now:
                continue
            rule = recurrence.Rule.from_json(row.get("recurrence"))
            occurrence = due
            claimed = None
            if rule is not None:
                try:
                    occurrence, upcoming = recurrence.latest_and_next(rule, due, now, timeutil.get_tz(self.settings))
                except recurrence.RuleError:
                    rule = None                      # unreadable rule: treat it as a one-off rather than looping forever
                else:
                    # Compare-and-swap on the due time we read: exactly one instance can advance it, so exactly one notifies.
                    # A server that slept through several occurrences fires the latest once and reschedules into the future.
                    claimed = await self.store.fetchone(
                        "UPDATE reminders SET due_at = ? WHERE id = ? AND status = 'pending' AND due_at = ? RETURNING id",
                        (upcoming.isoformat(), row["id"], row["due_at"]),
                    )
            if rule is None:
                # Atomic claim: only the instance whose UPDATE actually flips pending -> fired may notify. During a Render
                # deploy the old and new instance overlap, and a read-then-write here would buzz your phone twice.
                claimed = await self.store.fetchone(
                    "UPDATE reminders SET status = 'fired' WHERE id = ? AND status = 'pending' RETURNING id", (row["id"],)
                )
            if not claimed:
                continue
            await self.store.execute(
                "INSERT INTO notifications (kind, title, body, created_at) VALUES ('reminder', ?, ?, ?)",
                ("Reminder", row["title"], datetime.now(timezone.utc).isoformat()),
            )
            fired.append({"id": row["id"], "title": row["title"], "due": occurrence})
        if fired:
            self.stats["fired_total"] += len(fired)
            self.stats["last_fired_at"] = datetime.now(timezone.utc).isoformat()
        if fired and self.push is not None:
            try:  # a push failure must never stop reminders from firing or the loop from running
                result = await asyncio.wait_for(self.push.notify_reminders(fired, now), timeout=45)
                self.stats["last_delivery"] = result
                logger.info("Push for %d reminder(s): %s", len(fired), result)
            except Exception:
                logger.exception("Push delivery failed")
        return len(fired)
