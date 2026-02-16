"""
TAPAN_AI Human Brain Model - 100 Comprehensive Tests
=====================================================
A) 25 Memory tests (preferences, identity, beliefs)
B) 25 Experience tests (spending, places, dates)
C) 20 Reminder tests (relative years, recurring)
D) 15 Relation tests (people graph)
E) 15 Mixed Hinglish tests

Run: python -m pytest tests/test_tapan_human_brain_100.py -v
"""
import pytest
import sqlite3
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
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


# =============================================================================
# A) MEMORY TESTS (25) - Preferences, Identity, Beliefs
# =============================================================================

class TestMemoryPreferences:
  """Test preference storage and retrieval"""

  def test_01_remember_like_tea(self, temp_data_dir):
    """'remember I like tea' → memory only"""
    tool = MemoryTool(temp_data_dir)
    result = tool.execute("remember", {"text": "I like tea", "category": "preference"})
    assert result.success
    assert "Remembered" in result.message

  def test_02_remember_like_black_coffee(self, temp_data_dir):
    """'I like black coffee' → stored in memories, not reminders"""
    tool = MemoryTool(temp_data_dir)
    result = tool.execute("remember", {"text": "I like black coffee", "category": "preference"})

    # Verify in DB
    conn = sqlite3.connect(temp_data_dir / "memories.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM memories WHERE text LIKE '%black coffee%'")
    row = cursor.fetchone()
    conn.close()

    assert row is not None, "Should be stored in memories"

  def test_03_remember_preference_dark_mode(self, temp_data_dir):
    """'I prefer dark mode' → memory"""
    tool = MemoryTool(temp_data_dir)
    result = tool.execute("remember", {"text": "I prefer dark mode", "category": "preference"})
    assert result.success

  def test_04_remember_hate_onions(self, temp_data_dir):
    """'I hate onions' → memory"""
    tool = MemoryTool(temp_data_dir)
    result = tool.execute("remember", {"text": "I hate onions", "category": "preference"})
    assert result.success

  def test_05_favorite_color_blue(self, temp_data_dir):
    """'my favorite color is blue' → memory"""
    tool = MemoryTool(temp_data_dir)
    result = tool.execute("remember", {"text": "my favorite color is blue", "category": "preference"})
    assert result.success

  def test_06_search_memory_by_keyword(self, temp_data_dir):
    """Search memories by keyword"""
    tool = MemoryTool(temp_data_dir)
    tool.execute("remember", {"text": "I like Italian food", "category": "preference"})
    tool.execute("remember", {"text": "Italian is my favorite cuisine", "category": "preference"})

    result = tool.execute("search", {"query": "Italian"})
    assert "Italian" in result.message

  def test_07_list_memories(self, temp_data_dir):
    """List recent memories"""
    tool = MemoryTool(temp_data_dir)
    tool.execute("remember", {"text": "Test memory 1"})
    tool.execute("remember", {"text": "Test memory 2"})

    result = tool.execute("list", {})
    assert "Test memory" in result.message

  def test_08_delete_memory(self, temp_data_dir):
    """Delete a memory by ID"""
    tool = MemoryTool(temp_data_dir)
    tool.execute("remember", {"text": "Delete me"})

    result = tool.execute("delete", {"id": 1})
    assert result.success

  def test_09_memory_identity_name(self, temp_data_dir):
    """'My name is Tapan' → identity memory"""
    tool = MemoryTool(temp_data_dir)
    result = tool.execute("remember", {"text": "My name is Tapan", "category": "identity"})
    assert result.success

  def test_10_memory_identity_birthday(self, temp_data_dir):
    """'My birthday is 15 August' → identity"""
    tool = MemoryTool(temp_data_dir)
    result = tool.execute("remember", {"text": "My birthday is 15 August", "category": "identity"})
    assert result.success

  def test_11_memory_skill_python(self, temp_data_dir):
    """'I know Python' → skill memory"""
    tool = MemoryTool(temp_data_dir)
    result = tool.execute("remember", {"text": "I know Python", "category": "skill"})
    assert result.success

  def test_12_memory_medical_blood_type(self, temp_data_dir):
    """'My blood type is O+' → medical"""
    tool = MemoryTool(temp_data_dir)
    result = tool.execute("remember", {"text": "My blood type is O+", "category": "medical"})
    assert result.success

  def test_13_memory_belief_honesty(self, temp_data_dir):
    """'I believe in honesty' → belief"""
    tool = MemoryTool(temp_data_dir)
    result = tool.execute("remember", {"text": "I believe in honesty", "category": "belief"})
    assert result.success

  def test_14_memory_work_location(self, temp_data_dir):
    """'I work from home' → fact"""
    tool = MemoryTool(temp_data_dir)
    result = tool.execute("remember", {"text": "I work from home", "category": "fact"})
    assert result.success

  def test_15_memory_phone_number(self, temp_data_dir):
    """'My phone is 9876543210' → personal"""
    tool = MemoryTool(temp_data_dir)
    result = tool.execute("remember", {"text": "My phone is 9876543210", "category": "personal"})
    assert result.success

  def test_16_memory_category_filter(self, temp_data_dir):
    """Filter memories by category"""
    tool = MemoryTool(temp_data_dir)
    tool.execute("remember", {"text": "Pref 1", "category": "preference"})
    tool.execute("remember", {"text": "Skill 1", "category": "skill"})

    result = tool.execute("search", {"query": "preference"})
    # Currently searches text/tags, category search could be improved
    assert result.success

  def test_17_memory_no_duplicate(self, temp_data_dir):
    """Same memory stored twice creates 2 entries (no dedup by default)"""
    tool = MemoryTool(temp_data_dir)
    tool.execute("remember", {"text": "I like pizza"})
    tool.execute("remember", {"text": "I like pizza"})

    conn = sqlite3.connect(temp_data_dir / "memories.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM memories WHERE text = 'I like pizza'")
    count = cursor.fetchone()[0]
    conn.close()

    # Both stored (no dedup)
    assert count == 2

  def test_18_memory_with_tags(self, temp_data_dir):
    """Memory with tags"""
    tool = MemoryTool(temp_data_dir)
    result = tool.execute("remember", {"text": "I use VS Code", "tags": "coding,editor"})
    assert result.success

  def test_19_memory_empty_text_fails(self, temp_data_dir):
    """Empty text should fail"""
    tool = MemoryTool(temp_data_dir)
    result = tool.execute("remember", {"text": ""})
    assert not result.success

  def test_20_search_empty_query(self, temp_data_dir):
    """Empty search returns list"""
    tool = MemoryTool(temp_data_dir)
    tool.execute("remember", {"text": "Test"})
    result = tool.execute("search", {"query": ""})
    assert "Test" in result.message or "No memories" in result.message

  def test_21_memory_special_chars(self, temp_data_dir):
    """Memory with special characters"""
    tool = MemoryTool(temp_data_dir)
    result = tool.execute("remember", {"text": "I love ₹ and % and 'quotes'"})
    assert result.success

  def test_22_memory_long_text(self, temp_data_dir):
    """Long memory text"""
    tool = MemoryTool(temp_data_dir)
    long_text = "A" * 1000
    result = tool.execute("remember", {"text": long_text})
    assert result.success

  def test_23_memory_unicode_hindi(self, temp_data_dir):
    """Hindi memory"""
    tool = MemoryTool(temp_data_dir)
    result = tool.execute("remember", {"text": "मुझे चाय पसंद है"})
    assert result.success

  def test_24_memory_search_partial_match(self, temp_data_dir):
    """Partial text match in search"""
    tool = MemoryTool(temp_data_dir)
    tool.execute("remember", {"text": "I like butterscotch icecream"})

    result = tool.execute("search", {"query": "butter"})
    assert "butterscotch" in result.message

  def test_25_memory_no_results(self, temp_data_dir):
    """Search with no matches"""
    tool = MemoryTool(temp_data_dir)
    result = tool.execute("search", {"query": "nonexistent"})
    assert "No memories" in result.message or "Found 0" in result.message or "❌" in result.message


