import sqlite3
from pathlib import Path

import pytest

from src.agent.orchestrator import Orchestrator
from src.agent.tools.finance_tool import FinanceTool
from src.memory.cognee_brain import RecallResult
from src.memory.recall_guard import NO_RECORD_TEXT, RecallGuard


def _db_count(path: Path, table: str) -> int:
  if not path.exists():
    return 0
  conn = sqlite3.connect(path)
  cur = conn.cursor()
  cur.execute(f"SELECT COUNT(*) FROM {table}")
  count = int(cur.fetchone()[0] or 0)
  conn.close()
  return count


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
  return tmp_path


@pytest.fixture()
def finance_tool(data_dir: Path) -> FinanceTool:
  return FinanceTool(data_dir)


@pytest.fixture()
def orchestrator(data_dir: Path) -> Orchestrator:
  return Orchestrator(data_dir)


# ==================================================
# A) FINANCE (15)
# ==================================================
def test_finance_01_delete_single(finance_tool: FinanceTool):
  finance_tool.execute("add_account", {"name": "savings", "opening_balance": 1000})
  res = finance_tool.execute("delete_account", {"name": "savings"})
  assert res.success
  assert "deleted account" in res.message.lower()


def test_finance_02_delete_multiple(finance_tool: FinanceTool):
  finance_tool.execute("add_account", {"name": "savings", "opening_balance": 100})
  finance_tool.execute("add_account", {"name": "icici", "opening_balance": 100})
  finance_tool.execute("add_account", {"name": "new_acc", "opening_balance": 100})
  res = finance_tool.execute("bulk_delete", {"names": ["savings", "icici", "new_acc"]})
  assert res.success
  assert "deleted accounts" in res.message.lower()


def test_finance_03_rename(finance_tool: FinanceTool):
  finance_tool.execute("add_account", {"name": "old_acc", "opening_balance": 500})
  res = finance_tool.execute("rename_account", {"old_name": "old_acc", "new_name": "renamed_acc"})
  assert res.success
  listed = finance_tool.execute("accounts", {}).message.lower()
  assert "renamed_acc" in listed
  assert "old_acc" not in listed


def test_finance_04_list_alias(finance_tool: FinanceTool):
  finance_tool.execute("add_account", {"name": "wallet", "opening_balance": 200})
  res = finance_tool.execute("list", {})
  assert res.success
  assert "wallet" in res.message.lower()


def test_finance_05_balance_correct(finance_tool: FinanceTool):
  finance_tool.execute("add_account", {"name": "main", "opening_balance": 1000})
  finance_tool.execute("expense", {"amount": 100, "category": "food", "account": "main"})
  finance_tool.execute("income", {"amount": 50, "category": "bonus", "account": "main"})
  res = finance_tool.execute("balance", {})
  assert "950" in res.message


@pytest.mark.parametrize(
  "names",
  [
    ["a1", "a2"],
    ["acc_one", "acc_two", "acc_three"],
    ["icici", "hdfc", "kotak"],
    ["u1", "u2", "u3", "u4"],
    ["x", "y"],
  ],
)
def test_finance_06_to_10_bulk_delete_variants(finance_tool: FinanceTool, names):
  for name in names:
    finance_tool.execute("add_account", {"name": name, "opening_balance": 100})
  res = finance_tool.execute("bulk_delete", {"names": names})
  assert res.success
  listed = finance_tool.execute("accounts", {}).message.lower()
  for name in names:
    assert name.lower() not in listed


@pytest.mark.parametrize(
  "old_name,new_name",
  [
    ("r1", "r1_new"),
    ("r2", "r2_new"),
    ("r3", "r3_new"),
    ("r4", "r4_new"),
    ("r5", "r5_new"),
  ],
)
def test_finance_11_to_15_rename_variants(finance_tool: FinanceTool, old_name: str, new_name: str):
  finance_tool.execute("add_account", {"name": old_name, "opening_balance": 1})
  res = finance_tool.execute("rename_account", {"old_name": old_name, "new_name": new_name})
  assert res.success


