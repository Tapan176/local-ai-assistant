"""Quick test for people and finance tool enhancements."""

from __future__ import annotations

import pytest

from src.models import MemoryContext, ReasoningOutput
from src.storage.graph_store import GraphStore
from src.storage.sqlite_store import SQLiteStore
from src.tools.finance_tool import FinanceTool
from src.tools.people_tool import PeopleTool

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_people_and_finance_quick() -> None:
    store = SQLiteStore(":memory:")
    await store.initialize()
    graph = GraphStore(store)
    people_tool = PeopleTool(store, graph)
    finance_tool = FinanceTool(store)

    people_reasoning = ReasoningOutput(
        inferred_intent="people_memory_update",
        confidence=0.9,
        needs_clarification=False,
        possible_actions=[],
        tool_candidates=[],
        uncertainty=0.1,
        rationale="",
    )
    memory = MemoryContext()

    add_person = await people_tool.execute("s1", "add a friend roy who has a joyful nature", people_reasoning, memory)
    assert add_person.success, add_person.output_text

    set_relation = await people_tool.execute("s1", "name ROY relation friend", people_reasoning, memory)
    assert set_relation.success, set_relation.output_text

    finance_reasoning = ReasoningOutput(
        inferred_intent="financial_update",
        confidence=0.9,
        needs_clarification=False,
        possible_actions=[],
        tool_candidates=[],
        uncertainty=0.1,
        rationale="",
    )
    add_account = await finance_tool.execute("s1", "add one account axis with 400 balance", finance_reasoning, memory)
    assert add_account.success, add_account.output_text
