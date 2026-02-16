
import unittest
import shutil
import tempfile
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

# Adjust path to import src
import sys
sys.path.append(str(Path(__file__).parent.parent))

from src.core.sync_manager import SyncManager
from src.core.recall_guard import RecallGuard
from src.agent.orchestrator import Orchestrator
from src.agent.tools.base import ToolResult

class TestUnifiedReliability(unittest.TestCase):
    
    def setUp(self):
        # Create temp data directory
        self.test_dir = Path(tempfile.mkdtemp())
        self.sync_manager = SyncManager(self.test_dir)
        
        # Initialize SQLite tables for testing
        # SyncManager maps 'memory' -> 'memories.db', 'experience' -> 'experiences.db'
        self._init_db("memories", "memories", "CREATE TABLE memories (id INTEGER PRIMARY KEY, text TEXT, category TEXT, tags TEXT, created_at TIMESTAMP)")
        self._init_db("experiences", "experiences", "CREATE TABLE experiences (id INTEGER PRIMARY KEY, text TEXT, date DATE, place TEXT, category TEXT, sentiment TEXT, people TEXT, amount REAL, created_at TIMESTAMP)")
        
    def tearDown(self):
        # Cleanup
        shutil.rmtree(self.test_dir)

    def _init_db(self, domain, table, schema):
        conn = self.sync_manager.get_connection(domain)
        print(f"DEBUG: Init DB {domain} at {self.test_dir / f'{domain}.db'}")
        cursor = conn.cursor()
        cursor.execute(schema)
        conn.commit()
        # Verify table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        print(f"DEBUG: Tables in {domain}: {tables}")
        conn.close()

    def test_sync_manager_write_read(self):
        """Test basic Write -> Read from SQLite via SyncManager"""
        print("\n[TEST] SyncManager Write & List")
        
        # Write
        data = {"text": "I like pizza", "category": "food", "tags": "love"}
        row_id = self.sync_manager.write("memory", "memories", data)
        self.assertTrue(row_id > 0)
        
        # Read (List)
        items = self.sync_manager.list("memory", "memories")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["text"], "I like pizza")
        print("✓ Write and Read successful")

    def test_sync_manager_delete(self):
        """Test Delete flow"""
        print("\n[TEST] SyncManager Delete")
        
        # Write 2 items
        self.sync_manager.write("memory", "memories", {"text": "A", "category": "test"})
        id_b = self.sync_manager.write("memory", "memories", {"text": "B", "category": "test"})
        
        # Delete B
        count = self.sync_manager.delete("memory", "memories", {"id": id_b})
        self.assertEqual(count, 1)
        
        # Verify
        items = self.sync_manager.list("memory", "memories")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["text"], "A")
        print("✓ Delete successful")

    def test_recall_guard_verification(self):
        """Test RecallGuard verifies against SQLite"""
        print("\n[TEST] RecallGuard Verification")
        
        # RecallGuard takes data_dir, not brain object (based on view_file checking)
        guard = RecallGuard(self.test_dir)
        
        # Case 1: Data exists
        self.sync_manager.write("memory", "memories", {"text": "I visited Mars", "category": "dream"})
        
        # Verify exact text
        result = guard.verify_result("I visited Mars", "memory")
        self.assertEqual(result, "I visited Mars")
        
        # Verify fuzzy text failure (simple checks) or success if fuzzy match implemented
        # Current implementation does strict equality or very simple fuzzy? 
        # RecallGuard logic: 
        # cursor.execute(f"SELECT * FROM {table} WHERE {text_col} LIKE ?", (f"%{text}%",))
        
        # Case 2: Hallucination (Data not in DB)
        result_fake = guard.verify_result("I visited Pluto", "memory")
        self.assertEqual(result_fake, "No record in database.")
        print("✓ RecallGuard enforced truth")

    @patch("src.agent.orchestrator.Orchestrator._call_llm")
    def test_orchestrator_routing(self, mock_llm):
        """Test Orchestrator deterministic routing (No LLM)"""
        print("\n[TEST] Orchestrator Routing")
        
        orch = Orchestrator(self.test_dir)
        
        # 1. Data Query (Direct DB) - Experiences
        # First add some data
        self.sync_manager.write("experience", "experiences", 
                               {"text": "Went to gym", "date": "2023-10-01", "place": "Gold Gym", "amount": 0.0})
        
        response = orch.process("show experiences")
        # ExperienceTool.stats returns a summary, e.g. "Total events: 1"
        self.assertIn("events", response.lower()) 
        # self.assertIn("Went to gym", response) # Stats doesn't show details usually
        
        # 2. Deterministic Action - Reminder Delete
        # Mock specific tools if they rely on other DBs not init in setUp
        # But Orchestrator inits tools which init their own DBs via SyncManager
        
        response = orch.process("delete reminder 'buy milk'")
        # Should return "No matching reminders" (since empty) but PROVE it routed to tool
        self.assertIn("No matching reminders", response) 
        
        print("✓ Orchestrator routing verified")

if __name__ == "__main__":
    unittest.main()