# ==================================================
# B) SANITIZATION (15)
# ==================================================
@pytest.mark.parametrize(
  "raw,expected_contains",
  [
    ('{"response":"hello"}', "hello"),
    ('```json\n{"message":"ok"}\n```', "ok"),
    ("[AUDIT] finance.accounts", ""),
    ('{"action":"finance","method":"balance"}', ""),
    ("{ action: test }", ""),
  ],
)
def test_sanitizer_01_to_05(raw: str, expected_contains: str):
  clean = Orchestrator._sanitize_output(raw)
  assert "AUDIT" not in clean
  assert "action" not in clean.lower()
  assert "{" not in clean and "}" not in clean
  if expected_contains:
    assert expected_contains in clean


@pytest.mark.parametrize(
  "raw",
  [
    "```json\n{\"response\":\"x\"}\n```",
    "[AUDIT] relation.delete_by_text",
    "{\"tool\":\"reminder\"}",
    "{{{{broken}}}}",
    "normal text",
  ],
)
def test_sanitizer_06_to_10_plain_text(raw: str):
  clean = Orchestrator._sanitize_output(raw)
  assert "```" not in clean
  assert "[AUDIT]" not in clean
  assert "{" not in clean and "}" not in clean


@pytest.mark.parametrize(
  "raw",
  [
    '{"text":"done"}',
    '{"response":"[AUDIT] hidden"}',
    '{"message":"{ action: x }"}',
    "[AUDIT]\n{\"action\":\"x\"}",
    "result } } }",
  ],
)
def test_sanitizer_11_to_15_strips_braces(raw: str):
  clean = Orchestrator._sanitize_output(raw)
  assert "{" not in clean
  assert "}" not in clean
  assert "[AUDIT]" not in clean


# ==================================================
# C) DOMAIN SEPARATION (10)
# ==================================================
def test_domain_01_memory_only(orchestrator: Orchestrator, data_dir: Path):
  orchestrator.process_single("I like tea")
  assert _db_count(data_dir / "memories.db", "memories") >= 1
  assert _db_count(data_dir / "reminders.db", "reminders") == 0


def test_domain_02_reminder_only(orchestrator: Orchestrator, data_dir: Path):
  orchestrator.process_single("remind me to call mom tomorrow")
  assert _db_count(data_dir / "reminders.db", "reminders") >= 1


def test_domain_03_experience_only(orchestrator: Orchestrator, data_dir: Path):
  orchestrator.process_single("today I went bowling")
  assert _db_count(data_dir / "experiences.db", "experiences") >= 1


@pytest.mark.parametrize(
  "text,table",
  [
    ("remember I prefer coffee", "memories"),
    ("my favorite food is dosa", "memories"),
    ("remind me about passport next week", "reminders"),
    ("yesterday I watched a movie", "experiences"),
    ("my friend Rahul", "relations"),
    ("my colleague Priya", "relations"),
    ("add habit running", "habits"),
  ],
)
def test_domain_04_to_10_routing(orchestrator: Orchestrator, data_dir: Path, text: str, table: str):
  orchestrator.process_single(text)
  db_map = {
    "memories": data_dir / "memories.db",
    "reminders": data_dir / "reminders.db",
    "experiences": data_dir / "experiences.db",
    "relations": data_dir / "relations.db",
    "habits": data_dir / "habits.db",
  }
  assert _db_count(db_map[table], table) >= 1


# ==================================================
# D) COGNEE GROUNDING (10)
# ==================================================
class _DummyBrain:
  def __init__(self, data_dir: Path, recall_results=None, multi_results=None):
    self._brain = type("B", (), {"data_dir": data_dir})()
    self._recall = recall_results or []
    self._multi = multi_results or []

  def recall(self, query: str, domain: str = None, **kwargs):
    return self._recall

  def multi_hop_query(self, query: str):
    return self._multi


