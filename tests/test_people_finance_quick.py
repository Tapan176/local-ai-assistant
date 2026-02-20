"""Quick test for people and finance tool enhancements."""
import asyncio
from src.tools.people_tool import PeopleTool
from src.tools.finance_tool import FinanceTool
from src.storage.sqlite_store import SQLiteStore
from src.storage.graph_store import GraphStore
from src.models import ReasoningOutput, MemoryContext


async def test():
    store = SQLiteStore(":memory:")
    await store.initialize()
    graph = GraphStore(store)
    pt = PeopleTool(store, graph)
    ft = FinanceTool(store)
    ro = ReasoningOutput(
        inferred_intent="people_memory_update",
        confidence=0.9,
        needs_clarification=False,
        possible_actions=[],
        tool_candidates=[],
        uncertainty=0.1,
        rationale="",
    )
    mem = MemoryContext()

    r1 = await pt.execute("s1", "add a friend roy who has a joyful nature", ro, mem)
    print("People add friend:", r1.success, r1.output_text[:60] if r1.output_text else "")

    r2 = await pt.execute("s1", "name ROY relation friend", ro, mem)
    print("People name relation:", r2.success, r2.output_text[:60] if r2.output_text else "")

    ro2 = ReasoningOutput(
        inferred_intent="financial_update",
        confidence=0.9,
        needs_clarification=False,
        possible_actions=[],
        tool_candidates=[],
        uncertainty=0.1,
        rationale="",
    )
    r3 = await ft.execute("s1", "add one account axis with 400 balance", ro2, mem)
    print("Finance add one account:", r3.success, r3.output_text[:70] if r3.output_text else "")


if __name__ == "__main__":
    asyncio.run(test())