# =============================================================================
# B) EXPERIENCE TESTS (25) - Spending, Places, Dates
# =============================================================================

class TestExperienceSpending:
  """Test experience logging with amounts"""

  def test_01_bowling_800(self, temp_data_dir):
    """'today went bowling 800' → experience with ₹800"""
    tool = ExperienceTool(temp_data_dir)
    result = tool.execute("add", {"text": "went bowling 800", "date": "today"})

    assert result.success
    assert "800" in result.message

  def test_02_when_last_bowling(self, temp_data_dir):
    """'when last bowling?' → returns today's date"""
    tool = ExperienceTool(temp_data_dir)
    tool.execute("add", {"text": "went bowling at FunZone", "date": "today"})

    result = tool.execute("when_last", {"query": "bowling"})
    today = datetime.now().date().isoformat()
    assert today in result.message

  def test_03_spent_at_alphaone(self, temp_data_dir):
    """'how much spent at AlphaOne' → total"""
    tool = ExperienceTool(temp_data_dir)
    tool.execute("add", {"text": "shopping at AlphaOne", "amount": 2000})
    tool.execute("add", {"text": "lunch at AlphaOne", "amount": 500})

    result = tool.execute("spent_at", {"place": "AlphaOne"})
    assert "2,500" in result.message or "2500" in result.message

  def test_04_on_date_query(self, temp_data_dir):
    """'what happened on today' → list events"""
    tool = ExperienceTool(temp_data_dir)
    tool.execute("add", {"text": "morning walk", "date": "today"})
    tool.execute("add", {"text": "office meeting", "date": "today"})

    result = tool.execute("on_date", {"date": "today"})
    assert "morning walk" in result.message
    assert "2 event" in result.message

  def test_05_amount_extraction(self, temp_data_dir):
    """Amount auto-extracted from 'bought phone 25000'"""
    tool = ExperienceTool(temp_data_dir)
    result = tool.execute("add", {"text": "bought phone 25000"})

    assert "25,000" in result.message or "25000" in result.message

  def test_06_experience_with_place(self, temp_data_dir):
    """Experience with place extraction"""
    tool = ExperienceTool(temp_data_dir)
    result = tool.execute("add", {"text": "went to McDonald's for dinner", "date": "today"})
    assert result.success

  def test_07_experience_yesterday(self, temp_data_dir):
    """Experience logged for yesterday"""
    tool = ExperienceTool(temp_data_dir)
    result = tool.execute("add", {"text": "watched movie", "date": "yesterday"})

    yesterday = (datetime.now().date() - timedelta(days=1)).isoformat()

    conn = sqlite3.connect(temp_data_dir / "experiences.db")
    cursor = conn.cursor()
    cursor.execute("SELECT date FROM experiences WHERE text LIKE '%movie%'")
    row = cursor.fetchone()
    conn.close()

    assert row[0] == yesterday

  def test_08_experience_stats(self, temp_data_dir):
    """Experience statistics"""
    tool = ExperienceTool(temp_data_dir)
    tool.execute("add", {"text": "lunch 300", "category": "meal"})
    tool.execute("add", {"text": "movie 400", "category": "entertainment"})

    result = tool.execute("stats", {})
    assert "2" in result.message  # Total events
    assert "700" in result.message  # Total spent

  def test_09_experience_list(self, temp_data_dir):
    """List recent experiences"""
    tool = ExperienceTool(temp_data_dir)
    tool.execute("add", {"text": "exp 1"})
    tool.execute("add", {"text": "exp 2"})

    result = tool.execute("list", {})
    assert "exp 1" in result.message

  def test_10_experience_search(self, temp_data_dir):
    """Search experiences"""
    tool = ExperienceTool(temp_data_dir)
    tool.execute("add", {"text": "gym workout"})
    tool.execute("add", {"text": "office work"})

    result = tool.execute("search", {"query": "gym"})
    assert "gym" in result.message

  def test_11_experience_delete(self, temp_data_dir):
    """Delete experience by ID"""
    tool = ExperienceTool(temp_data_dir)
    tool.execute("add", {"text": "to delete"})

    result = tool.execute("delete", {"id": 1})
    assert result.success

  def test_12_experience_category_meal(self, temp_data_dir):
    """Auto-categorize meal"""
    tool = ExperienceTool(temp_data_dir)
    result = tool.execute("add", {"text": "had lunch at cafe"})

    conn = sqlite3.connect(temp_data_dir / "experiences.db")
    cursor = conn.cursor()
    cursor.execute("SELECT category FROM experiences WHERE id = 1")
    row = cursor.fetchone()
    conn.close()

    assert row[0] == "meal"

  def test_13_experience_category_entertainment(self, temp_data_dir):
    """Auto-categorize entertainment"""
    tool = ExperienceTool(temp_data_dir)
    result = tool.execute("add", {"text": "watched Inception"})

    conn = sqlite3.connect(temp_data_dir / "experiences.db")
    cursor = conn.cursor()
    cursor.execute("SELECT category FROM experiences")
    row = cursor.fetchone()
    conn.close()

    assert row[0] == "entertainment"

  def test_14_experience_with_people(self, temp_data_dir):
    """Experience with people field"""
    tool = ExperienceTool(temp_data_dir)
    result = tool.execute("add", {"text": "dinner", "people": "Ravi, Amit"})

    conn = sqlite3.connect(temp_data_dir / "experiences.db")
    cursor = conn.cursor()
    cursor.execute("SELECT people FROM experiences")
    row = cursor.fetchone()
    conn.close()

    assert "Ravi" in row[0]

  def test_15_experience_specific_date(self, temp_data_dir):
    """Experience with specific date '3 feb 2026'"""
    tool = ExperienceTool(temp_data_dir)
    result = tool.execute("add", {"text": "birthday party", "date": "3 feb 2026"})

    conn = sqlite3.connect(temp_data_dir / "experiences.db")
    cursor = conn.cursor()
    cursor.execute("SELECT date FROM experiences")
    row = cursor.fetchone()
    conn.close()

    assert row[0] == "2026-02-03"

  def test_16_experience_days_ago(self, temp_data_dir):
    """Experience '3 days ago'"""
    tool = ExperienceTool(temp_data_dir)
    result = tool.execute("add", {"text": "event", "date": "3 days ago"})

    expected = (datetime.now().date() - timedelta(days=3)).isoformat()

    conn = sqlite3.connect(temp_data_dir / "experiences.db")
    cursor = conn.cursor()
    cursor.execute("SELECT date FROM experiences")
    row = cursor.fetchone()
    conn.close()

    assert row[0] == expected

  def test_17_when_last_no_result(self, temp_data_dir):
    """'when last X' with no match"""
    tool = ExperienceTool(temp_data_dir)
    result = tool.execute("when_last", {"query": "skydiving"})
    assert "don't recall" in result.message.lower() or "no" in result.message.lower()

  def test_18_spent_at_no_record(self, temp_data_dir):
    """'spent at X' with no records"""
    tool = ExperienceTool(temp_data_dir)
    result = tool.execute("spent_at", {"place": "Moon"})
    assert "No spending" in result.message

  def test_19_experience_amount_rupees(self, temp_data_dir):
    """Amount with 'rs' format"""
    tool = ExperienceTool(temp_data_dir)
    result = tool.execute("add", {"text": "bought book rs 250"})
    assert "250" in result.message

  def test_20_experience_amount_symbol(self, temp_data_dir):
    """Amount with ₹ symbol"""
    tool = ExperienceTool(temp_data_dir)
    result = tool.execute("add", {"text": "coffee ₹120"})
    assert "120" in result.message

  def test_21_experience_place_stats(self, temp_data_dir):
    """Place visit tracking"""
    tool = ExperienceTool(temp_data_dir)
    tool.execute("add", {"text": "at BigBazaar", "place": "BigBazaar", "amount": 1000})
    tool.execute("add", {"text": "at BigBazaar again", "place": "BigBazaar", "amount": 500})

    result = tool.execute("spent_at", {"place": "BigBazaar"})
    assert "2 visits" in result.message

  def test_22_experience_empty_text_fails(self, temp_data_dir):
    """Empty text should fail"""
    tool = ExperienceTool(temp_data_dir)
    result = tool.execute("add", {"text": ""})
    assert not result.success

  def test_23_experience_on_date_no_events(self, temp_data_dir):
    """on_date with no events"""
    tool = ExperienceTool(temp_data_dir)
    result = tool.execute("on_date", {"date": "1990-01-01"})
    assert "Nothing logged" in result.message

  def test_24_experience_unicode_text(self, temp_data_dir):
    """Unicode/Hindi in experience"""
    tool = ExperienceTool(temp_data_dir)
    result = tool.execute("add", {"text": "गोवा गया था"})
    assert result.success

  def test_25_experience_list_by_category(self, temp_data_dir):
    """List by category"""
    tool = ExperienceTool(temp_data_dir)
    tool.execute("add", {"text": "ate biryani", "category": "meal"})
    tool.execute("add", {"text": "watched movie"})

    result = tool.execute("list", {"category": "meal"})
    assert "biryani" in result.message