def test_grounding_01_empty_sqlite_returns_no_record(data_dir: Path):
  brain = _DummyBrain(
    data_dir,
    recall_results=[
      RecallResult(
        text="I think you like sushi",
        node_id="n1",
        node_type="Memory",
        confidence=0.9,
        source="cognee",
        timestamp="",
      )
    ],
  )
  guard = RecallGuard(brain)
  result = guard.recall_memory("sushi")
  assert result.text == NO_RECORD_TEXT


def test_grounding_02_no_maybe_phrase(data_dir: Path):
  brain = _DummyBrain(data_dir, recall_results=[])
  guard = RecallGuard(brain)
  result = guard.recall_memory("anything")
  assert result.text == NO_RECORD_TEXT
  assert "maybe" not in result.text.lower()


def test_grounding_03_no_probably_phrase(data_dir: Path):
  brain = _DummyBrain(data_dir, recall_results=[])
  guard = RecallGuard(brain)
  result = guard.recall_with_guard("x", domain="memory")
  assert result.text == NO_RECORD_TEXT
  assert "probably" not in result.text.lower()


def test_grounding_04_no_i_think_phrase(data_dir: Path):
  brain = _DummyBrain(data_dir, recall_results=[])
  guard = RecallGuard(brain)
  result = guard.multi_hop_with_guard("x")
  assert result.text == NO_RECORD_TEXT
  assert "i think" not in result.text.lower()


@pytest.mark.parametrize("query", ["q1", "q2", "q3", "q4", "q5", "q6"])
def test_grounding_05_to_10_all_empty_return_no_record(data_dir: Path, query: str):
  brain = _DummyBrain(data_dir, recall_results=[], multi_results=[])
  guard = RecallGuard(brain)
  result = guard.recall_with_guard(query, domain="memory")
  assert result.text == NO_RECORD_TEXT


# ==================================================
# E) CLI PARSING (10)
# ==================================================
def test_cli_01_remove_savings_account(orchestrator: Orchestrator):
  orchestrator.process("add account savings 100")
  out = orchestrator.process("remove savings account")
  assert "deleted account" in out.lower() or "deleted accounts" in out.lower()


def test_cli_02_delete_accounts_comma(orchestrator: Orchestrator):
  orchestrator.process("add account savings 100")
  orchestrator.process("add account icici 100")
  orchestrator.process("add account new_acc 100")
  out = orchestrator.process("delete accounts savings, icici, new_acc")
  assert "deleted accounts" in out.lower()
  assert "savings" in out.lower() and "icici" in out.lower() and "new_acc" in out.lower()


def test_cli_03_delete_accounts_and(orchestrator: Orchestrator):
  orchestrator.process("add account s1 100")
  orchestrator.process("add account s2 100")
  out = orchestrator.process("delete accounts s1 and s2")
  assert "deleted accounts" in out.lower()


def test_cli_04_plain_list_delete(orchestrator: Orchestrator):
  orchestrator.process("add account a1 100")
  orchestrator.process("add account a2 100")
  out = orchestrator.process("a1, a2")
  assert "deleted accounts" in out.lower()


def test_cli_05_show_accounts_reflects_change(orchestrator: Orchestrator):
  orchestrator.process("add account keep_me 100")
  orchestrator.process("add account remove_me 100")
  orchestrator.process("delete account remove_me")
  out = orchestrator.process("show accounts")
  assert "remove_me" not in out.lower()
  assert "keep_me" in out.lower()


@pytest.mark.parametrize(
  "text",
  [
    "delete account aa1",
    "remove account aa2",
    "delete accounts aa3, aa4",
    "aa5, aa6",
    "delete accounts aa7 and aa8",
  ],
)
def test_cli_06_to_10_parser_variants(orchestrator: Orchestrator, text: str):
  for name in ["aa1", "aa2", "aa3", "aa4", "aa5", "aa6", "aa7", "aa8"]:
    orchestrator.process(f"add account {name} 100")
  out = orchestrator.process(text)
  assert "unknown action" not in out.lower()
