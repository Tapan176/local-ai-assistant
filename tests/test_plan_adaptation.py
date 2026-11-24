"""Tests for Phase 4 adaptive multi-step planning."""

from __future__ import annotations

import asyncio

from src.config.settings import Settings
from src.main import build_runtime


def test_multi_step_plan_adaptation_continues_remaining_steps():
    async def _run() -> None:
        settings = Settings.from_env()
        settings.llm_provider = "mock"
        settings.sqlite_path = ":memory:"

        runtime = await build_runtime(settings=settings)
        response = await runtime.orchestrator.handle_user_input(
            "adapt-session",
            "transfer 9999 from savings to wallet and show accounts",
        )

        assert response.action_type == "tool"
        assert response.tool_used == "finance_tool"
        assert "plan_adaptation" in response.debug
        adaptations = response.debug["plan_adaptation"]
        assert isinstance(adaptations, list)
        assert len(adaptations) >= 1
        assert "account balances" in str(response.text).lower() or "total net balance" in str(response.text).lower()

    asyncio.run(_run())