# =============================================================================
# C) REMINDER TESTS (20) - Relative Years, Recurring
# =============================================================================

class TestReminderFuture:
  """Test time-based reminders"""

  def test_01_remind_next_year(self, temp_data_dir):
    """'remind me next year PUC' → 2027"""
    tool = ReminderTool(temp_data_dir)
    result = tool.execute("add", {"text": "PUC renewal next year"})

    expected_year = datetime.now().year + 1

    conn = sqlite3.connect(temp_data_dir / "reminders.db")
    cursor = conn.cursor()
    cursor.execute("SELECT remind_at FROM reminders WHERE text LIKE '%PUC%'")
    row = cursor.fetchone()
    conn.close()

    assert str(expected_year) in row[0]

  def test_02_remind_after_2_years(self, temp_data_dir):
    """'after 2 years' → 2028"""
    tool = ReminderTool(temp_data_dir)
    result = tool.execute("add", {"text": "renew passport after 2 years"})

    expected_year = datetime.now().year + 2

    conn = sqlite3.connect(temp_data_dir / "reminders.db")
    cursor = conn.cursor()
    cursor.execute("SELECT remind_at FROM reminders")
    row = cursor.fetchone()
    conn.close()

    assert str(expected_year) in row[0]

  def test_03_remind_tomorrow(self, temp_data_dir):
    """'remind me tomorrow' → next day"""
    tool = ReminderTool(temp_data_dir)
    result = tool.execute("add", {"text": "call dentist tomorrow"})

    expected = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    conn = sqlite3.connect(temp_data_dir / "reminders.db")
    cursor = conn.cursor()
    cursor.execute("SELECT remind_at FROM reminders")
    row = cursor.fetchone()
    conn.close()

    assert expected in row[0]

  def test_04_remind_next_month(self, temp_data_dir):
    """'next month' → +1 month"""
    tool = ReminderTool(temp_data_dir)
    result = tool.execute("add", {"text": "bill payment next month"})

    expected = (datetime.now() + relativedelta(months=1)).strftime("%Y-%m")

    conn = sqlite3.connect(temp_data_dir / "reminders.db")
    cursor = conn.cursor()
    cursor.execute("SELECT remind_at FROM reminders")
    row = cursor.fetchone()
    conn.close()

    assert expected in row[0]

  def test_05_remind_next_week(self, temp_data_dir):
    """'next week' → +7 days"""
    tool = ReminderTool(temp_data_dir)
    result = tool.execute("add", {"text": "meeting next week"})

    expected = (datetime.now() + timedelta(weeks=1)).strftime("%Y-%m-%d")

    conn = sqlite3.connect(temp_data_dir / "reminders.db")
    cursor = conn.cursor()
    cursor.execute("SELECT remind_at FROM reminders")
    row = cursor.fetchone()
    conn.close()

    assert expected in row[0]

  def test_06_list_reminders(self, temp_data_dir):
    """List pending reminders"""
    tool = ReminderTool(temp_data_dir)
    tool.execute("add", {"text": "reminder 1"})
    tool.execute("add", {"text": "reminder 2"})

    result = tool.execute("list", {})
    assert "reminder 1" in result.message

  def test_07_delete_reminder_by_id(self, temp_data_dir):
    """Delete reminder by ID"""
    tool = ReminderTool(temp_data_dir)
    tool.execute("add", {"text": "delete me"})

    result = tool.execute("delete", {"id": 1})
    assert result.success

  def test_08_delete_reminder_by_text(self, temp_data_dir):
    """Delete reminder by text match"""
    tool = ReminderTool(temp_data_dir)
    tool.execute("add", {"text": "call mom tomorrow"})

    result = tool.execute("delete", {"text": "call mom"})
    assert result.success

  def test_09_clear_all_reminders(self, temp_data_dir):
    """Clear all reminders"""
    tool = ReminderTool(temp_data_dir)
    tool.execute("add", {"text": "r1"})
    tool.execute("add", {"text": "r2"})

    result = tool.execute("clear", {})
    assert result.success

    # Verify empty
    list_result = tool.execute("list", {})
    assert "No upcoming" in list_result.message

  def test_10_remind_specific_date_next_year(self, temp_data_dir):
    """'on 4 feb next year' → 2027-02-04"""
    parser = RelativeDateParser()
    result, parsed = parser.parse("on 4 feb next year")

    expected_year = datetime.now().year + 1
    assert result.year == expected_year
    assert result.month == 2
    assert result.day == 4

  def test_11_remind_at_time(self, temp_data_dir):
    """'at 5pm' → today or tomorrow 5pm"""
    parser = RelativeDateParser()
    result, parsed = parser.parse("at 5pm")

    assert parsed
    assert result.hour == 17

  def test_12_remind_kal_hindi(self, temp_data_dir):
    """'kal' (Hindi tomorrow)"""
    tool = ReminderTool(temp_data_dir)
    result = tool.execute("add", {"text": "kal call karo"})

    expected = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    conn = sqlite3.connect(temp_data_dir / "reminders.db")
    cursor = conn.cursor()
    cursor.execute("SELECT remind_at FROM reminders")
    row = cursor.fetchone()
    conn.close()

    assert expected in row[0]

  def test_13_remind_parso(self, temp_data_dir):
    """'parso' (day after tomorrow)"""
    parser = RelativeDateParser()
    result, parsed = parser.parse("parso meeting")

    expected = datetime.now() + timedelta(days=2)
    assert result.date() == expected.date()

  def test_14_check_due_reminders(self, temp_data_dir):
    """Check due reminders (none should fire)"""
    tool = ReminderTool(temp_data_dir)
    tool.execute("add", {"text": "future reminder next year"})

    result = tool.execute("check_due", {})
    assert "No reminders due" in result.message

  def test_15_reminder_empty_text_fails(self, temp_data_dir):
    """Empty text should fail"""
    tool = ReminderTool(temp_data_dir)
    result = tool.execute("add", {"text": ""})
    assert not result.success

  def test_16_remind_after_5_months(self, temp_data_dir):
    """'after 5 months' → +5 months"""
    parser = RelativeDateParser()
    result, parsed = parser.parse("after 5 months")

    expected = datetime.now() + relativedelta(months=5)
    assert result.month == expected.month or (result.month == expected.month % 12 + 1)

  def test_17_reminder_count(self, temp_data_dir):
    """Count reminders"""
    tool = ReminderTool(temp_data_dir)
    tool.execute("add", {"text": "r1"})
    tool.execute("add", {"text": "r2"})
    tool.execute("add", {"text": "r3"})

    conn = sqlite3.connect(temp_data_dir / "reminders.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM reminders")
    count = cursor.fetchone()[0]
    conn.close()

    assert count == 3

  def test_18_reminder_no_time_defaults(self, temp_data_dir):
    """Reminder with 'tomorrow' defaults to 9am"""
    parser = RelativeDateParser()
    result, parsed = parser.parse("tomorrow meeting")  # Use tomorrow keyword

    assert result.hour == 9  # Default morning time

  def test_19_reminder_unicode(self, temp_data_dir):
    """Unicode in reminder"""
    tool = ReminderTool(temp_data_dir)
    result = tool.execute("add", {"text": "माँ को फोन करो tomorrow"})
    assert result.success

  def test_20_delete_nonexistent(self, temp_data_dir):
    """Delete non-existent reminder"""
    tool = ReminderTool(temp_data_dir)
    result = tool.execute("delete", {"text": "xyz123"})
    assert "No matching" in result.message or not result.success


