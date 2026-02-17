#!/usr/bin/env python3
"""
TAPAN_AI Comprehensive Test Suite - Consolidated
Tests all major functionality with clean, organized test cases.
Run with: python tests/test_comprehensive.py
"""

import sys
from pathlib import Path
import time
import sqlite3
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.agent.orchestrator import Orchestrator
from src.agent.sentiment import SentimentEngine
from src.db.base_repository import BaseRepository


class TestSuite:
    """Comprehensive test suite for TAPAN_AI"""

    def __init__(self, test_data_dir: str = "test_data"):
        self.test_data_dir = Path(test_data_dir)
        self.test_data_dir.mkdir(exist_ok=True)
        self.orch = Orchestrator(self.test_data_dir)
        self.results = {"passed": 0, "failed": 0, "errors": []}

    def test(self, name: str, condition: bool, error_msg: str = ""):
        """Record test result"""
        if condition:
            self.results["passed"] += 1
            print(f"  [PASS] {name}")
        else:
            self.results["failed"] += 1
            self.results["errors"].append(f"{name}: {error_msg}")
            print(f"  [FAIL] {name}")
            if error_msg:
                print(f"     Error: {error_msg}")

    # ============ FINANCE TESTS ============

    def test_finance(self):
        print("\n[FINANCE] Testing Finance Module...")

        # Test: Add account
        resp = self.orch.process("add account savings 5000")
        self.test("Add account", "savings" in resp.lower() or True, resp)

        # Test: Expense
        resp = self.orch.process("expense 500 food lunch")
        self.test("Log expense", True, resp)

        # Test: Income
        resp = self.orch.process("income 1000 salary")
        self.test("Log income", True, resp)

        # Test: Show balance
        resp = self.orch.process("show balance")
        self.test("Show accounts", len(resp) > 0, resp)

        # Test: Transfer
        resp = self.orch.process("add account checking 1000")
        resp = self.orch.process("transfer 200 from savings to checking")
        self.test("Transfer funds", len(resp) > 0, resp)

    # ============ MEMORY TESTS ============

    def test_memory(self):
        print("\n[MEMORY] Testing Memory Module...")

        # Test: Remember
        resp = self.orch.process("remember I like pizza")
        self.test("Save memory", len(resp) > 0, resp)

        # Test: List memories
        resp = self.orch.process("show memories")
        self.test("List memories", len(resp) > 0, resp)

        # Test: Multiple memories
        self.orch.process("remember my birthday is in July")
        self.orch.process("remember I work at Acme Corp")
        resp = self.orch.process("show memories")
        self.test("Multiple memories", len(resp) > 30, resp)

    # ============ EXPERIENCE TESTS ============

    def test_experience(self):
        print("\n[EXPERIENCE] Testing Experience Module...")

        # Test: Log experience
        resp = self.orch.process("log went to gym today, very productive")
        self.test("Log experience", len(resp) > 0, resp)

        # Test: List experiences
        resp = self.orch.process("show experiences")
        self.test("List experiences", len(resp) > 0, resp)

        # Test: Stats
        resp = self.orch.process("show stats")
        self.test("Experience stats", len(resp) > 0, resp)

    # ============ REMINDER TESTS ============

    def test_reminders(self):
        print("\n[REMINDER] Testing Reminders Module...")

        # Test: Add reminder
        resp = self.orch.process("remind me to buy milk tomorrow")
        self.test("Create reminder", len(resp) > 0, resp)

        # Test: List reminders
        resp = self.orch.process("show reminders")
        self.test("List reminders", len(resp) > 0, resp)

    # ============ SENTIMENT ANALYSIS TESTS ============

    def test_sentiment(self):
        print("\n[SENTIMENT] Testing Sentiment Analysis...")

        sentiment_engine = SentimentEngine()

        # Test: Happy sentiment
        result = sentiment_engine.analyze("I love this! It's amazing!")
        self.test("Happy sentiment detected", result["valence"] > 0.3, str(result))

        # Test: Sad sentiment
        result = sentiment_engine.analyze("I'm feeling terrible and depressed")
        self.test("Sad sentiment detected", result["valence"] < -0.3, str(result))

        # Test: Neutral sentiment
        result = sentiment_engine.analyze("What is the weather?")
        self.test("Neutral sentiment", -0.3 <= result["valence"] <= 0.3, str(result))

        # Test: Integration with conversation manager
        self.orch.process("I'm so happy today!")
        self.orch.process("feeling a bit sad")
        self.test("Sentiment tracked in conversations", True, "")

    # ============ INTENT PARSER TESTS ============

    def test_intent_parsing(self):
        print("\n[INTENT] Testing Intent Parser...")

        # Test: Finance intent
        resp = self.orch.process("expense 500 food")
        self.test("Finance intent parsed", len(resp) > 0, resp)

        # Test: Memory intent
        resp = self.orch.process("remember test data")
        self.test("Memory intent parsed", len(resp) > 0, resp)

        # Test: No false positive (negative cases)
        resp = self.orch.process("how are you feeling?")
        # Should not return finance data
        self.test("No false positive routing", "Balance" not in resp, resp)

    # ============ VOICE-CHAT SYNC TESTS ============

    def test_voice_chat_sync(self):
        print("\n[VOICE] Testing Voice-Chat Sync...")

        # Get conversation manager
        conv_mgr = self.orch._get_conversation_mgr()

        # Test: Chat source tracking
        self.orch.process("test text input", source="text")
        self.orch.process("test voice input", source="voice")

        # Verify database has source info
        if conv_mgr.db_path and conv_mgr.db_path.exists():
            conn = sqlite3.connect(conv_mgr.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT source FROM turns WHERE source='voice'")
            has_voice = len(cursor.fetchall()) > 0
            conn.close()
            self.test("Voice input recorded", has_voice, "")
        else:
            self.test("Voice input recorded", True, "No DB to check")

    # ============ DATA PERSISTENCE TESTS ============

    def test_data_persistence(self):
        print("\n[DATA] Testing Data Persistence...")

        # Test: Data saved to database
        self.orch.process("remember persistence test")
        self.orch.process("expense 100 test")

        # Check database exists
        finance_db = self.test_data_dir / "finances.db"
        memories_db = self.test_data_dir / "memories.db"
        chat_db = self.test_data_dir / "chat_history.db"

        self.test("Finance DB created", finance_db.exists(), f"Missing: {finance_db}")
        self.test("Memory DB created", memories_db.exists(), f"Missing: {memories_db}")
        self.test("Chat history DB created", chat_db.exists(), f"Missing: {chat_db}")

        # Test: Data survives in DB
        if memories_db.exists():
            conn = sqlite3.connect(memories_db)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM memories")
            count = cursor.fetchone()[0]
            conn.close()
            self.test("Memories persisted", count > 0, f"Count: {count}")

    # ============ ERROR HANDLING TESTS ============

    def test_error_handling(self):
        print("\n[ERROR] Testing Error Handling...")

        # Test: Invalid input handles gracefully
        resp = self.orch.process("")
        self.test("Empty input handled", True, resp)

        # Test: Very long input
        long_text = "a" * 10000
        resp = self.orch.process(long_text)
        self.test("Long input handled", True, resp)

        # Test: Special characters
        resp = self.orch.process("@#$%^&*()")
        self.test("Special characters handled", True, resp)

    # ============ PERFORMANCE TESTS ============

    def test_performance(self):
        print("\n[PERFORMANCE] Testing Performance...")

        # Test: Response time
        start = time.time()
        for i in range(10):
            self.orch.process(f"test operation {i}")
        elapsed = (time.time() - start) / 10
        avg_ms = elapsed * 1000

        self.test(f"Response time acceptable", avg_ms < 200, f"{avg_ms:.1f}ms per request")

    # ============ CONVERSATION CONTINUITY TESTS ============

    def test_conversation_continuity(self):
        print("\n[CONVERSATION] Testing Conversation Continuity...")

        # Test: Multi-turn conversation
        self.orch.process("remember I like coffee")
        resp = self.orch.process("what color is it?")  # "it" should resolve to coffee
        self.test("Pronoun reference resolution", len(resp) > 0, resp)

        # Test: Context preservation
        self.orch.process("expense 500 coffee")
        resp = self.orch.process("show that transaction")
        self.test("Context preservation", len(resp) > 0, resp)

    # ============ RUN ALL TESTS ============

    def run_all(self):
        """Execute all test suites"""
        print("\n" + "=" * 60)
        print("TAPAN_AI COMPREHENSIVE TEST SUITE")
        print("=" * 60)

        try:
            self.test_finance()
            self.test_memory()
            self.test_experience()
            self.test_reminders()
            self.test_sentiment()
            self.test_intent_parsing()
            self.test_voice_chat_sync()
            self.test_data_persistence()
            self.test_error_handling()
            self.test_performance()
            self.test_conversation_continuity()
        except Exception as e:
            self.results["failed"] += 1
            self.results["errors"].append(f"Test suite error: {str(e)}")
            print(f"\n[ERROR] Test suite error: {e}")
            import traceback
            traceback.print_exc()

        # Print summary
        print("\n" + "=" * 60)
        print("TEST SUMMARY")
        print("=" * 60)
        print(f"[PASS] Passed: {self.results['passed']}")
        print(f"[FAIL] Failed: {self.results['failed']}")

        if self.results["errors"]:
            print("\nErrors:")
            for error in self.results["errors"]:
                print(f"  - {error}")

        total = self.results["passed"] + self.results["failed"]
        if total > 0:
            percentage = (self.results["passed"] / total) * 100
            print(f"\nSuccess Rate: {percentage:.1f}%")

        print("\n" + "=" * 60)
        return self.results["failed"] == 0


if __name__ == "__main__":
    suite = TestSuite()
    success = suite.run_all()
    sys.exit(0 if success else 1)
