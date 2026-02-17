from pathlib import Path

from src.agent.intent_parser import IntentParser
from src.agent.orchestrator import Orchestrator
from src.agent.tools.finance_tool import FinanceTool


def test_delete_account_parsing_variants():
    parser = IntentParser()
    for q in ["delete abi", "remove abi", "delete abi account", "remove account abi"]:
        out = parser.parse(q)
        assert out is not None
        assert out["tool"] == "finance"
        assert out["method"] == "delete_account"
        assert out["params"]["name"] == "abi"


def test_unknown_account_name_suggests_close_match(tmp_path: Path):
    tool = FinanceTool(tmp_path)
    tool.execute("add_account", {"name": "sbi", "opening_balance": 0})

    res = tool.execute("income", {"amount": 2500, "category": "topup", "account": "abi"})
    assert res.success is False
    assert "Did you mean 'sbi'" in res.message


def test_friend_list_routes_to_relation_list():
    parser = IntentParser()
    for q in ["show friend list", "who are in my current frient data"]:
        out = parser.parse(q)
        assert out is not None
        assert out["tool"] == "relation"
        assert out["method"] == "list"


def test_delete_flow_works_end_to_end(tmp_path: Path):
    orch = Orchestrator(tmp_path)
    assert "Income" in orch.process("add 2500 to abi")
    assert "abi" in orch.process("show account")
    resp = orch.process("delete abi")
    assert "Deleted account" in resp
    assert "abi" not in orch.process("show accounts")


def test_typo_set_default_balance_routing():
    parser = IntentParser()
    out = parser.parse("set defalut banace to 0")
    assert out is not None
    assert out["tool"] == "finance"
    assert out["method"] == "update_account_balance"
    assert out["params"]["name"] == "default"