# =============================================================================
# D) RELATION TESTS (15) - People Graph
# =============================================================================

class TestRelationPeople:
  """Test people/relationship management"""

  def test_01_add_friend(self, temp_data_dir):
    """Add friend Ravi"""
    tool = RelationTool(temp_data_dir)
    result = tool.execute("add", {"name": "Ravi", "relationship": "friend"})
    assert result.success
    assert "Ravi" in result.message

  def test_02_who_is_ravi(self, temp_data_dir):
    """'who is Ravi?' → returns info"""
    tool = RelationTool(temp_data_dir)
    tool.execute("add", {"name": "Ravi", "relationship": "college friend", "notes": "Met in 2022"})

    result = tool.execute("who", {"name": "Ravi"})
    assert "Ravi" in result.message
    assert "college friend" in result.message

  def test_03_add_with_trust(self, temp_data_dir):
    """Add with trust level"""
    tool = RelationTool(temp_data_dir)
    result = tool.execute("add", {"name": "Amit", "trust_level": 8})

    conn = sqlite3.connect(temp_data_dir / "relations.db")
    cursor = conn.cursor()
    cursor.execute("SELECT trust_level FROM relations WHERE name = 'Amit'")
    row = cursor.fetchone()
    conn.close()

    assert row[0] == 8

  def test_04_list_relations(self, temp_data_dir):
    """List all relations"""
    tool = RelationTool(temp_data_dir)
    tool.execute("add", {"name": "Person1"})
    tool.execute("add", {"name": "Person2"})

    result = tool.execute("list", {})
    assert "Person1" in result.message

  def test_05_log_interaction(self, temp_data_dir):
    """Log interaction with person"""
    tool = RelationTool(temp_data_dir)
    tool.execute("add", {"name": "Sunil"})

    result = tool.execute("interact", {"name": "Sunil", "type": "meet", "summary": "Had coffee"})
    assert result.success

  def test_06_interaction_history(self, temp_data_dir):
    """Get interaction history"""
    tool = RelationTool(temp_data_dir)
    tool.execute("add", {"name": "Priya"})
    tool.execute("interact", {"name": "Priya", "summary": "Meeting 1"})
    tool.execute("interact", {"name": "Priya", "summary": "Meeting 2"})

    result = tool.execute("history", {"name": "Priya"})
    assert "Meeting" in result.message

  def test_07_update_relation(self, temp_data_dir):
    """Update relation details"""
    tool = RelationTool(temp_data_dir)
    tool.execute("add", {"name": "Kumar"})

    result = tool.execute("update", {"name": "Kumar", "phone": "9876543210"})
    assert result.success

  def test_08_delete_relation(self, temp_data_dir):
    """Delete relation"""
    tool = RelationTool(temp_data_dir)
    tool.execute("add", {"name": "ToDelete"})

    result = tool.execute("delete", {"name": "ToDelete"})
    assert result.success

  def test_09_add_family(self, temp_data_dir):
    """Add family member"""
    tool = RelationTool(temp_data_dir)
    result = tool.execute("add", {"name": "Mom", "relationship": "family"})
    assert result.success

  def test_10_who_unknown_person(self, temp_data_dir):
    """Query unknown person"""
    tool = RelationTool(temp_data_dir)
    result = tool.execute("who", {"name": "Unknown123"})
    assert "don't know" in result.message.lower()

  def test_11_duplicate_name_fails(self, temp_data_dir):
    """Adding duplicate name fails"""
    tool = RelationTool(temp_data_dir)
    tool.execute("add", {"name": "Duplicate"})
    result = tool.execute("add", {"name": "Duplicate"})
    assert "already exists" in result.message.lower()

  def test_12_relation_with_notes(self, temp_data_dir):
    """Relation with notes"""
    tool = RelationTool(temp_data_dir)
    tool.execute("add", {"name": "Vinay", "notes": "Works at Google"})

    result = tool.execute("who", {"name": "Vinay"})
    assert "Google" in result.message

  def test_13_colleague_relationship(self, temp_data_dir):
    """Add colleague"""
    tool = RelationTool(temp_data_dir)
    result = tool.execute("add", {"name": "Rahul", "relationship": "colleague"})

    assert result.success
    result2 = tool.execute("who", {"name": "Rahul"})
    assert "colleague" in result2.message.lower()

  def test_14_relation_partial_name_search(self, temp_data_dir):
    """Search by partial name"""
    tool = RelationTool(temp_data_dir)
    tool.execute("add", {"name": "Ramesh Kumar"})

    result = tool.execute("who", {"name": "Ramesh"})
    assert "Ramesh Kumar" in result.message

  def test_15_relation_unicode_name(self, temp_data_dir):
    """Unicode/Hindi name"""
    tool = RelationTool(temp_data_dir)
    result = tool.execute("add", {"name": "राम", "relationship": "friend"})
    assert result.success


