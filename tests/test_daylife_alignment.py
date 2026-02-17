from pathlib import Path

from src.agent.intent_parser import IntentParser
from src.agent.tools.finance_tool import FinanceTool
from src.agent.tools.memory_tool import MemoryTool


def test_investment_suggestion_routes_to_decision():
    parser = IntentParser()
    out = parser.parse("suggest me an investment opportunity")
    assert out is not None
    assert out["tool"] == "decision"
    assert out["method"] == "evaluate"


def test_when_did_i_last_time_routes_to_memory_last_time():
    parser = IntentParser()
    out = parser.parse("when did i ate pizza last time")
    assert out is not None
    assert out["tool"] == "memory"
    assert out["method"] == "last_time"


def test_memory_last_time_returns_timestamped_answer(tmp_path: Path):
    tool = MemoryTool(tmp_path)
    tool.execute("remember", {"text": "i like pizza"})
    res = tool.execute("last_time", {"query": "when did i ate pizza last time"})
    assert res.success
    assert "Last time I saw this in memory:" in res.message


def test_expense_without_account_uses_richest_account_when_default_insufficient(tmp_path: Path):
    tool = FinanceTool(tmp_path)
    tool.execute("income", {"amount": 1000, "category": "salary", "account": "sbi"})
    tool.execute("expense", {"amount": 200, "category": "food"})

    accounts = {a["name"]: a["balance"] for a in tool.accounts.list(limit=50)}
    assert accounts["default"] == 0
    assert accounts["sbi"] == 800
