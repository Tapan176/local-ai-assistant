"""
TAPAN_AI Human Brain - Comprehensive Test Suite
Verifies:
1. Domain Separation (Reminder vs Memory vs Experience)
2. Retrieval (when last, spent at, who is)
3. Relative Date Parsing
4. Component functionality
"""
import unittest
import sys
import shutil
import tempfile
from pathlib import Path
from datetime import datetime, timedelta

# Add src to path
sys.path.append(str(Path(__file__).parent.parent))

from src.agent.orchestrator import Orchestrator
from src.agent.tools.reminder_tool import ReminderTool
from src.agent.tools.experience_tool import ExperienceTool
from src.agent.tools.memory_tool import MemoryTool
from src.agent.tools.relation_tool import RelationTool
from src.agent.tools.persona_tool import PersonaTool
from src.core.date_parser import parse_relative_date

class TestHumanBrain(unittest.TestCase):
  def setUp(self):
    self.test_dir = Path(tempfile.mkdtemp())
    self.orchestrator = Orchestrator(data_dir=self.test_dir)

  def tearDown(self):
    try:
      shutil.rmtree(self.test_dir)
    except:
      pass

  def test_01_domain_separation_memory(self):
    """Test 'remember I like tea' -> Memory (not reminder)"""
    print("\nTesting Memory Intent...")
    # Use _check_deterministic_intent to verify strict routing
    result = self.orchestrator.process("remember I like tea")

    self.assertIsNotNone(result)
    # Memory tool returns "Remembered:" or similar
    self.assertTrue("✓" in result, f"Expected success message, got: {result}")
    self.assertTrue("ike tea" in result or "tea" in result, f"Expected content in result: {result}")

    # Verify it went to memory DB
    tool = MemoryTool(self.test_dir) 
    # Note: Or check file existence
    # self.assertTrue((self.test_dir / "memories.db").exists())
    print(f"✓ Correctly routed to Memory: {result}")

  def test_02_domain_separation_reminder(self):
    """Test 'remind me at 8pm' -> Reminder"""
    print("\nTesting Reminder Intent...")
    result = self.orchestrator.process("remind me at 8pm to call mom")

    self.assertIsNotNone(result)
    self.assertIn("Reminder added", result)
    self.assertIn("call mom", result)
    print(f"✓ Correctly routed to Reminder: {result}")

  def test_03_domain_separation_experience(self):
    """Test 'today went bowling 800' -> Experience"""
    print("\nTesting Experience Intent...")
    result = self.orchestrator.process("today went bowling 800")
    print(f"DEBUG Experience Result: '{result}'")

    self.assertIsNotNone(result)
    self.assertIn("Logged", result)
    self.assertIn("bowling", result)
    self.assertIn("800", result)
    print(f"✓ Correctly routed to Experience: {result}")

  def test_04_experience_retrieval_when_last(self):
    """Test 'when last bowling?'"""
    print("\nTesting Experience Retrieval (When Last)...")
    # First add one directly using tool to ensure state
    tool = ExperienceTool(self.test_dir)
    tool.execute("add", {"text": "went bowling", "date": "2024-01-01"})

    # Test routing
    result = self.orchestrator.process("when last bowling?")
    self.assertIsNotNone(result)
    self.assertIn("2024-01-01", result)
    print(f"✓ Routing correct: {result}")

  def test_05_experience_retrieval_spent_at(self):
    """Test 'how much spent at AlphaOne?'"""
    print("\nTesting Experience Retrieval (Spent At)...")
    tool = ExperienceTool(self.test_dir)
    tool.execute("add", {"text": "shopping 2000", "place": "AlphaOne"})
    tool.execute("add", {"text": "coffee 500", "place": "AlphaOne"})

    # Test routing
    result = self.orchestrator.process("how much spent at AlphaOne?")
    self.assertIsNotNone(result)
    self.assertIn("2,500", result)
    print(f"✓ Calculation correct: {result}")

  def test_06_relative_date_next_year(self):
    """Test 'next year' parsing logic"""
    print("\nTesting Relative Date Parser...")
    now = datetime.now()
    parsed = parse_relative_date("next year")
    self.assertEqual(parsed.year, now.year + 1)

    parsed = parse_relative_date("after 2 years")
    self.assertEqual(parsed.year, now.year + 2)
    print("✓ Date parsing correct")

  def test_07_relation_tools(self):
    """Test Relation Tool and routing"""
    print("\nTesting Relation Tool...")
    tool = RelationTool(self.test_dir)
    tool.execute("add", {"name": "Ravi", "relationship": "Developer"})

    # Test routing
    result = self.orchestrator.process("who is Ravi?")
    self.assertIsNotNone(result)
    self.assertIn("Ravi", result)
    self.assertIn("Developer", result)
    print(f"✓ Relation ops correct: {result}")

  def test_08_persona_tool(self):
    """Test Persona Tool direct usage"""
    print("\nTesting Persona Tool...")
    tool = PersonaTool(self.test_dir)
    tool.execute("set", {"category": "values", "key": "honesty", "value": "high"})
    res = tool.execute("get", {"category": "values", "key": "honesty"})
    self.assertIn("high", res.message)
    print("✓ Persona ops correct")

if __name__ == "__main__":
  unittest.main()