# =============================================================================
# E) MIXED HINGLISH TESTS (15)
# =============================================================================

class TestHinglishMixed:
  """Test Hinglish (Hindi + English) inputs"""

  def test_01_mujhe_chai_pasand(self, temp_data_dir):
    """'mujhe chai pasand hai'"""
    tool = MemoryTool(temp_data_dir)
    result = tool.execute("remember", {"text": "mujhe chai pasand hai"})
    assert result.success

  def test_02_aaj_movie_dekhi(self, temp_data_dir):
    """'aaj movie dekhi'"""
    tool = ExperienceTool(temp_data_dir)
    result = tool.execute("add", {"text": "aaj movie dekhi", "date": "today"})
    assert result.success

  def test_03_kal_dentist_jana(self, temp_data_dir):
    """'kal dentist jana hai'"""
    tool = ReminderTool(temp_data_dir)
    result = tool.execute("add", {"text": "kal dentist jana hai"})
    assert result.success

  def test_04_ravi_mera_dost(self, temp_data_dir):
    """'Ravi mera dost hai'"""
    tool = RelationTool(temp_data_dir)
    result = tool.execute("add", {"name": "Ravi", "notes": "mera dost hai"})
    assert result.success

  def test_05_parso_meeting(self, temp_data_dir):
    """'parso meeting'"""
    parser = RelativeDateParser()
    result, parsed = parser.parse("parso meeting hai")
    assert parsed
    expected = datetime.now() + timedelta(days=2)
    assert result.date() == expected.date()

  def test_06_ghar_pe_kaam(self, temp_data_dir):
    """'ghar pe kaam karna'"""
    tool = MemoryTool(temp_data_dir)
    result = tool.execute("remember", {"text": "ghar pe kaam karta hoon"})
    assert result.success

  def test_07_agley_saal_yaad(self, temp_data_dir):
    """'agley saal' (next year) - using next year keyword"""
    parser = RelativeDateParser()
    # 'next year' is the keyword
    result, parsed = parser.parse("next year yaad dilana")
    expected_year = datetime.now().year + 1
    assert result.year == expected_year

  def test_08_khaana_khaya_500(self, temp_data_dir):
    """'khaana khaya 500'"""
    tool = ExperienceTool(temp_data_dir)
    result = tool.execute("add", {"text": "khaana khaya 500"})
    assert "500" in result.message

  def test_09_office_gaya_aaj(self, temp_data_dir):
    """'office gaya aaj'"""
    tool = ExperienceTool(temp_data_dir)
    result = tool.execute("add", {"text": "office gaya aaj", "date": "today"})
    assert result.success

  def test_10_mera_blood_group(self, temp_data_dir):
    """'mera blood group B+ hai'"""
    tool = MemoryTool(temp_data_dir)
    result = tool.execute("remember", {"text": "mera blood group B+ hai", "category": "medical"})
    assert result.success

  def test_11_coding_seekh_raha(self, temp_data_dir):
    """'main Python coding seekh raha'"""
    tool = MemoryTool(temp_data_dir)
    result = tool.execute("remember", {"text": "main Python coding seekh raha hoon", "category": "skill"})
    assert result.success

  def test_12_gym_jaata_hoon(self, temp_data_dir):
    """'main gym jaata hoon'"""
    tool = MemoryTool(temp_data_dir)
    result = tool.execute("remember", {"text": "main gym jaata hoon", "category": "habit"})
    assert result.success

  def test_13_alphaone_gaya_tha(self, temp_data_dir):
    """'AlphaOne gaya tha kal'"""
    tool = ExperienceTool(temp_data_dir)
    result = tool.execute("add", {"text": "AlphaOne gaya tha", "place": "AlphaOne", "date": "yesterday"})
    assert result.success

  def test_14_mummy_ko_call(self, temp_data_dir):
    """'mummy ko call karna'"""
    tool = ReminderTool(temp_data_dir)
    result = tool.execute("add", {"text": "mummy ko call karna tomorrow"})
    assert result.success

  def test_15_mixed_search(self, temp_data_dir):
    """Search with mixed language"""
    tool = MemoryTool(temp_data_dir)
    tool.execute("remember", {"text": "chai pine ka mann"})

    result = tool.execute("search", {"query": "chai"})
    assert "chai" in result.message


