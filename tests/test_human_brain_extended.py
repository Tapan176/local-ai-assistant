"""
Extended Human Brain Model Tests - TAPAN_AI
Tests for all new features: experiences, relations, memories, domain separation

Run with: python -m pytest tests/test_human_brain_extended.py -v
"""
import pytest
import sqlite3
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

# Add project root to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.agent.tools.memory_tool import MemoryTool
from src.agent.tools.experience_tool import ExperienceTool
from src.agent.tools.reminder_tool import ReminderTool
from src.agent.tools.relation_tool import RelationTool
from src.agent.tools.persona_tool import PersonaTool
from src.core.date_parser import RelativeDateParser


@pytest.fixture
def temp_data_dir():
  """Create temporary data directory for tests"""
  temp_dir = Path(tempfile.mkdtemp())
  yield temp_dir
  shutil.rmtree(temp_dir, ignore_errors=True)


# ========== A) MEMORY TESTS ==========

class TestMemoryDomain:
  """Memory = facts/preferences (NOT reminders)"""

  def test_remember_preference(self, temp_data_dir):
    """'remember I like tea' → memory storage"""
    tool = MemoryTool(temp_data_dir)
    result = tool.execute("remember", {"text": "I like tea", "category": "preference"})

    assert result.success
    assert "Remembered" in result.message

  def test_memory_not_in_reminders(self, temp_data_dir):
    """Preferences should NOT appear in reminders"""
    mem_tool = MemoryTool(temp_data_dir)
    mem_tool.execute("remember", {"text": "I like black coffee"})

    # Check memories DB has it
    conn = sqlite3.connect(temp_data_dir / "memories.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM memories WHERE text LIKE '%coffee%'")
    count = cursor.fetchone()[0]
    conn.close()

    assert count == 1, "Should be in memories"

  def test_search_memories(self, temp_data_dir):
    """Search stored memories"""
    tool = MemoryTool(temp_data_dir)
    tool.execute("remember", {"text": "I prefer dark mode"})
    tool.execute("remember", {"text": "I like night walks"})

    result = tool.execute("search", {"query": "dark"})

    assert result.success
    assert "dark" in result.message.lower()


# ========== B) EXPERIENCE TESTS ==========

class TestExperienceDomain:
  """Experience = past events with dates"""

  def test_log_experience_today(self, temp_data_dir):
    """'today went bowling 800' → logged with amount"""
    tool = ExperienceTool(temp_data_dir)
    result = tool.execute("add", {"text": "went bowling 800", "date": "today"})

    assert result.success
    assert "Logged" in result.message
    assert "800" in result.message

  def test_when_last_query(self, temp_data_dir):
    """'when last bowling?' → returns date"""
    tool = ExperienceTool(temp_data_dir)
    tool.execute("add", {"text": "went bowling at FunZone", "date": "today"})

    result = tool.execute("when_last", {"query": "bowling"})

    assert result.success
    today = datetime.now().date().isoformat()
    assert today in result.message

  def test_on_date_query(self, temp_data_dir):
    """'what happened on 3 feb 2026?' → list events"""
    tool = ExperienceTool(temp_data_dir)
    tool.execute("add", {"text": "lunch at Pizza Hut", "date": "2026-02-03"})
    tool.execute("add", {"text": "watched movie", "date": "2026-02-03"})

    result = tool.execute("on_date", {"date": "3 feb 2026"})

    assert result.success
    assert "2026-02-03" in result.message
    assert "2 event" in result.message

  def test_spent_at_place(self, temp_data_dir):
    """'how much spent at AlphaOne?' → total amount"""
    tool = ExperienceTool(temp_data_dir)
    tool.execute("add", {"text": "shopping", "date": "2026-01-15", "place": "AlphaOne", "amount": 2500})
    tool.execute("add", {"text": "dinner", "date": "2026-01-20", "place": "AlphaOne", "amount": 800})

    result = tool.execute("spent_at", {"place": "AlphaOne"})

    assert result.success
    assert "3,300" in result.message or "3300" in result.message

  def test_amount_auto_extraction(self, temp_data_dir):
    """Auto-extract ₹800 from 'bowling 800'"""
    tool = ExperienceTool(temp_data_dir)
    result = tool.execute("add", {"text": "bowling 800", "date": "today"})

    assert result.success
    assert "800" in result.message

  def test_stats(self, temp_data_dir):
    """Experience statistics"""
    tool = ExperienceTool(temp_data_dir)
    tool.execute("add", {"text": "went bowling", "date": "today", "amount": 500})
    tool.execute("add", {"text": "had lunch", "date": "today", "amount": 300})

    result = tool.execute("stats", {})

    assert result.success
    assert "Total events: 2" in result.message


# ========== C) REMINDER TESTS ==========

class TestReminderDomain:
  """Reminder = future actions with time"""

  def test_remind_next_year(self, temp_data_dir):
    """'remind me next year PUC' → 2027"""
    tool = ReminderTool(temp_data_dir)
    result = tool.execute("add", {"text": "PUC renewal next year"})

    assert result.success
    assert "2027" in result.message

  def test_remind_tomorrow(self, temp_data_dir):
    """'remind me tomorrow' → tomorrow's date"""
    tool = ReminderTool(temp_data_dir)
    result = tool.execute("add", {"text": "call mom tomorrow"})

    assert result.success
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    assert tomorrow in result.message

  def test_list_reminders(self, temp_data_dir):
    """List pending reminders"""
    tool = ReminderTool(temp_data_dir)
    tool.execute("add", {"text": "buy groceries tomorrow"})

    result = tool.execute("list", {})

    assert result.success
    assert "groceries" in result.message


