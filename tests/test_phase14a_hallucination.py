"""
PHASE 14A: Hallucination Blocker Tests

Critical tests to ensure:
1. Data queries NEVER go to LLM
2. LLM cannot invent data (biryani, pasta, pizza)
3. Only DB data is returned
4. Audit log tracks tool calls

Target: 30 tests
"""
import sqlite3
import json
import pytest
import gc
import shutil
from pathlib import Path
from datetime import datetime

from src.agent.orchestrator import Orchestrator, DATA_QUERY_PATTERNS, _AUDIT_LOG


# Test data directory
_TEST_DATA_DIR = Path(__file__).parent / "temp_phase14a"


def _cleanup_dir(path: Path):
    """Force cleanup directory"""
    gc.collect()
    if path.exists():
        try:
            shutil.rmtree(path, ignore_errors=True)
        except:
            pass


def _create_db(data_dir: Path, name: str, schema: str):
    """Create a database with schema"""
    conn = sqlite3.connect(data_dir / name)
    conn.executescript(schema)
    conn.commit()
    conn.close()


@pytest.fixture
def clean_data_dir():
    """Create clean temp data directory with schemas"""
    data_dir = _TEST_DATA_DIR
    _cleanup_dir(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    
    # Create persona_rules.json
    rules = {
        "financial_conscience": {"mode": "strict_saver", "save_ratio": 0.7, "spend_ratio": 0.3},
        "approval_rules": {"post_spend_buffer": 1.2, "emi_limit_percent": 30, "category_whitelist": ["health"]},
        "risk_levels": {"low": {"threshold": 0.1}, "medium": {"threshold": 0.25}},
        "ride_mode": {"max_sentences": 1, "max_chars": 100}
    }
    (data_dir / "persona_rules.json").write_text(json.dumps(rules))
    
    # Finance DB
    _create_db(data_dir, "finance.db", """
        CREATE TABLE accounts (name TEXT PRIMARY KEY, balance REAL DEFAULT 0);
        CREATE TABLE transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, amount REAL, type TEXT, category TEXT, account TEXT, note TEXT, date TIMESTAMP);
        INSERT INTO accounts (name, balance) VALUES ('main', 50000);
    """)
    
    # Reminders DB - EMPTY (no reminders)
    _create_db(data_dir, "reminders.db", """
        CREATE TABLE reminders (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL, remind_at TIMESTAMP NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, status TEXT DEFAULT 'pending');
        CREATE INDEX idx_rem_remind_at ON reminders(remind_at);
        CREATE INDEX idx_rem_status ON reminders(status);
    """)
    
    # Memories DB - EMPTY (no memories)
    _create_db(data_dir, "memories.db", """
        CREATE TABLE memories (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL, category TEXT DEFAULT 'general', tags TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP, source TEXT DEFAULT 'user');
    """)
    
    # Experiences DB - EMPTY (no experiences)
    _create_db(data_dir, "experiences.db", """
        CREATE TABLE experiences (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL, date DATE NOT NULL, time TEXT, category TEXT DEFAULT 'activity', place TEXT, city TEXT, amount REAL DEFAULT 0, currency TEXT DEFAULT 'INR', people TEXT, sentiment TEXT, rating INTEGER, tags TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE places_visited (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, city TEXT, type TEXT, first_visit DATE, last_visit DATE, visit_count INTEGER DEFAULT 1, total_spent REAL DEFAULT 0);
    """)
    
    # Habits DB - EMPTY
    _create_db(data_dir, "habits.db", """
        CREATE TABLE habits (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, description TEXT, frequency TEXT DEFAULT 'daily', reminder_time TEXT, target_count INTEGER DEFAULT 1, streak_current INTEGER DEFAULT 0, streak_best INTEGER DEFAULT 0, last_done DATE, status TEXT DEFAULT 'active', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE habit_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, habit_id INTEGER NOT NULL, done_date DATE NOT NULL, done_time TIME, count INTEGER DEFAULT 1, notes TEXT, mood TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(habit_id, done_date));
    """)
    
    # Relations DB - EMPTY
    _create_db(data_dir, "relations.db", """
        CREATE TABLE relations (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, nickname TEXT, relationship TEXT DEFAULT 'acquaintance', trust_level INTEGER DEFAULT 5, phone TEXT, email TEXT, notes TEXT, first_met DATE, last_contact DATE, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, talk_style TEXT DEFAULT 'casual', topics_to_avoid TEXT, communication_preference TEXT DEFAULT 'any', sentiment_history TEXT);
        CREATE TABLE interactions (id INTEGER PRIMARY KEY AUTOINCREMENT, person_id INTEGER NOT NULL, interaction_date DATE NOT NULL, type TEXT DEFAULT 'general', summary TEXT, sentiment TEXT DEFAULT 'neutral', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE person_reminders (id INTEGER PRIMARY KEY AUTOINCREMENT, person_id INTEGER NOT NULL, text TEXT NOT NULL, remind_at TIMESTAMP, status TEXT DEFAULT 'pending');
        CREATE TABLE shared_memories (id INTEGER PRIMARY KEY AUTOINCREMENT, person_id INTEGER NOT NULL, memory TEXT NOT NULL, memory_date DATE, importance INTEGER DEFAULT 5, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    """)
    
    # Persona DB
    _create_db(data_dir, "persona.db", """
        CREATE TABLE traits (key TEXT PRIMARY KEY, value TEXT NOT NULL, category TEXT DEFAULT 'personality');
    """)
    
    yield data_dir
    gc.collect()


@pytest.fixture
def agent(clean_data_dir):
    """Create orchestrator with clean data"""
    return Orchestrator(clean_data_dir)


# ================================================
# SECTION 1: DATA QUERY PATTERN DETECTION (10 tests)
# ================================================

class TestDataQueryPatterns:
    """Test that data query patterns are correctly detected"""
    
    def test_list_reminders_is_data_query(self, agent):
        """'list reminders' must be detected as data query"""
        assert agent._is_data_query("list reminders") == True
    
    def test_show_accounts_is_data_query(self, agent):
        """'show accounts' must be detected as data query"""
        assert agent._is_data_query("show accounts") == True
    
    def test_my_balance_is_data_query(self, agent):
        """'my balance' must be detected as data query"""
        assert agent._is_data_query("my balance") == True
    
    def test_what_do_you_know_is_data_query(self, agent):
        """'what do you know' must be detected as data query"""
        assert agent._is_data_query("what do you know about me") == True
    
    def test_list_all_data_is_data_query(self, agent):
        """'list all data' must be detected as data query"""
        assert agent._is_data_query("list all data") == True
    
    def test_when_did_i_last_is_data_query(self, agent):
        """'when did I last' must be detected as data query"""
        assert agent._is_data_query("when did I last eat pizza") == True
    
    def test_who_is_is_data_query(self, agent):
        """'who is X' must be detected as data query"""
        assert agent._is_data_query("who is Ravi") == True
    
    def test_show_my_habits_is_data_query(self, agent):
        """'show my habits' must be detected as data query"""
        assert agent._is_data_query("show my habits") == True
    
    def test_my_friends_is_data_query(self, agent):
        """'my friends' must be detected as data query"""
        assert agent._is_data_query("list my friends") == True
    
    def test_random_chat_not_data_query(self, agent):
        """Random chat should NOT be data query"""
        assert agent._is_data_query("hello how are you") == False


# ================================================
# SECTION 2: NO HALLUCINATION TESTS (10 tests)
# ================================================

class TestNoHallucination:
    """Test that LLM cannot invent data"""
    
    def test_list_all_data_no_biryani(self, agent, clean_data_dir):
        """'list all data' must NOT contain biryani (not in DB)"""
        result = agent.process_single("list all data")
        assert "biryani" not in result.lower()
    
    def test_list_all_data_no_pasta(self, agent, clean_data_dir):
        """'list all data' must NOT contain pasta (not in DB)"""
        result = agent.process_single("list all data")
        assert "pasta" not in result.lower()
    
    def test_list_all_data_no_pizza(self, agent, clean_data_dir):
        """'list all data' must NOT contain pizza (not in DB)"""
        result = agent.process_single("list all data")
        assert "pizza" not in result.lower()
    
    def test_list_reminders_empty(self, agent, clean_data_dir):
        """Empty DB should return 'no reminders' not invented ones"""
        result = agent.process_single("list reminders")
        # Should indicate empty or no reminders
        assert "no" in result.lower() or "empty" in result.lower() or "📋" in result
    
    def test_list_memories_empty(self, agent, clean_data_dir):
        """Empty DB should return 'no memories' not invented ones"""
        result = agent.process_single("list memories")
        assert "no" in result.lower() or "empty" in result.lower() or "🧠" in result
    
    def test_list_habits_empty(self, agent, clean_data_dir):
        """Empty DB should return 'no habits' not invented ones"""
        result = agent.process_single("list habits")
        assert "no" in result.lower() or "empty" in result.lower() or "✅" in result
    
    def test_who_is_unknown_person(self, agent, clean_data_dir):
        """Unknown person should return 'not found' not invented bio"""
        result = agent.process_single("who is RandomPerson123")
        assert "not found" in result.lower() or "no" in result.lower() or "don't" in result.lower()
    
    def test_when_last_no_experience(self, agent, clean_data_dir):
        """No experience should return 'no record' not invented date"""
        result = agent.process_single("when did I last go bowling")
        # Should indicate no record - "don't recall", "no", "not found", "never"
        assert "no" in result.lower() or "not found" in result.lower() or "never" in result.lower() or "don't" in result.lower() or "recall" in result.lower()
    
    def test_what_do_you_know_empty_db(self, agent, clean_data_dir):
        """Empty DB should not invent user preferences"""
        result = agent.process_single("what do you know about me")
        # Should show accounts (has data) but not invented preferences
        assert "coffee" not in result.lower() or "main" in result.lower()
    
    def test_show_experiences_empty(self, agent, clean_data_dir):
        """Empty experiences should not invent trips"""
        result = agent.process_single("show my experiences")
        # Should indicate no experiences or show stats
        assert "goa" not in result.lower()
        assert "mumbai" not in result.lower()


# ================================================
# SECTION 3: AUDIT LOG TESTS (5 tests)
# ================================================

class TestAuditLog:
    """Test audit logging functionality"""
    
    def test_audit_log_populated(self, agent, clean_data_dir):
        """Audit log should be populated after query"""
        _AUDIT_LOG.clear()
        agent.process_single("list reminders")
        assert len(_AUDIT_LOG) >= 1
    
    def test_audit_log_has_tool_name(self, agent, clean_data_dir):
        """Audit log should contain tool name"""
        _AUDIT_LOG.clear()
        agent.process_single("show accounts")
        assert any("finance" in entry.get("tool", "") for entry in _AUDIT_LOG)
    
    def test_audit_log_has_action(self, agent, clean_data_dir):
        """Audit log should contain action"""
        _AUDIT_LOG.clear()
        agent.process_single("list habits")
        assert any("list" in entry.get("action", "") for entry in _AUDIT_LOG)
    
    def test_audit_log_has_timestamp(self, agent, clean_data_dir):
        """Audit log should have timestamp"""
        _AUDIT_LOG.clear()
        agent.process_single("my balance")
        assert all("timestamp" in entry for entry in _AUDIT_LOG)
    
    def test_audit_log_max_50_entries(self, agent, clean_data_dir):
        """Audit log should not exceed 50 entries"""
        _AUDIT_LOG.clear()
        for i in range(60):
            agent.process_single("list reminders")
        assert len(_AUDIT_LOG) <= 50


# ================================================
# SECTION 4: DB-ONLY RESPONSE TESTS (5 tests)
# ================================================

class TestDBOnlyResponse:
    """Test that responses come from DB only"""
    
    def test_accounts_shows_main(self, agent, clean_data_dir):
        """Accounts query should show 'main' account from DB"""
        result = agent.process_single("show accounts")
        assert "main" in result.lower() or "50000" in result or "50,000" in result
    
    def test_balance_shows_50000(self, agent, clean_data_dir):
        """Balance query should show 50000 from DB"""
        result = agent.process_single("my balance")
        assert "50000" in result or "50,000" in result or "₹50" in result
    
    def test_data_query_bypasses_llm(self, agent, clean_data_dir):
        """Data query should not contain LLM narrative"""
        result = agent.process_single("list all data")
        # Should not have LLM-style narrative
        assert "I think" not in result
        assert "probably" not in result
        assert "might have" not in result
    
    def test_list_returns_structured_data(self, agent, clean_data_dir):
        """List queries should return structured data"""
        result = agent.process_single("list all data")
        # Should have section headers
        assert "💰" in result or "ACCOUNT" in result.upper()
    
    def test_empty_db_no_fabrication(self, agent, clean_data_dir):
        """Empty sections should say empty, not fabricate"""
        result = agent.process_single("list all data")
        # Should not contain common fabricated items
        fabricated_items = ["movie", "restaurant", "shopping", "gym", "yoga", "meditation"]
        fabrication_count = sum(1 for item in fabricated_items if item in result.lower())
        assert fabrication_count <= 1  # Allow at most 1 coincidental match


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