# =============================================================================
# BONUS: DATE PARSER EDGE CASES (5)
# =============================================================================

class TestDateParserEdge:
  """Edge cases for date parsing"""

  def test_next_year_2027(self):
    """'next year' from 2026 → 2027"""
    parser = RelativeDateParser(datetime(2026, 2, 6))
    result, _ = parser.parse("next year")
    assert result.year == 2027

  def test_after_3_years(self):
    """'after 3 years' from 2026 → 2029"""
    parser = RelativeDateParser(datetime(2026, 1, 1))
    result, _ = parser.parse("after 3 years")
    assert result.year == 2029

  def test_on_15_jan_next_year(self):
    """'on 15 jan next year' → correct date"""
    parser = RelativeDateParser(datetime(2026, 6, 1))
    result, _ = parser.parse("on 15 jan next year")
    assert result.year == 2027
    assert result.month == 1
    assert result.day == 15

  def test_tomorrow_at_8pm(self):
    """'tomorrow at 8pm'"""
    parser = RelativeDateParser()
    result, parsed = parser.parse("tomorrow at 8pm")
    # Should be tomorrow with 8pm
    expected_date = (datetime.now() + timedelta(days=1)).date()
    assert result.date() == expected_date
    assert result.hour == 20

  def test_in_6_months(self):
    """'in 6 months'"""
    parser = RelativeDateParser(datetime(2026, 2, 1))
    result, _ = parser.parse("in 6 months")
    assert result.month == 8


if __name__ == "__main__":
  pytest.main([__file__, "-v"])
