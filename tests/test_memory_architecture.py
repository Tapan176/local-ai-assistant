"""
Phase 9.8: Memory Architecture Tests
Tests for domain separation: Reminders, Memories, Experiences
"""
import sys
import tempfile
import shutil
from pathlib import Path
from datetime import datetime

# Add project root
project_root = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(project_root))

from src.agent.tools.reminder_tool import ReminderTool
from src.agent.tools.memory_tool import MemoryTool
from src.agent.tools.experience_tool import ExperienceTool
from src.core.memory import MemoryManager


class MemoryArchitectureTests:
  """Test domain separation between Reminders, Memories, Experiences"""

  def __init__(self):
    self.temp_dir = Path(tempfile.mkdtemp())
    self.results = []

    # Setup DBs
    self._setup_dbs()

  def _setup_dbs(self):
    """Setup required databases"""
    # Reminders DB
    import sqlite3

    reminder_db = self.temp_dir / "reminders.db"
    conn = sqlite3.connect(reminder_db)
    conn.execute("""CREATE TABLE IF NOT EXISTS reminders (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      text TEXT NOT NULL,
      remind_at TIMESTAMP,
      status TEXT DEFAULT 'pending'
    )""")
    conn.commit()
    conn.close()

    # Memory DB
    memory_db = self.temp_dir / "memory.db"
    conn = sqlite3.connect(memory_db)
    conn.execute("""CREATE TABLE IF NOT EXISTS memories (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      text TEXT NOT NULL,
      category TEXT DEFAULT 'general',
      timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
      tags TEXT
    )""")
    conn.commit()
    conn.close()

  def cleanup(self):
    shutil.rmtree(self.temp_dir, ignore_errors=True)

  def add_result(self, test_name: str, passed: bool, message: str = ""):
    self.results.append({
      "name": test_name,
      "passed": passed,
      "message": message[:80]
    })
    status = "✓" if passed else "✗"
    print(f"  {status} {test_name}")
    if not passed and message:
      print(f"    └─ {message[:60]}")

  # ===== EXPERIENCE TOOL TESTS =====

  def test_experience_add_today(self):
    """Test: 'today went bowling 800' → Experience"""
    exp = ExperienceTool(self.temp_dir)
    r = exp.execute("add", {"text": "went bowling 800", "date": "today"})
    self.add_result(
      "Experience: add today event",
      r.success and "Logged" in r.message,
      r.message
    )

  def test_experience_add_yesterday(self):
    """Test: 'yesterday met Rahul' → Experience"""
    exp = ExperienceTool(self.temp_dir)
    r = exp.execute("add", {"text": "met Rahul at café", "date": "yesterday"})
    self.add_result(
      "Experience: add yesterday event",
      r.success and "Logged" in r.message,
      r.message
    )

  def test_experience_with_amount(self):
    """Test: experience with rupees extracted"""
    exp = ExperienceTool(self.temp_dir)
    r = exp.execute("add", {"text": "had dinner 500rs at Barbeque Nation"})
    self.add_result(
      "Experience: amount extraction",
      r.success and "500" in r.message,
      r.message
    )

  def test_experience_search_date(self):
    """Test: 'what happened on today' → search experiences"""
    exp = ExperienceTool(self.temp_dir)
    exp.execute("add", {"text": "morning walk", "date": "today"})
    r = exp.execute("on_date", {"date": "today"})
    self.add_result(
      "Experience: search by date",
      r.success,
      r.message
    )

  def test_experience_list(self):
    """Test: list recent experiences"""
    exp = ExperienceTool(self.temp_dir)
    r = exp.execute("list", {"days": 7})
    self.add_result(
      "Experience: list recent",
      r.success,
      r.message
    )

  # ===== MEMORY TOOL TESTS =====

  def test_memory_preference(self):
    """Test: 'I like black coffee' → Memory"""
    memory_db = self.temp_dir / "memory.db"
    mm = MemoryManager(memory_db)
    r = mm.remember("I like black coffee", category="preference")
    self.add_result(
      "Memory: store preference",
      "Remembered" in r,
      r
    )

  def test_memory_fact(self):
    """Test: 'my blood group is B+' → Memory"""
    memory_db = self.temp_dir / "memory.db"
    mm = MemoryManager(memory_db)
    r = mm.remember("my blood group is B+", category="personal")
    self.add_result(
      "Memory: store fact",
      "Remembered" in r,
      r
    )

  def test_memory_search(self):
    """Test: search memories"""
    memory_db = self.temp_dir / "memory.db"
    mm = MemoryManager(memory_db)
    mm.remember("I prefer tea over coffee")
    r = mm.search_memory("tea")
    self.add_result(
      "Memory: search",
      "tea" in r.lower() or "Found" in r,
      r[:50]
    )

  # ===== REMINDER TOOL TESTS =====

  def test_reminder_add(self):
    """Test: 'remind me at 8pm' → Reminder"""
    rem = ReminderTool(self.temp_dir)
    r = rem.execute("add", {"text": "call mom at 8pm"})
    self.add_result(
      "Reminder: add with time",
      r.success and "Reminder added" in r.message,
      r.message
    )

  def test_reminder_add_future(self):
    """Test: 'PUC due March 10' → Reminder"""
    rem = ReminderTool(self.temp_dir)
    r = rem.execute("add", {"text": "PUC due March 10"})
    self.add_result(
      "Reminder: add future task",
      r.success,
      r.message
    )

  def test_reminder_list(self):
    """Test: list reminders"""
    rem = ReminderTool(self.temp_dir)
    r = rem.execute("list", {})
    self.add_result(
      "Reminder: list",
      r.success,
      r.message
    )

  # ===== DOMAIN SEPARATION TESTS =====

  def test_domain_no_cross_contamination(self):
    """Test: experiences not in reminders, memories not in experiences"""
    exp = ExperienceTool(self.temp_dir)
    rem = ReminderTool(self.temp_dir)
    memory_db = self.temp_dir / "memory.db"
    mm = MemoryManager(memory_db)

    # Add to each domain
    exp.execute("add", {"text": "unique_exp_test_123"})
    rem.execute("add", {"text": "unique_rem_test_456"})
    mm.remember("unique_mem_test_789")

    # Check no cross-contamination
    exp_list = exp.execute("search", {"query": ""})
    rem_list = rem.execute("list", {})
    mem_list = mm.search_memory("")

    # Verify isolation
    exp_has_rem = "unique_rem_test" in exp_list.message
    exp_has_mem = "unique_mem_test" in exp_list.message
    rem_has_exp = "unique_exp_test" in rem_list.message

    passed = not exp_has_rem and not exp_has_mem and not rem_has_exp
    self.add_result(
      "Domain: no cross-contamination",
      passed,
      "Domains properly isolated" if passed else "Cross-contamination detected!"
    )

  def run_all(self):
    """Run all tests"""
    print("\n" + "=" * 60)
    print("  PHASE 9.8: MEMORY ARCHITECTURE TESTS")
    print("=" * 60 + "\n")

    print("📖 Experience Tool Tests:")
    self.test_experience_add_today()
    self.test_experience_add_yesterday()
    self.test_experience_with_amount()
    self.test_experience_search_date()
    self.test_experience_list()

    print("\n🧠 Memory Tool Tests:")
    self.test_memory_preference()
    self.test_memory_fact()
    self.test_memory_search()

    print("\n⏰ Reminder Tool Tests:")
    self.test_reminder_add()
    self.test_reminder_add_future()
    self.test_reminder_list()

    print("\n🔒 Domain Separation Tests:")
    self.test_domain_no_cross_contamination()

    # Summary
    passed = sum(1 for r in self.results if r["passed"])
    total = len(self.results)

    print("\n" + "=" * 60)
    print(f"  RESULTS: {passed}/{total} tests passed ({100*passed/total:.0f}%)")
    print("=" * 60)

    return passed == total


def main():
  tests = MemoryArchitectureTests()
  try:
    success = tests.run_all()
    return 0 if success else 1
  finally:
    tests.cleanup()


if __name__ == "__main__":
  exit(main())
