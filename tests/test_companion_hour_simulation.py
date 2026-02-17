from pathlib import Path
import sqlite3

from src.agent.orchestrator import Orchestrator


def _count_rows(db_path: Path, table: str) -> int:
    with sqlite3.connect(db_path) as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_accelerated_hour_like_companion_usage(tmp_path: Path):
    orch = Orchestrator(tmp_path)

    morning_flow = [
        "good morning",
        "daily plan",
        "remind me to drink water every 2 hours",
        "remind me to call mom at 8 pm",
        "show reminders",
        "add 50000 to salary and 10000 to savings",
        "expense 300 breakfast",
        "expense 1200 groceries",
        "show accounts",
        "remember I prefer black coffee",
        "remember my standup is at 10 am daily",
        "list memories",
        "should i buy iphone for 70000",
        "suggest me an investment opportunity",
        "when did i prefer black coffee last time",
    ]

    work_flow = [
        "log worked on project alpha planning",
        "log completed backend API integration",
        "log joined sprint review meeting",
        "show experiences",
        "ask summarize my week",
        "profile",
        "suggestions",
    ]

    evening_flow = [
        "expense 500 dinner",
        "expense 200 transport",
        "show accounts",
        "show reminders",
        "session",
        "list memories",
        "when did i standup last time",
    ]

    outputs = []
    for turn in morning_flow + work_flow + evening_flow:
        outputs.append((turn, orch.process(turn)))

    # Simulate mixed voice and text through same session
    for i in range(40):
        source = "voice" if i % 2 == 0 else "text"
        resp = orch.process(f"log hourly checkin {i}", source=source)
        outputs.append((f"hourly-{i}", resp))

    # Core behavior expectations
    out_dict = dict(outputs)
    assert "Decision:" in out_dict["should i buy iphone for 70000"] or "Hold off" in out_dict["should i buy iphone for 70000"]
    assert "Decision:" in out_dict["suggest me an investment opportunity"] or "Consider it carefully" in out_dict["suggest me an investment opportunity"]
    assert "Last time" in out_dict["when did i prefer black coffee last time"] or "couldn't find" in out_dict["when did i prefer black coffee last time"]

    # DB verification across domains
    assert _count_rows(tmp_path / "chat_history.db", "turns") >= 50
    assert _count_rows(tmp_path / "reminders.db", "reminders") >= 2
    assert _count_rows(tmp_path / "memories.db", "memories") >= 2
    assert _count_rows(tmp_path / "finance.db", "transactions") >= 4
    assert _count_rows(tmp_path / "experiences.db", "experiences") >= 10

    # Voice/text sync check in chat history
    with sqlite3.connect(tmp_path / "chat_history.db") as conn:
        voice_turns = conn.execute("SELECT COUNT(*) FROM turns WHERE source='voice'").fetchone()[0]
        text_turns = conn.execute("SELECT COUNT(*) FROM turns WHERE source='text'").fetchone()[0]
    assert voice_turns >= 10
    assert text_turns >= 10
