from pathlib import Path

from src.agent.conversation_manager import ConversationManager
from src.agent.intent_parser import IntentParser
from src.agent.tools.finance_tool import FinanceTool


def test_conversation_manager_migrates_legacy_turns_schema(tmp_path: Path):
    db_path = tmp_path / "chat_history.db"
    import sqlite3

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                user_input TEXT,
                assistant_response TEXT,
                intent TEXT,
                entities TEXT
            )
            """
        )
        conn.commit()

    mgr = ConversationManager(data_dir=tmp_path)
    mgr.add_turn("hello", "hi", intent="free_chat", entities={"name": "user"}, source="voice")

    with sqlite3.connect(db_path) as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(turns)").fetchall()]
        assert "sentiment_valence" in cols
        assert "sentiment_arousal" in cols
        assert "sentiment_label" in cols
        assert "source" in cols
        assert "topic" in cols


def test_parser_supports_account_topup_phrasing():
    parser = IntentParser()

    one = parser.parse("add 35000 in sbi")
    assert one is not None
    assert one["tool"] == "finance"
    assert one["method"] == "income"
    assert one["params"]["account"] == "sbi"

    multi = parser.parse("add 400 to axis and 25000 to sbi")
    assert multi is not None
    assert multi["tool"] == "finance"
    assert multi["method"] == "bulk_topup"
    assert len(multi["params"]["entries"]) == 2


def test_finance_bulk_topup_autocreates_accounts(tmp_path: Path):
    tool = FinanceTool(tmp_path)

    result = tool.execute(
        "bulk_topup",
        {"entries": [{"amount": 400, "account": "axis"}, {"amount": 25000, "account": "sbi"}]},
    )

    assert result.success

    accounts = {a["name"]: a["balance"] for a in tool.accounts.list(limit=10)}
    assert accounts["axis"] == 400
    assert accounts["sbi"] == 25000
