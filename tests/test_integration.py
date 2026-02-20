"""Quick bug-finder: tests core components and writes results to JSON."""
from __future__ import annotations

import asyncio
import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

RESULTS: dict[str, dict] = {}


def record(comp: str, test: str, passed: bool, detail: str = ""):
    RESULTS[f"{comp}::{test}"] = {"passed": passed, "detail": detail}


async def main():
    from src.config.settings import Settings

    settings = Settings.from_env()
    settings.llm_provider = "mock"

    # ── 1. SQLiteStore ──
    from src.storage.sqlite_store import SQLiteStore

    store = SQLiteStore(":memory:")
    try:
        await store.initialize()
        record("SQLiteStore", "initialize", True)
    except Exception as e:
        record("SQLiteStore", "initialize", False, str(e))
        _dump()
        return

    # check what tables exist
    try:
        tables = await store.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tbl_names = [r["name"] for r in tables]
        record("SQLiteStore", "schema_tables", True, str(tbl_names))
    except Exception as e:
        record("SQLiteStore", "schema_tables", False, str(e))

    # ── 2. VectorStore ──
    from src.storage.vector_store import create_vector_store

    try:
        vs = create_vector_store(settings)
        record("VectorStore", "create", True, type(vs).__name__)
    except Exception as e:
        record("VectorStore", "create", False, str(e))

    try:
        vs2 = create_vector_store(settings)
        await vs2.upsert("d1", "hello world", {"src": "test"})
        record("VectorStore", "upsert", True)
    except Exception as e:
        record("VectorStore", "upsert", False, str(e))

    try:
        res = await vs2.query("world", limit=2)
        record("VectorStore", "query", True, f"count={len(res)}")
    except Exception as e:
        record("VectorStore", "query", False, str(e))

    # ── 3. GraphStore ──
    from src.storage.graph_store import GraphStore

    graph = GraphStore(store)
    try:
        await graph.add_relationship("user", "Tapan", "self")
        record("GraphStore", "add_relationship", True)
    except Exception as e:
        record("GraphStore", "add_relationship", False, str(e))

    try:
        related = await graph.find_related("user")
        record("GraphStore", "find_related", True, f"count={len(related)}")
    except Exception as e:
        record("GraphStore", "find_related", False, str(e))

    # ── 4. EpisodicMemory ──
    from src.memory.episodic_memory import EpisodicMemory

    ep = EpisodicMemory(store)
    try:
        from src.models import ConversationTurn
        turn = ConversationTurn(
            session_id="sess1", user_text="hi", assistant_text="hello",
            emotional_state="neutral", tool_used=None, metadata={}
        )
        await ep.add_turn(turn)
        record("EpisodicMemory", "add_turn", True)
    except Exception as e:
        record("EpisodicMemory", "add_turn", False, str(e))

    try:
        turns = await ep.recent("sess1", limit=5)
        record("EpisodicMemory", "recent", True, f"count={len(turns)}")
    except Exception as e:
        record("EpisodicMemory", "recent", False, str(e))

    # ── 5. SemanticMemory ──
    from src.memory.semantic_memory import SemanticMemory

    sem = SemanticMemory(store, vs2)
    try:
        await sem.upsert_fact("user_name", "Tapan")
        record("SemanticMemory", "upsert_fact", True)
    except Exception as e:
        record("SemanticMemory", "upsert_fact", False, str(e))

    try:
        await sem.remember_text("doc1", "I like AI")
        record("SemanticMemory", "remember_text", True)
    except Exception as e:
        record("SemanticMemory", "remember_text", False, str(e))

    try:
        facts = await sem.retrieve("Tapan", limit=3)
        record("SemanticMemory", "retrieve", True, f"count={len(facts)}")
    except Exception as e:
        record("SemanticMemory", "retrieve", False, str(e))

    # ── 6. PersonaMemory ──
    from src.memory.persona_memory import PersonaMemory

    pm = PersonaMemory(store)
    try:
        profile = await pm.get_profile()
        record("PersonaMemory", "get_profile", True, str(list(profile.keys())))
    except Exception as e:
        record("PersonaMemory", "get_profile", False, str(e))

    try:
        await pm.update_profile(communication_style="warm")
        record("PersonaMemory", "update_profile", True)
    except Exception as e:
        record("PersonaMemory", "update_profile", False, str(e))

    try:
        await pm.learn_from_text("My name is Tapan and I love coding")
        record("PersonaMemory", "learn_from_text", True)
    except Exception as e:
        record("PersonaMemory", "learn_from_text", False, str(e))

    # ── 7. EmotionalEngine ──
    from src.core.emotional_engine import EmotionalEngine

    emo = EmotionalEngine()
    for text, expected in [
        ("I am happy", "positive"),
        ("I feel sad", "negative"),
        ("so stressed", "stressed"),
        ("what time", "neutral"),
    ]:
        try:
            r = await emo.analyze(text)
            record("EmotionalEngine", f"{expected}", r.state == expected,
                   f"expected={expected}, got={r.state}, intensity={r.intensity:.2f}")
        except Exception as e:
            record("EmotionalEngine", f"{expected}", False, str(e))

    # ── 8. PerceptionEngine ──
    from src.core.perception_engine import PerceptionEngine

    pe = PerceptionEngine(emo)
    for text in ["add 500 to savings", "hi", "I'm stressed", "remind me tomorrow"]:
        try:
            p = await pe.perceive(text)
            record("PerceptionEngine", text[:25],
                   True,
                   f"tone={p.tone}, emotion={p.emotional_state}, entities={p.entities}")
        except Exception as e:
            record("PerceptionEngine", text[:25], False, traceback.format_exc()[-300:])

    # ── 9. LLMDispatcher (mock) ──
    from src.llm.llm_dispatcher import LLMDispatcher

    llm = LLMDispatcher(settings)
    try:
        r = await llm.generate_text(system="You are Tapan AI.", context="", user="hello", temperature=0.5)
        record("LLMDispatcher", "generate_text_basic", True, f"len={len(r)}")
    except Exception as e:
        record("LLMDispatcher", "generate_text_basic", False, str(e))

    try:
        payload = {"user_text": "add 500", "perception": {"tone": "neutral"}, "memory": {}}
        r = await llm.infer_reasoning(payload)
        record("LLMDispatcher", "infer_reasoning", True, f"intent={r.get('inferred_intent')}")
    except Exception as e:
        record("LLMDispatcher", "infer_reasoning", False, str(e))

    # ── 10. ReasoningEngine ──
    from src.core.reasoning_engine import ReasoningEngine
    from src.models import MemoryContext, PerceptionOutput

    re_engine = ReasoningEngine(llm)
    try:
        mock_p = PerceptionOutput(
            tone="neutral", ambiguity_score=0.1, entities=["savings"],
            emotional_state="neutral", emotional_intensity=0.2, detected_language="en",
        )
        mock_m = MemoryContext(
            episodic_memories=[], semantic_memories=[], persona_profile={}, relationship_graph=[],
        )
        r = await re_engine.reason("add 500 to savings", mock_p, mock_m)
        record("ReasoningEngine", "reason", True,
               f"intent={r.inferred_intent}, conf={r.confidence:.2f}")
    except Exception as e:
        record("ReasoningEngine", "reason", False, traceback.format_exc()[-300:])

    # ── 11. PlanningEngine ──
    from src.core.planning_engine import PlanningEngine
    from src.models import ReasoningOutput

    planner = PlanningEngine()
    try:
        mock_ro = ReasoningOutput(
            inferred_intent="financial_update", confidence=0.9, needs_clarification=False,
            possible_actions=["finance_tool"], tool_candidates=["finance_tool"],
            uncertainty=0.1, rationale="user wants finance"
        )
        mock_p2 = PerceptionOutput(
            tone="neutral", ambiguity_score=0.1, entities=["savings"],
            emotional_state="neutral", emotional_intensity=0.2, detected_language="en",
        )
        mock_m2_plan = MemoryContext(
            episodic_memories=[], semantic_memories=[], persona_profile={}, relationship_graph=[],
        )
        plan = await planner.plan("add 500", mock_ro, mock_p2, mock_m2_plan)
        record("PlanningEngine", "plan_tool", True,
               f"action={plan.action_type}, tool={plan.tool_name}")
    except Exception as e:
        record("PlanningEngine", "plan_tool", False, traceback.format_exc()[-300:])

    # ── 12. FinanceTool ──
    from src.tools.finance_tool import FinanceTool

    ft = FinanceTool(store)
    mock_ro_fin = ReasoningOutput(
        inferred_intent="financial_update", confidence=0.9, needs_clarification=False,
        possible_actions=[], tool_candidates=[], uncertainty=0.1, rationale=""
    )
    mock_m2 = MemoryContext(episodic_memories=[], semantic_memories=[], persona_profile={}, relationship_graph=[])
    for text, desc in [
        ("create account savings with 10000", "create_account"),
        ("add 500 to savings", "credit"),
        ("spent 200 from savings", "debit"),
        ("show balance", "balance"),
        ("show accounts", "list"),
        ("transfer 100 from savings to wallet", "transfer"),
        ("transaction history", "history"),
    ]:
        try:
            res = await ft.execute("test", text, mock_ro_fin, mock_m2)
            record("FinanceTool", desc, res.success, res.output_text[:80])
        except Exception as e:
            record("FinanceTool", desc, False, traceback.format_exc()[-300:])

    # ── 13. ReminderTool ──
    from src.tools.reminder_tool import ReminderTool

    rt = ReminderTool(store)
    for text, desc in [
        ("remind me to call mom tomorrow at 5 pm", "create"),
        ("show reminders", "list"),
    ]:
        try:
            res = await rt.execute("test", text, mock_ro_fin, mock_m2)
            record("ReminderTool", desc, res.success, res.output_text[:80])
        except Exception as e:
            record("ReminderTool", desc, False, traceback.format_exc()[-300:])

    # ── 14. CalendarTool ──
    from src.tools.calendar_tool import CalendarTool

    ct = CalendarTool(store)
    for text, desc in [
        ("schedule meeting tomorrow at 10 am", "create"),
        ("upcoming events", "list"),
    ]:
        try:
            res = await ct.execute("test", text, mock_ro_fin, mock_m2)
            record("CalendarTool", desc, res.success, res.output_text[:80])
        except Exception as e:
            record("CalendarTool", desc, False, traceback.format_exc()[-300:])

    # ── 15. PeopleTool ──
    from src.tools.people_tool import PeopleTool

    pp = PeopleTool(store, graph)
    for text, desc in [
        ("Rahul is my friend", "save"),
        ("who is Rahul", "query"),
        ("list people", "list"),
    ]:
        try:
            res = await pp.execute("test", text, mock_ro_fin, mock_m2)
            record("PeopleTool", desc, res.success, res.output_text[:80])
        except Exception as e:
            record("PeopleTool", desc, False, traceback.format_exc()[-300:])

    # ── 16. OutputSanitizer ──
    from src.core.output_sanitizer import OutputSanitizer

    san = OutputSanitizer()
    try:
        r = san.sanitize('{"response": "Hello"}')
        record("OutputSanitizer", "json_extract", r == "Hello", f"got={r}")
    except Exception as e:
        record("OutputSanitizer", "json_extract", False, str(e))

    try:
        r = san.sanitize("system prompt data leaked")
        record("OutputSanitizer", "leak_scrub", "system prompt" not in r.lower(), f"got={r}")
    except Exception as e:
        record("OutputSanitizer", "leak_scrub", False, str(e))

    try:
        r = san.sanitize("I want coffee", user_text="I want coffee")
        record("OutputSanitizer", "echo_detect", "coffee" not in r.lower(), f"got={r}")
    except Exception as e:
        record("OutputSanitizer", "echo_detect", False, str(e))

    # ── 17. DateTimeParser ──
    from src.utils.date_time_parser import RelativeDateTimeParser

    dtp = RelativeDateTimeParser()
    for text, should_parse in [("tomorrow at 5 pm", True), ("random text", False)]:
        try:
            r, parsed = dtp.parse(text)
            ok = (r is not None) == should_parse
            record("DateTimeParser", text[:20], ok, f"result={r}")
        except Exception as e:
            record("DateTimeParser", text[:20], False, str(e))

    # ── 18. Full pipeline ──
    try:
        from src.main import build_runtime

        mock_settings = Settings.from_env()
        mock_settings.llm_provider = "mock"
        mock_settings.sqlite_path = ":memory:"
        runtime = await build_runtime(settings=mock_settings)
        record("Orchestrator", "build_runtime", True)
    except Exception as e:
        record("Orchestrator", "build_runtime", False, traceback.format_exc()[-300:])
        _dump()
        return

    for text in [
        "Hello how are you",
        "My name is Tapan",
        "Add 5000 to savings account",
        "Show my balance",
        "I feel stressed today",
        "Remind me to call mom tomorrow at 5 pm",
        "Schedule meeting monday 10 am",
        "Who is Rahul",
        "yes",
        "Thank you",
    ]:
        try:
            resp = await runtime.orchestrator.handle_user_input("test-sess", text)
            ok = resp is not None and len(resp.text) > 0
            record("Orchestrator", f"pipeline:{text[:30]}", ok,
                   f"action={resp.action_type}, tool={resp.tool_used}, text={resp.text[:60]}")
        except Exception as e:
            record("Orchestrator", f"pipeline:{text[:30]}", False, traceback.format_exc()[-300:])

    _dump()


def _dump():
    with open("tests/results.json", "w", encoding="utf-8") as f:
        json.dump(RESULTS, f, indent=2, ensure_ascii=False)
    total = len(RESULTS)
    passed = sum(1 for v in RESULTS.values() if v["passed"])
    failed = total - passed
    print(f"Results written to tests/results.json | TOTAL={total} PASSED={passed} FAILED={failed}")


if __name__ == "__main__":
    asyncio.run(main())
