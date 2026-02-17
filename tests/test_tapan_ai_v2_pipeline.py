import asyncio
from pathlib import Path

from tapan_ai.config.settings import Settings
from tapan_ai.main import build_runtime


def _runtime(tmp_path: Path):
    settings = Settings(
        llm_provider="mock",
        sqlite_path=str(tmp_path / "tapan_ai_v2_test.db"),
        chroma_path=str(tmp_path / "chroma"),
        max_memory_items=6,
        stream_chunk_size=12,
    )
    return asyncio.run(build_runtime(settings=settings))


def _ask(runtime, session_id: str, text: str):
    return asyncio.run(runtime.orchestrator.handle_user_input(session_id=session_id, user_text=text))


def test_casual_chat_no_system_leakage(tmp_path: Path):
    runtime = _runtime(tmp_path)
    res = _ask(runtime, "casual", "bro kya hal chal")
    assert res.action_type in {"respond", "clarify", "tool"}
    assert "system prompt" not in res.text.lower()
    assert "internal architecture" not in res.text.lower()


def test_financial_update_and_balance_query(tmp_path: Path):
    runtime = _runtime(tmp_path)
    res1 = _ask(runtime, "finance", "add 400 to axis account")
    assert res1.tool_used == "finance_tool"
    assert "axis" in res1.text.lower()

    res2 = _ask(runtime, "finance", "what is my balance in axis account")
    assert res2.tool_used == "finance_tool"
    assert "balance" in res2.text.lower()
    assert "400" in res2.text


def test_emotional_support_flow(tmp_path: Path):
    runtime = _runtime(tmp_path)
    res = _ask(runtime, "emotion", "I am feeling stressed and overwhelmed today")
    assert res.emotional_state in {"stressed", "sad", "neutral", "positive"}
    assert "system" not in res.text.lower()


def test_ambiguous_input_triggers_clarification(tmp_path: Path):
    runtime = _runtime(tmp_path)
    res = _ask(runtime, "ambiguous", "do it")
    assert res.action_type == "clarify"
    assert "?" in res.text


def test_long_conversation_continuity_name_recall(tmp_path: Path):
    runtime = _runtime(tmp_path)
    _ask(runtime, "continuity", "my name is Arjun")
    res = _ask(runtime, "continuity", "what is my name")
    assert "arjun" in res.text.lower()


def test_topic_switching_across_tools(tmp_path: Path):
    runtime = _runtime(tmp_path)
    res1 = _ask(runtime, "switch", "add 2500 to primary account")
    res2 = _ask(runtime, "switch", "remind me to pay internet bill tomorrow at 9 am")
    res3 = _ask(runtime, "switch", "schedule product sync meeting tomorrow at 5 pm")
    res4 = _ask(runtime, "switch", "I feel a bit anxious about deadlines")

    assert res1.tool_used == "finance_tool"
    assert res2.tool_used == "reminder_tool"
    assert res3.tool_used == "calendar_tool"
    assert res4.action_type in {"respond", "clarify"}


def test_people_memory_followup(tmp_path: Path):
    runtime = _runtime(tmp_path)
    res1 = _ask(runtime, "people", "Ravi is my manager")
    res2 = _ask(runtime, "people", "who is Ravi")
    assert res1.tool_used == "people_tool"
    assert res2.tool_used == "people_tool"
    assert "manager" in res2.text.lower()

