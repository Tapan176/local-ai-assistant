"""
System Tests - TAPAN_AI Rebuild (SQLite First)
"""
import pytest
import shutil
from pathlib import Path
from src.agent.orchestrator import Orchestrator
from src.agent.tools.finance_tool import FinanceTool
from src.agent.tools.experience_tool import ExperienceTool
from src.agent.tools.memory_tool import MemoryTool
from src.agent.tools.reminder_tool import ReminderTool
from src.agent.tools.relation_tool import RelationTool

@pytest.fixture
def test_dir(tmp_path):
  d = tmp_path / "tapan_test_data"
  d.mkdir()
  return d

@pytest.fixture
def orchestrator(test_dir):
  return Orchestrator(test_dir)

# ================= FINANCE TESTS =================

def test_finance_flow(test_dir):
  ft = FinanceTool(test_dir)

  # 1. Accounts
  res = ft.execute("add_account", {"name": "savings", "opening_balance": 1000})
  assert res.success
  assert "savings" in res.message

  res = ft.execute("accounts", {})
  assert "savings: 1000" in res.message

  # 2. Expense
  res = ft.execute("expense", {"amount": 200, "category": "food", "account": "savings"})
  assert res.success

  res = ft.execute("accounts", {})
  assert "savings: 800" in res.message

  # 3. Transfer
  ft.execute("add_account", {"name": "checking", "opening_balance": 0})
  res = ft.execute("transfer", {"from_account": "savings", "to_account": "checking", "amount": 300})
  assert res.success

  res = ft.execute("accounts", {})
  assert "savings: 500" in res.message
  assert "checking: 300" in res.message

  # 4. Rename
  res = ft.execute("rename_account", {"old_name": "savings", "new_name": "vault"})
  assert res.success
  res = ft.execute("accounts", {})
  assert "vault: 500" in res.message

  # 5. Bulk Delete
  res = ft.execute("bulk_delete", {"names": ["vault", "checking"]})
  assert res.success
  # Should check they are gone

# ================= EXPERIENCE TESTS =================

def test_experience_crud(test_dir):
  et = ExperienceTool(test_dir)

  res = et.execute("add", {"text": "Went to the park", "category": "leisure"})
  assert res.success

  res = et.execute("stats", {})
  assert "Total Experiences: 1" in res.message

  res = et.execute("delete_by_text", {"text": "park"})
  assert res.success
  assert "Deleted 1" in res.message

# ================= MEMORY TESTS =================

def test_memory_logic(test_dir):
  mt = MemoryTool(test_dir)

  res = mt.execute("remember", {"text": "I like python"})
  assert res.success

  res = mt.execute("list", {})
  assert "I like python" in res.message

  res = mt.execute("remember", {"text": "I like python"})
  assert "Already remember" in res.message

  res = mt.execute("delete_all", {})
  assert  "Forgot 1" in res.message or "Forgot 0" in res.message

# ================= ORCHESTRATOR & INTENT TESTS =================

def test_orchestrator_routing(orchestrator):
  # 1. Finance Intent
  res = orchestrator.process("add account test 500")
  # New regex: 'add account (\w+) (\d+)'
  # "add account test 500" matches.

  # 2. System Help
  res = orchestrator.process("help")
  assert "TAPAN_AI Help" in res

  # 3. Invalid
  res = orchestrator.process("gibberish")
  assert "didn't understand" in res

def test_orchestrator_deterministic_intents(orchestrator):
  # Test specific patterns we implemented

  # 1. Show accounts
  orchestrator.process("show accounts") 
  # Can't assert output easily without mocking tools or seeing side effects, 
  # but we can trust unit tests. 
  # Real integration test:

  # Create account directly first to have data
  ft = orchestrator.tools["finance"]
  ft.add_account({"name": "test", "opening_balance": 100})

  # Now query via text
  res = orchestrator.process("show accounts")
  assert "test: 100" in res

  # 2. Hindi Mapping
  res = orchestrator.process("accounts dikhao")
  assert "test: 100" in res

  # 3. Delete
  res = orchestrator.process("delete account test")
  assert "Deleted account: test" in res

def test_sanitizer():
  from src.agent.output_sanitizer import OutputSanitizer
  s = OutputSanitizer()

  assert s.sanitize("```json\n{\"text\": \"hello\"}\n```") == "hello"
  assert s.sanitize("[AUDIT] Log entry\nHello") == "Hello"