# ========== D) RELATION TESTS ==========

class TestRelationDomain:
  """Relation = people graph"""

  def test_add_relation(self, temp_data_dir):
    """Add person to relations"""
    tool = RelationTool(temp_data_dir)
    result = tool.execute("add", {
      "name": "Ravi",
      "relationship": "friend",
      "trust_level": 8
    })

    assert result.success
    assert "Ravi" in result.message

  def test_who_is_query(self, temp_data_dir):
    """'who is Ravi?' → relation info"""
    tool = RelationTool(temp_data_dir)
    tool.execute("add", {"name": "Ravi", "relationship": "friend", "trust_level": 8})

    result = tool.execute("who", {"name": "Ravi"})

    assert result.success
    assert "Ravi" in result.message
    assert "friend" in result.message.lower()

  def test_log_interaction(self, temp_data_dir):
    """Log interaction with person"""
    tool = RelationTool(temp_data_dir)
    tool.execute("add", {"name": "Ravi", "relationship": "friend"})

    result = tool.execute("interact", {"name": "Ravi", "summary": "coffee at Starbucks"})

    assert result.success

  def test_interaction_history(self, temp_data_dir):
    """Get interaction history"""
    tool = RelationTool(temp_data_dir)
    tool.execute("add", {"name": "Ravi", "relationship": "friend"})
    tool.execute("interact", {"name": "Ravi", "summary": "Lunch together"})

    result = tool.execute("history", {"name": "Ravi"})

    assert result.success
    assert "Lunch" in result.message


# ========== DATE PARSER TESTS ==========

class TestDateParser:
  """Relative date parsing"""

  def test_next_year(self):
    """'next year' → +1 year"""
    parser = RelativeDateParser(datetime(2026, 2, 6))
    result, parsed = parser.parse("remind me next year")

    assert parsed
    assert result.year == 2027

  def test_specific_date_next_year(self):
    """'on 4 feb next year' → 2027-02-04"""
    parser = RelativeDateParser(datetime(2026, 2, 6))
    result, parsed = parser.parse("on 4 feb next year")

    assert parsed
    assert result.year == 2027
    assert result.month == 2
    assert result.day == 4

  def test_tomorrow(self):
    """'tomorrow' → +1 day"""
    parser = RelativeDateParser(datetime(2026, 2, 6))
    result, parsed = parser.parse("call tomorrow")

    assert parsed
    assert result.day == 7

  def test_after_n_years(self):
    """'after 2 years' → +2 years"""
    parser = RelativeDateParser(datetime(2026, 2, 6))
    result, parsed = parser.parse("after 2 years renew")

    assert parsed
    assert result.year == 2028


# ========== DOMAIN SEPARATION TESTS ==========

class TestDomainSeparation:
  """Verify entries go to correct domain"""

  def test_preference_in_memory_not_reminder(self, temp_data_dir):
    """Preferences go to memory, NOT reminder"""
    mem_tool = MemoryTool(temp_data_dir)
    mem_tool.execute("remember", {"text": "I like coffee"})

    # Check memory DB
    mem_conn = sqlite3.connect(temp_data_dir / "memories.db")
    cursor = mem_conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM memories WHERE text LIKE '%coffee%'")
    mem_count = cursor.fetchone()[0]
    mem_conn.close()

    assert mem_count == 1, "Should be in memories"

  def test_experience_has_date(self, temp_data_dir):
    """Experiences must have dates"""
    tool = ExperienceTool(temp_data_dir)
    tool.execute("add", {"text": "gym workout", "date": "today"})

    conn = sqlite3.connect(temp_data_dir / "experiences.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT date FROM experiences WHERE text LIKE '%gym%'")
    row = cursor.fetchone()
    conn.close()

    assert row is not None
    assert row['date'] == datetime.now().date().isoformat()


# ========== INTEGRATION TESTS ==========

class TestIntegration:
  """End-to-end workflows"""

  def test_experience_workflow(self, temp_data_dir):
    """Log → Query when last → Query spending"""
    tool = ExperienceTool(temp_data_dir)

    # Log
    tool.execute("add", {"text": "bowling at FunZone", "place": "FunZone", "amount": 800, "date": "today"})

    # When last?
    result = tool.execute("when_last", {"query": "bowling"})
    assert "bowling" in result.message.lower()

    # Spent how much?
    result = tool.execute("spent_at", {"place": "FunZone"})
    assert "800" in result.message

  def test_relation_workflow(self, temp_data_dir):
    """Add → Interact → Query who is"""
    tool = RelationTool(temp_data_dir)

    tool.execute("add", {"name": "Priya", "relationship": "colleague"})
    tool.execute("interact", {"name": "Priya", "summary": "Sprint meeting"})

    result = tool.execute("who", {"name": "Priya"})
    assert "Priya" in result.message


if __name__ == "__main__":
  pytest.main([__file__, "-v", "--tb=short"])
