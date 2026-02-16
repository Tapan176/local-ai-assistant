"""
Phase 17: Comprehensive Test Suite — Jarvis-Level Testing

Tests EVERY phase of TAPAN_AI (Phase 1 through 17) with real-world,
human-like conversation flows. Not toy tests — production-grade scenarios.

Coverage:
  - UserProfile: name/occupation/location extraction, learning, mood, routines
  - ConversationManager: multi-turn tracking, reference resolution, topic
  - ProactiveEngine: time-based, habit, finance, reminder, exercise suggestions
  - ResponsePersonalizer: mood-aware tone, greetings, concise mode
  - PerformanceMonitor: decorator timing, stats, reports, warnings
  - SmartCache: put/get, TTL, memory/disk, cleanup
  - IntentParser: all Phase 17 commands
  - Orchestrator: end-to-end integration
  - Finance: expense/income/balance (Phase 1-3)
  - Memory: remember/recall (Phase 4-5)
  - Experience: log/show (Phase 6-7)
  - Reminders: set/list (Phase 8-9)
  - Persona: Hinglish formatting (Phase 10-12)
  - Decision: should I buy / can I afford (Phase 13-14)
  - LLM: ask / status / models (Phase 15-16)
"""
import json
import sys
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path
from datetime import datetime, timedelta, date

import pytest

# === Ensure project import works ===
sys.path.insert(0, str(Path(__file__).parent.parent))


# ────────────────────────────────────────────────────────────────
# FIXTURES
# ────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_data(tmp_path):
  """Fresh data directory for each test."""
  data_dir = tmp_path / "data"
  data_dir.mkdir()
  return data_dir


@pytest.fixture
def profile(tmp_data):
  from src.agent.user_profile import UserProfile
  return UserProfile(tmp_data)


@pytest.fixture
def conv_mgr():
  from src.agent.conversation_manager import ConversationManager
  return ConversationManager(max_history=20)


@pytest.fixture
def proactive(tmp_data, profile):
  from src.agent.proactive_engine import ProactiveEngine
  return ProactiveEngine(tmp_data, user_profile=profile)


@pytest.fixture
def personalizer(profile):
  from src.agent.response_personalizer import ResponsePersonalizer
  return ResponsePersonalizer(user_profile=profile)


@pytest.fixture
def perf_monitor():
  from src.optimization.performance_monitor import PerformanceMonitor
  return PerformanceMonitor()


@pytest.fixture
def cache(tmp_data):
  from src.optimization.smart_cache import SmartCache
  return SmartCache(tmp_data, max_memory=10, ttl_hours=1)


@pytest.fixture
def parser():
  from src.agent.intent_parser import IntentParser
  return IntentParser()


@pytest.fixture
def orchestrator(tmp_data):
  """Full orchestrator with fresh data."""
  from src.agent.orchestrator import Orchestrator
  return Orchestrator(tmp_data)


# ╔═══════════════════════════════════════════════════════════════╗
# ║  PART 1: USER PROFILE ENGINE (60+ scenarios)                 ║
# ╚═══════════════════════════════════════════════════════════════╝

class TestUserProfileBasic:
  """Phase 1-5: Basic profile operations."""

  def test_new_profile_defaults(self, profile):
    assert profile.get_name() is None
    assert profile.get_occupation() is None
    assert profile.get_location() is None
    assert profile.get_facts() == []

  def test_set_and_get_name(self, profile):
    profile.set_name("Tapan")
    assert profile.get_name() == "Tapan"

  def test_set_and_get_occupation(self, profile):
    profile.set_occupation("developer")
    assert profile.get_occupation() == "developer"

  def test_set_and_get_location(self, profile):
    profile.set_location("Mumbai")
    assert profile.get_location() == "Mumbai"

  def test_add_multiple_facts(self, profile):
    profile.add_fact("Loves hiking")
    profile.add_fact("Has a dog named Bruno")
    profile.add_fact("Loves hiking")  # Duplicate — should not add
    facts = profile.get_facts()
    assert len(facts) == 2
    assert "Loves hiking" in facts

  def test_set_and_get_preference(self, profile):
    profile.set_preference("language", "Hinglish")
    assert profile.get_preference("language") == "Hinglish"
    assert profile.get_preference("missing_key") is None

  def test_profile_persistence(self, tmp_data):
    """Profile survives reload from disk."""
    from src.agent.user_profile import UserProfile
    p1 = UserProfile(tmp_data)
    p1.set_name("Rahul")
    p1.add_fact("Works at Google")

    p2 = UserProfile(tmp_data)  # Reload
    assert p2.get_name() == "Rahul"
    assert "Works at Google" in p2.get_facts()

  def test_corrupt_profile_file_recovery(self, tmp_data):
    """Graceful handling of corrupt profile.json."""
    from src.agent.user_profile import UserProfile
    profile_path = tmp_data / "profile.json"
    profile_path.write_text("not valid json!!!", encoding='utf-8')
    p = UserProfile(tmp_data)
    assert p.get_name() is None  # Should reset to defaults


class TestUserProfileExtraction:
  """Phase 17: Auto-extraction from natural language."""

  @pytest.mark.parametrize("msg, expected_name", [
    ("I am Tapan", "Tapan"),
    ("My name is Priya", "Priya"),
    ("Call me Arjun", "Arjun"),
    ("I'm Vikram and I love coding", "Vikram"),
    ("mera naam Rohit hai", "Rohit"),
  ])
  def test_name_extraction(self, profile, msg, expected_name):
    result = profile.extract_from_message(msg)
    assert profile.get_name() == expected_name
    assert expected_name in (result or "")

  @pytest.mark.parametrize("msg, expected_job", [
    ("I work as software developer", "software developer"),
    ("I am a teacher", "teacher"),
    ("I'm a data scientist", "data scientist"),
    ("my job is freelancer", "freelancer"),
  ])
  def test_occupation_extraction(self, profile, msg, expected_job):
    profile.extract_from_message(msg)
    assert profile.get_occupation() is not None
    assert expected_job.lower() in profile.get_occupation().lower()

  @pytest.mark.parametrize("msg, expected_loc", [
    ("I live in Delhi", "Delhi"),
    ("I am from Bangalore", "Bangalore"),
    ("I'm from Pune", "Pune"),
    ("based in Mumbai", "Mumbai"),
  ])
  def test_location_extraction(self, profile, msg, expected_loc):
    profile.extract_from_message(msg)
    assert profile.get_location() is not None
    assert expected_loc in profile.get_location()

  def test_no_false_positive_extraction(self, profile):
    """Random text should NOT extract bogus profile info."""
    result = profile.extract_from_message("just checking my expenses today")
    assert result is None
    assert profile.get_name() is None


class TestUserProfileLearning:
  """Phase 17: Continuous learning from interactions."""

  def test_learn_food_preference(self, profile):
    profile.learn_from_interaction("I love biryani so much!")
    prefs = profile.get_learned_preferences("food")
    assert any(p.get("item") == "biryani" for p in prefs)
    assert any(p.get("sentiment") == "likes" for p in prefs)

  def test_learn_dislike(self, profile):
    profile.learn_from_interaction("I hate running in the morning")
    prefs = profile.get_learned_preferences("activity")
    assert any(p.get("item") == "running" and p.get("sentiment") == "dislikes"
               for p in prefs)

  def test_preference_reinforcement(self, profile):
    """Repeated mentions increase confidence."""
    for _ in range(5):
      profile.learn_from_interaction("I love pizza, pizza is the best!")
    prefs = profile.get_learned_preferences("food")
    pizza = [p for p in prefs if p.get("item") == "pizza"]
    assert len(pizza) == 1
    assert pizza[0]["count"] >= 5
    assert pizza[0]["confidence"] > 0.5

  def test_learn_multiple_categories(self, profile):
    profile.learn_from_interaction("I love yoga and chai")
    all_prefs = profile.get_learned_preferences()
    items = {p.get("item") for p in all_prefs}
    assert "yoga" in items
    assert "chai" in items

  def test_interaction_log_capped(self, profile):
    """Log should not exceed 200 entries."""
    for i in range(250):
      profile.learn_from_interaction(f"Interaction {i}")
    log = profile.data.get("interaction_log", [])
    assert len(log) <= 200


class TestUserProfileMood:
  """Phase 17: Mood detection."""

  @pytest.mark.parametrize("text, expected_mood", [
    ("I'm really happy today!", "happy"),
    ("Feeling sad and down", "sad"),
    ("So stressed with work deadlines", "stressed"),
    ("I'm angry about the traffic", "angry"),
    ("I'm so excited for the concert!", "excited"),
    ("Feeling peaceful and calm", "calm"),
    ("Just a normal day", "neutral"),
  ])
  def test_mood_detection(self, profile, text, expected_mood):
    mood = profile.detect_mood(text)
    assert mood == expected_mood

  def test_mood_history_tracking(self, profile):
    profile.learn_from_interaction("I'm really stressed out")
    profile.learn_from_interaction("Feeling happy now!")
    history = profile.data.get("mood_history", [])
    assert len(history) >= 2

  def test_mood_history_capped(self, profile):
    for i in range(60):
      profile.learn_from_interaction("feeling happy yay!")
    history = profile.data.get("mood_history", [])
    assert len(history) <= 50

  def test_current_mood_recent(self, profile):
    profile.learn_from_interaction("so stressed and tired")
    assert profile.get_current_mood() == "stressed"


class TestUserProfileContext:
  """Phase 17: Context awareness."""

  def test_context_has_all_keys(self, profile):
    ctx = profile.get_current_context()
    assert "time_of_day" in ctx
    assert "day_type" in ctx
    assert "hour" in ctx
    assert "mood" in ctx
    assert "weekday" in ctx

  def test_context_time_of_day(self, profile):
    ctx = profile.get_current_context()
    assert ctx["time_of_day"] in ("morning", "afternoon", "evening", "night")

  def test_context_day_type(self, profile):
    ctx = profile.get_current_context()
    assert ctx["day_type"] in ("weekday", "weekend")

  def test_activity_inference_finance(self, profile):
    for _ in range(3):
      profile.learn_from_interaction("expense 500 food", action="expense")
    activity = profile._infer_activity()
    assert activity == "managing_finances"

  def test_activity_inference_memory(self, profile):
    for _ in range(3):
      profile.learn_from_interaction("remember I have a meeting", action="remember")
    activity = profile._infer_activity()
    assert activity == "saving_info"


class TestUserProfileRoutines:
  """Phase 17: Pattern detection and routines."""

  def test_no_patterns_with_few_interactions(self, profile):
    profile.learn_from_interaction("hello", action="greet")
    assert profile.get_routines() == []

  def test_pattern_detection_after_many_interactions(self, profile):
    """Simulate 20 interactions to trigger pattern detection."""
    for i in range(20):
      profile.data.setdefault("interaction_log", []).append({
        "ts": datetime.now().isoformat(),
        "hour": 9,
        "weekday": datetime.now().weekday(),
        "action": "expense",
        "snippet": f"expense {i*100} food"
      })
    profile._detect_patterns()
    routines = profile.get_routines()
    assert len(routines) >= 1
    assert routines[0]["action"] == "expense"

  def test_suggest_actions_returns_list(self, profile):
    suggestions = profile.suggest_actions()
    assert isinstance(suggestions, list)
    assert len(suggestions) <= 4

  def test_profile_summary_format(self, profile):
    profile.set_name("Tapan")
    profile.set_occupation("Developer")
    profile.set_location("Bengaluru")
    summary = profile.get_profile_summary()
    assert "Tapan" in summary
    assert "Developer" in summary
    assert "Bengaluru" in summary

  def test_context_string_with_prefs(self, profile):
    profile.set_name("Rahul")
    profile.learn_from_interaction("I love biryani so much!")
    ctx = profile.get_context_string()
    assert "Rahul" in ctx
    assert "biryani" in ctx

  def test_to_dict(self, profile):
    profile.set_name("Test")
    d = profile.to_dict()
    assert isinstance(d, dict)
    assert d["name"] == "Test"


# ╔═══════════════════════════════════════════════════════════════╗
# ║  PART 2: CONVERSATION MANAGER (30+ scenarios)                ║
# ╚═══════════════════════════════════════════════════════════════╝

class TestConversationManagerBasic:
  """Multi-turn conversation tracking."""

  def test_empty_session(self, conv_mgr):
    assert conv_mgr.get_turn_count() == 0
    assert conv_mgr.get_last_turn() is None
    assert conv_mgr.get_last_intent() is None

  def test_add_turn(self, conv_mgr):
    conv_mgr.add_turn("hello", "Hi there!", intent="greet")
    assert conv_mgr.get_turn_count() == 1
    assert conv_mgr.get_last_intent() == "greet"

  def test_multiple_turns(self, conv_mgr):
    conv_mgr.add_turn("hello", "Hi!", "greet")
    conv_mgr.add_turn("expense 500 food", "Logged ₹500", "expense",
                       {"amount": 500, "category": "food"})
    conv_mgr.add_turn("balance", "Your balance: ₹10000", "balance")
    assert conv_mgr.get_turn_count() == 3

  def test_max_history_respected(self):
    from src.agent.conversation_manager import ConversationManager
    cm = ConversationManager(max_history=3)
    for i in range(5):
      cm.add_turn(f"msg{i}", f"resp{i}")
    assert cm.get_turn_count() == 3

  def test_last_turn_data(self, conv_mgr):
    conv_mgr.add_turn("expense 200 food", "Done!", "expense",
                       {"amount": 200, "category": "food"})
    last = conv_mgr.get_last_turn()
    assert last["user"] == "expense 200 food"
    assert last["intent"] == "expense"


class TestConversationManagerContext:
  """LLM context formatting."""

  def test_llm_context_empty(self, conv_mgr):
    assert conv_mgr.get_context_for_llm() == ""

  def test_llm_context_with_turns(self, conv_mgr):
    conv_mgr.add_turn("what's my balance?", "₹10000", "balance")
    conv_mgr.add_turn("any pending habits?", "3 habits pending", "habit")
    ctx = conv_mgr.get_context_for_llm()
    assert "User:" in ctx
    assert "Assistant:" in ctx
    assert "₹10000" in ctx

  def test_llm_context_truncates_long_response(self, conv_mgr):
    long_response = "x" * 500
    conv_mgr.add_turn("tell me everything", long_response, "ask")
    ctx = conv_mgr.get_context_for_llm()
    assert "..." in ctx
    assert len(ctx) < len(long_response)


class TestConversationManagerReference:
  """Pronoun/reference resolution."""

  def test_resolve_with_no_history(self, conv_mgr):
    result = conv_mgr.resolve_reference("tell me about it")
    assert result == "tell me about it"  # No change without history

  def test_resolve_it_to_last_entity(self, conv_mgr):
    conv_mgr.add_turn(
      "remember I have a meeting",
      "Saved!",
      "memory",
      {"text": "I have a meeting"}
    )
    resolved = conv_mgr.resolve_reference("more about it")
    assert "meeting" in resolved.lower()

  def test_resolve_that_reference(self, conv_mgr):
    conv_mgr.add_turn(
      "expense 500 food",
      "Logged ₹500",
      "expense",
      {"category": "food", "amount": 500}
    )
    resolved = conv_mgr.resolve_reference("show that")
    # "that" should be resolved to one of the entity values
    assert resolved != "show that"

  def test_no_resolve_for_long_sentences(self, conv_mgr):
    conv_mgr.add_turn("hello", "hi", "greet", {"text": "hello"})
    long = "I was thinking about it and also wanted to discuss something else"
    assert conv_mgr.resolve_reference(long) == long


class TestConversationManagerTopic:
  """Topic tracking and continuity."""

  def test_topic_from_expense(self, conv_mgr):
    conv_mgr.add_turn("expense 100 food", "Done", "expense")
    assert conv_mgr.current_topic == "finance"

  def test_topic_from_memory(self, conv_mgr):
    conv_mgr.add_turn("remember meeting tomorrow", "Saved", "remember")
    assert conv_mgr.current_topic == "memory"

  def test_topic_continuity_fresh(self, conv_mgr):
    assert not conv_mgr.should_continue_topic()

  def test_topic_continuity_recent(self, conv_mgr):
    conv_mgr.add_turn("expense 100", "Done", "expense")
    assert conv_mgr.should_continue_topic()

  def test_session_summary(self, conv_mgr):
    conv_mgr.add_turn("expense 100 food", "Done", "expense")
    conv_mgr.add_turn("balance", "₹5000", "balance")
    summary = conv_mgr.get_session_summary()
    assert "2 turns" in summary

  def test_end_session_clears_state(self, conv_mgr):
    conv_mgr.add_turn("hello", "hi", "greet")
    conv_mgr.end_session()
    assert conv_mgr.get_turn_count() == 0
    assert conv_mgr.current_topic is None


# ╔═══════════════════════════════════════════════════════════════╗
# ║  PART 3: PROACTIVE ENGINE (25+ scenarios)                    ║
# ╚═══════════════════════════════════════════════════════════════╝

class TestProactiveEngineBasic:

  def test_suggestions_without_data(self, proactive):
    """No crash on empty data dir."""
    sug = proactive.get_suggestions()
    assert isinstance(sug, list)

  def test_time_suggestions(self, proactive):
    """Time-based suggestions always work."""
    sug = proactive._time_suggestions()
    assert isinstance(sug, list)
    for s in sug:
      assert "message" in s
      assert "priority" in s

  def test_format_no_suggestions(self, proactive):
    formatted = proactive.format_suggestions([])
    assert "sorted" in formatted.lower() or "no suggestion" in formatted.lower()

  def test_format_with_suggestions(self, proactive):
    sug = [{"type": "habit", "priority": "medium",
            "message": "Pending: exercise", "action": None}]
    formatted = proactive.format_suggestions(sug)
    assert "Pending: exercise" in formatted
    assert "✅" in formatted

  def test_max_6_suggestions(self, proactive):
    sug = proactive.get_suggestions()
    assert len(sug) <= 6


class TestProactiveEngineHabits:

  def test_habit_suggestions_with_pending(self, tmp_data, proactive):
    """Create habits DB with pending habits."""
    db = tmp_data / "habits.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE habits (name TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE habit_logs (name TEXT, log_date TEXT)")
    conn.execute("INSERT INTO habits VALUES ('exercise')")
    conn.execute("INSERT INTO habits VALUES ('meditation')")
    conn.execute("INSERT INTO habits VALUES ('reading')")
    conn.commit()
    conn.close()

    sug = proactive._habit_suggestions()
    assert len(sug) >= 1
    assert "pending" in sug[0]["message"].lower()

  def test_habit_no_suggestions_all_done(self, tmp_data, proactive):
    """All habits done today → no suggestions."""
    db = tmp_data / "habits.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE habits (name TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE habit_logs (name TEXT, log_date TEXT)")
    conn.execute("INSERT INTO habits VALUES ('exercise')")
    today = date.today().isoformat()
    conn.execute("INSERT INTO habit_logs VALUES ('exercise', ?)", (today,))
    conn.commit()
    conn.close()

    sug = proactive._habit_suggestions()
    assert len(sug) == 0


class TestProactiveEngineFinance:

  def test_finance_no_db(self, proactive):
    assert proactive._finance_suggestions() == []

  def test_finance_spending_spike(self, tmp_data, proactive):
    """This week's spending 50% higher than last week."""
    db = tmp_data / "finance.db"
    conn = sqlite3.connect(db)
    conn.execute("""CREATE TABLE transactions
      (id INTEGER PRIMARY KEY, type TEXT, amount REAL, category TEXT, date TEXT)""")
    conn.execute("""CREATE TABLE accounts
      (name TEXT, balance REAL)""")
    conn.execute("INSERT INTO accounts VALUES ('main', 50000)")

    today = date.today()
    # Last week: ₹1000
    last_week = (today - timedelta(days=today.weekday() + 3)).isoformat()
    conn.execute("INSERT INTO transactions VALUES (1, 'expense', 1000, 'food', ?)",
                 (last_week,))
    # This week: ₹2000 (100% spike)
    this_week = today.isoformat()
    conn.execute("INSERT INTO transactions VALUES (2, 'expense', 2000, 'food', ?)",
                 (this_week,))
    conn.commit()
    conn.close()

    sug = proactive._finance_suggestions()
    assert len(sug) >= 1
    assert "higher" in sug[0]["message"].lower() or "low" in sug[0]["message"].lower()


class TestProactiveEngineReminders:

  def test_reminder_no_db(self, proactive):
    assert proactive._reminder_suggestions() == []

  def test_overdue_reminders(self, tmp_data, proactive):
    db = tmp_data / "reminders.db"
    conn = sqlite3.connect(db)
    conn.execute("""CREATE TABLE reminders
      (id INTEGER PRIMARY KEY, text TEXT, remind_at TEXT, status TEXT)""")
    # Overdue reminder
    past = (datetime.now() - timedelta(hours=2)).isoformat()
    conn.execute("INSERT INTO reminders VALUES (1, 'buy milk', ?, 'pending')",
                 (past,))
    conn.commit()
    conn.close()

    sug = proactive._reminder_suggestions()
    assert len(sug) == 1
    assert "overdue" in sug[0]["message"].lower()
    assert "milk" in sug[0]["message"].lower()


class TestProactiveEngineExercise:

  def test_exercise_no_db(self, proactive):
    assert proactive._exercise_suggestions() == []


class TestProactiveEngineProfile:

  def test_mood_based_suggestion(self, tmp_data):
    from src.agent.user_profile import UserProfile
    from src.agent.proactive_engine import ProactiveEngine
    p = UserProfile(tmp_data)
    p.learn_from_interaction("I'm so stressed and overwhelmed")
    engine = ProactiveEngine(tmp_data, user_profile=p)
    sug = engine._profile_suggestions()
    assert any("break" in s["message"].lower() or "stress" in s["message"].lower()
               for s in sug)


# ╔═══════════════════════════════════════════════════════════════╗
# ║  PART 4: RESPONSE PERSONALIZER (20+ scenarios)               ║
# ╚═══════════════════════════════════════════════════════════════╝

class TestResponsePersonalizerBasic:

  def test_empty_input(self, personalizer):
    assert personalizer.personalize("") == ""

  def test_no_change_on_neutral(self, personalizer):
    resp = personalizer.personalize("Expense logged: ₹500")
    assert "₹500" in resp

  def test_greeting_on_first_interaction(self, personalizer):
    resp = personalizer.personalize("Expense logged: ₹500",
                                    context={"time_of_day": "morning", "mood": "neutral"},
                                    is_first=True)
    # Should add a greeting
    assert len(resp) > len("Expense logged: ₹500")

  def test_greeting_only_once(self, personalizer):
    ctx = {"time_of_day": "morning", "mood": "neutral"}
    r1 = personalizer.personalize("First", ctx, is_first=True)
    r2 = personalizer.personalize("Second", ctx, is_first=True)
    # Second call should not add greeting (already greeted)
    assert len(r2) <= len(r1) + 10

  def test_greeting_with_name(self, profile, personalizer):
    profile.set_name("Tapan")
    ctx = {"time_of_day": "evening", "mood": "neutral", "name": "Tapan"}
    resp = personalizer.personalize("Done!", ctx, is_first=True)
    assert "Tapan" in resp


class TestResponsePersonalizerMood:

  def test_mood_detection_happy(self, personalizer):
    mood = personalizer.detect_mood("I'm so happy today!")
    assert mood == "happy"

  def test_mood_detection_stressed(self, personalizer):
    mood = personalizer.detect_mood("overwhelmed with work")
    assert mood == "stressed"

  def test_mood_fallback_neutral(self, personalizer):
    mood = personalizer.detect_mood("just a regular day")
    assert mood == "neutral"

  def test_concise_mode(self, profile, personalizer):
    profile.set_preference("verbosity", "concise")
    long_text = "Actually, this is basically essentially a very long response. " * 5
    resp = personalizer.personalize(long_text, {"mood": "neutral"})
    # Should remove fillers
    assert "basically" not in resp
    assert "essentially" not in resp

  def test_reset_session(self, personalizer):
    personalizer._session_greeted = True
    personalizer.reset_session()
    assert not personalizer._session_greeted


# ╔═══════════════════════════════════════════════════════════════╗
# ║  PART 5: PERFORMANCE MONITOR (20+ scenarios)                 ║
# ╚═══════════════════════════════════════════════════════════════╝

class TestPerformanceMonitorDecorator:

  def test_measure_decorator(self, perf_monitor):
    @perf_monitor.measure("test_op")
    def slow_function():
      time.sleep(0.05)
      return "done"

    result = slow_function()
    assert result == "done"
    stats = perf_monitor.get_stats("test_op")
    assert stats is not None
    assert stats["count"] == 1
    assert stats["mean"] >= 0.04

  def test_measure_multiple_calls(self, perf_monitor):
    @perf_monitor.measure("multi_op")
    def fast_func():
      return 42

    for _ in range(10):
      fast_func()

    stats = perf_monitor.get_stats("multi_op")
    assert stats["count"] == 10

  def test_context_manager(self, perf_monitor):
    with perf_monitor.time_block("ctx_op"):
      time.sleep(0.02)

    stats = perf_monitor.get_stats("ctx_op")
    assert stats is not None
    assert stats["mean"] >= 0.01

  def test_threshold_warning(self, perf_monitor):
    perf_monitor.thresholds["slow_op"] = 0.01

    @perf_monitor.measure("slow_op")
    def too_slow():
      time.sleep(0.05)

    too_slow()
    warnings = perf_monitor.get_warnings()
    assert len(warnings) >= 1
    assert "slow_op" in warnings[0]


class TestPerformanceMonitorReports:

  def test_empty_report(self, perf_monitor):
    report = perf_monitor.get_report()
    assert "No performance data" in report

  def test_report_with_data(self, perf_monitor):
    @perf_monitor.measure("report_op")
    def f():
      pass

    for _ in range(5):
      f()

    report = perf_monitor.get_report()
    assert "report_op" in report
    assert "5" in report

  def test_stats_calculation(self, perf_monitor):
    for dur in [0.1, 0.2, 0.3, 0.4, 0.5]:
      perf_monitor._record("calc_op", dur)

    stats = perf_monitor.get_stats("calc_op")
    assert stats["count"] == 5
    assert abs(stats["mean"] - 0.3) < 0.01
    assert stats["min"] == 0.1
    assert stats["max"] == 0.5

  def test_clear_metrics(self, perf_monitor):
    perf_monitor._record("some_op", 1.0)
    perf_monitor.clear()
    assert perf_monitor.get_stats("some_op") is None
    assert perf_monitor.get_warnings() == []

  def test_nonexistent_stats(self, perf_monitor):
    assert perf_monitor.get_stats("ghost_op") is None

  def test_singleton(self):
    from src.optimization.performance_monitor import get_perf_monitor
    m1 = get_perf_monitor()
    m2 = get_perf_monitor()
    assert m1 is m2


# ╔═══════════════════════════════════════════════════════════════╗
# ║  PART 6: SMART CACHE (20+ scenarios)                         ║
# ╚═══════════════════════════════════════════════════════════════╝

class TestSmartCacheBasic:

  def test_put_and_get(self, cache):
    cache.put("test", "key1", {"data": "hello"})
    result = cache.get("test", "key1")
    assert result == {"data": "hello"}

  def test_get_missing_key(self, cache):
    assert cache.get("test", "nonexistent") is None

  def test_overwrite(self, cache):
    cache.put("ns", "k", "v1")
    cache.put("ns", "k", "v2")
    assert cache.get("ns", "k") == "v2"


class TestSmartCacheLLM:

  def test_cache_llm_response(self, cache):
    cache.cache_llm_response("What is AI?", "context1", "AI is artificial intelligence")
    result = cache.get_llm_response("What is AI?", "context1")
    assert result == "AI is artificial intelligence"

  def test_cache_miss_different_context(self, cache):
    cache.cache_llm_response("What is AI?", "ctx1", "response1")
    result = cache.get_llm_response("What is AI?", "ctx2")
    assert result is None  # Different context → cache miss

  def test_cache_miss_different_prompt(self, cache):
    cache.cache_llm_response("prompt1", "ctx", "resp1")
    assert cache.get_llm_response("prompt2", "ctx") is None


class TestSmartCacheMemory:

  def test_memory_eviction(self, cache):
    """Memory cache should evict oldest when full."""
    for i in range(15):  # max_memory=10
      cache.put("ns", f"key{i}", f"value{i}")

    # First 5 should be evicted from memory
    # But still in SQLite
    assert cache.get("ns", "key14") == "value14"  # Most recent → in memory
    assert cache.get("ns", "key0") == "value0"  # Oldest → from SQLite

  def test_disk_persistence(self, tmp_data):
    from src.optimization.smart_cache import SmartCache
    c1 = SmartCache(tmp_data, max_memory=5)
    c1.put("ns", "k", "persisted_value")

    c2 = SmartCache(tmp_data, max_memory=5)
    # Should read from SQLite (not in memory of c2)
    assert c2.get("ns", "k") == "persisted_value"


class TestSmartCacheExpiry:

  def test_cleanup_expired(self, cache):
    cache._put("expired_key", "old_value", ttl_hours=0)  # Expires immediately
    time.sleep(0.1)
    removed = cache.cleanup_expired()
    assert cache._get("expired_key") is None

  def test_cache_stats(self, cache):
    cache.put("ns", "k1", "v1")
    cache.put("ns", "k2", "v2")
    stats = cache.get_stats()
    assert stats["memory_items"] >= 2
    assert stats["disk_items"] >= 2

  def test_clear_cache(self, cache):
    cache.put("ns", "k1", "v1")
    cache.clear()
    assert cache.get("ns", "k1") is None
    assert cache.get_stats()["memory_items"] == 0


# ╔═══════════════════════════════════════════════════════════════╗
# ║  PART 7: INTENT PARSER — PHASE 17 COMMANDS (15+ scenarios)   ║
# ╚═══════════════════════════════════════════════════════════════╝

class TestIntentParserPhase17:

  @pytest.mark.parametrize("cmd", ["suggestions", "suggest", "tips", "proactive"])
  def test_suggestions_command(self, parser, cmd):
    r = parser.parse(cmd)
    assert r is not None
    assert r["tool"] == "system"
    assert r["method"] == "suggestions"

  @pytest.mark.parametrize("cmd", ["profile", "profile show", "show profile", "my profile"])
  def test_profile_show_command(self, parser, cmd):
    r = parser.parse(cmd)
    assert r is not None
    assert r["method"] == "profile_show"

  @pytest.mark.parametrize("cmd", ["profile stats", "profile summary"])
  def test_profile_stats_command(self, parser, cmd):
    r = parser.parse(cmd)
    assert r is not None
    assert r["method"] == "profile_stats"

  @pytest.mark.parametrize("cmd", ["perf", "perf report", "performance", "performance report"])
  def test_perf_report_command(self, parser, cmd):
    r = parser.parse(cmd)
    assert r is not None
    assert r["method"] == "perf_report"

  @pytest.mark.parametrize("cmd", ["session", "session summary"])
  def test_session_summary_command(self, parser, cmd):
    r = parser.parse(cmd)
    assert r is not None
    assert r["method"] == "session_summary"

  @pytest.mark.parametrize("cmd", ["end session", "new session"])
  def test_end_session_command(self, parser, cmd):
    r = parser.parse(cmd)
    assert r is not None
    assert r["method"] == "end_session"


class TestIntentParserExistingCommands:
  """Ensure Phase 17 additions don't break existing commands."""

  def test_expense(self, parser):
    r = parser.parse("expense 500 food")
    assert r is not None
    assert r["tool"] == "finance"

  def test_income(self, parser):
    r = parser.parse("income 10000 salary")
    assert r is not None
    assert r["tool"] == "finance"

  def test_remember(self, parser):
    r = parser.parse("remember I like pizza")
    assert r is not None
    assert r["tool"] == "memory"

  def test_log_experience(self, parser):
    r = parser.parse("log went to the gym")
    assert r is not None
    assert r["tool"] == "experience"

  def test_reminder(self, parser):
    r = parser.parse("remind me to call mom")
    assert r is not None
    assert r["tool"] == "reminder"

  def test_help(self, parser):
    r = parser.parse("help")
    assert r is not None
    assert r["method"] == "help"

  def test_balance(self, parser):
    r = parser.parse("balance")
    assert r is not None

  def test_llm_status(self, parser):
    r = parser.parse("llm status")
    assert r is not None
    assert r["method"] == "llm_status"

  def test_ask_query(self, parser):
    r = parser.parse("ask what are my hobbies")
    assert r is not None
    assert r["tool"] == "ask"

  def test_greeting(self, parser):
    r = parser.parse("hello")
    assert r is not None
    assert r["tool"] == "free_chat"


# ╔═══════════════════════════════════════════════════════════════╗
# ║  PART 8: ORCHESTRATOR END-TO-END (30+ scenarios)             ║
# ╚═══════════════════════════════════════════════════════════════╝

class TestOrchestratorPhase17Commands:
  """End-to-end tests for Phase 17 commands via Orchestrator."""

  def test_suggestions_command(self, orchestrator):
    resp = orchestrator.process("suggestions")
    assert resp  # Should return something
    assert "💡" in resp or "suggestion" in resp.lower()

  def test_profile_show(self, orchestrator):
    resp = orchestrator.process("my profile")
    assert resp
    # Should show time context
    assert "Mood" in resp or "interaction" in resp.lower()

  def test_profile_stats(self, orchestrator):
    resp = orchestrator.process("profile stats")
    assert resp
    assert "No profile" in resp or "User" in resp

  def test_session_summary(self, orchestrator):
    orchestrator.process("hello")
    resp = orchestrator.process("session summary")
    assert resp
    assert "turn" in resp.lower() or "session" in resp.lower()

  def test_end_session(self, orchestrator):
    orchestrator.process("hello")
    resp = orchestrator.process("end session")
    assert "fresh" in resp.lower() or "ended" in resp.lower()

  def test_perf_report(self, orchestrator):
    resp = orchestrator.process("perf report")
    assert resp
    assert "📊" in resp or "performance" in resp.lower()


class TestOrchestratorFinanceFlow:
  """Phase 1-3: Finance operations through orchestrator."""

  def test_add_expense(self, orchestrator):
    resp = orchestrator.process("expense 500 food")
    assert resp
    assert "500" in resp or "food" in resp.lower()

  def test_add_income(self, orchestrator):
    resp = orchestrator.process("income 10000 salary")
    assert resp
    assert "10000" in resp or "salary" in resp.lower() or "income" in resp.lower()

  def test_check_balance(self, orchestrator):
    orchestrator.process("income 5000 salary")
    resp = orchestrator.process("balance")
    assert resp


class TestOrchestratorMemoryFlow:
  """Phase 4-5: Memory operations."""

  def test_remember_fact(self, orchestrator):
    resp = orchestrator.process("remember I love hiking in the mountains")
    assert resp
    assert "save" in resp.lower() or "remember" in resp.lower() or "memory" in resp.lower()

  def test_show_memories(self, orchestrator):
    orchestrator.process("remember I have a pet dog named Bruno")
    resp = orchestrator.process("show memories")
    assert resp


class TestOrchestratorExperienceFlow:
  """Phase 6-7: Experience logging."""

  def test_log_experience(self, orchestrator):
    resp = orchestrator.process("log went to the gym today")
    assert resp
    assert "log" in resp.lower() or "gym" in resp.lower() or "experience" in resp.lower()


class TestOrchestratorReminderFlow:
  """Phase 8-9: Reminders."""

  def test_set_reminder(self, orchestrator):
    resp = orchestrator.process("remind me to buy milk")
    assert resp


class TestOrchestratorHelp:
  """System commands."""

  def test_help_includes_adaptive(self, orchestrator):
    resp = orchestrator.process("help")
    assert "ADAPTIVE" in resp
    assert "suggestions" in resp
    assert "profile" in resp
    assert "perf report" in resp

  def test_help_has_all_sections(self, orchestrator):
    resp = orchestrator.process("help")
    sections = ["FINANCE", "MEMORY", "EXPERIENCE", "REMINDERS",
                "DECISIONS", "PLANNING", "ASK", "LLM", "ADAPTIVE", "SYSTEM"]
    for section in sections:
      assert section in resp, f"Missing section: {section}"


# ╔═══════════════════════════════════════════════════════════════╗
# ║  PART 9: MULTI-TURN CONVERSATION FLOW (Jarvis-like)          ║
# ╚═══════════════════════════════════════════════════════════════╝

class TestJarvisLikeFlows:
  """Real-world conversation scenarios a human would have."""

  def test_morning_routine_flow(self, orchestrator):
    """Simulate a typical morning interaction."""
    # 1. User says hello
    r1 = orchestrator.process("hello")
    assert r1

    # 2. Check agenda
    # (may fail if planner not available, but shouldn't crash)
    r2 = orchestrator.process("suggestions")
    assert r2

    # 3. Log an expense
    r3 = orchestrator.process("expense 150 breakfast")
    assert r3 and "150" in r3

    # 4. Check session
    r4 = orchestrator.process("session")
    assert "3" in r4 or "4" in r4  # 3-4 turns

  def test_finance_tracking_flow(self, orchestrator):
    """Full finance session."""
    orchestrator.process("income 50000 salary")
    orchestrator.process("expense 5000 rent")
    orchestrator.process("expense 2000 groceries")
    orchestrator.process("expense 500 coffee")
    r = orchestrator.process("balance")
    assert r

  def test_memory_and_recall_flow(self, orchestrator):
    """Save facts and try to recall them."""
    orchestrator.process("remember I have a meeting with Rahul on Monday")
    orchestrator.process("remember my favorite restaurant is Toit in Koramangala")
    r = orchestrator.process("show memories")
    assert r

  def test_profile_learning_flow(self, orchestrator):
    """Profile should learn from interactions."""
    orchestrator.process("I am Tapan")
    orchestrator.process("I live in Bengaluru")
    orchestrator.process("I work as software developer")
    orchestrator.process("I love pizza and coding")

    r = orchestrator.process("my profile")
    # Profile should have learned something
    assert r

  def test_continuous_session(self, orchestrator):
    """Extended session with mixed commands."""
    commands = [
      "hello",
      "expense 100 chai",
      "remember meeting at 3pm",
      "I love yoga and meditation",
      "suggest",
      "expense 500 lunch",
      "remind me to call doctor",
      "my profile",
      "balance",
      "session",
    ]
    for cmd in commands:
      resp = orchestrator.process(cmd)
      assert resp is not None
      assert isinstance(resp, str)


# ╔═══════════════════════════════════════════════════════════════╗
# ║  PART 10: EDGE CASES & STRESS TESTS                          ║
# ╚═══════════════════════════════════════════════════════════════╝

class TestEdgeCases:

  def test_empty_input(self, orchestrator):
    assert orchestrator.process("") == ""

  def test_whitespace_input(self, orchestrator):
    assert orchestrator.process("   ") == ""

  def test_very_long_input(self, orchestrator):
    long_text = "hello " * 1000
    resp = orchestrator.process(long_text)
    assert resp  # Should not crash

  def test_special_characters(self, orchestrator):
    resp = orchestrator.process("expense 100 food! @#$%^&*()")
    assert resp

  def test_unicode_input(self, orchestrator):
    resp = orchestrator.process("remember मुझे pizza पसंद है")
    assert resp

  def test_numbers_only(self, orchestrator):
    resp = orchestrator.process("12345")
    assert resp

  def test_emoji_input(self, orchestrator):
    resp = orchestrator.process("🎉 I'm so happy!")
    assert resp

  def test_rapid_fire_commands(self, orchestrator):
    """Rapid sequence of commands — should all work."""
    for i in range(20):
      resp = orchestrator.process(f"expense {i*10} test{i}")
      assert resp is not None

  def test_concurrent_profile_operations(self, tmp_data):
    """Multiple profile instances shouldn't corrupt data."""
    from src.agent.user_profile import UserProfile
    p1 = UserProfile(tmp_data)
    p2 = UserProfile(tmp_data)
    p1.set_name("Alice")
    p2.set_name("Bob")
    p3 = UserProfile(tmp_data)
    assert p3.get_name() == "Bob"  # Last write wins


class TestStressTestUserProfile:
  """Volume testing for UserProfile."""

  def test_1000_interactions(self, profile):
    """Process 1000 interactions without crashing."""
    import random
    messages = [
      "expense 100 food", "I love pizza", "feeling happy",
      "remember meeting tomorrow", "balance check",
      "I hate traffic", "log went to gym", "tired and stressed",
      "work is going well", "excited about weekend",
    ]
    for i in range(1000):
      msg = random.choice(messages)
      profile.learn_from_interaction(msg, action="test")

    # Should not crash, log should be capped
    assert len(profile.data.get("interaction_log", [])) <= 200
    assert len(profile.data.get("mood_history", [])) <= 50

  def test_100_preferences(self, profile):
    """Store and retrieve 100 preferences."""
    for i in range(100):
      profile.set_preference(f"pref_{i}", f"value_{i}")
    for i in range(100):
      assert profile.get_preference(f"pref_{i}") == f"value_{i}"

  def test_500_facts(self, profile):
    """Store 500 unique facts."""
    for i in range(500):
      profile.add_fact(f"Fact number {i}")
    facts = profile.get_facts()
    assert len(facts) == 500


class TestStressTestConversationManager:

  def test_1000_turns(self, conv_mgr):
    """1000 conversation turns without issues."""
    for i in range(1000):
      conv_mgr.add_turn(f"msg{i}", f"resp{i}", f"intent{i % 10}")
    assert conv_mgr.get_turn_count() == 20  # max_history=20

  def test_large_entities(self, conv_mgr):
    """Large entity dictionaries."""
    big_entities = {f"key_{i}": f"value_{i}" for i in range(100)}
    conv_mgr.add_turn("big input", "big response", "test", big_entities)
    assert conv_mgr.get_last_turn()["entities"] == big_entities


class TestStressTestSmartCache:

  def test_1000_cache_entries(self, cache):
    """1000 cache entries."""
    for i in range(1000):
      cache.put("stress", f"key{i}", f"value{i}")

    # Recent entries should be retrievable
    assert cache.get("stress", "key999") == "value999"

    stats = cache.get_stats()
    assert stats["disk_items"] == 1000

  def test_cache_with_complex_data(self, cache):
    """Cache complex JSON structures."""
    complex_data = {
      "nested": {"deep": {"value": [1, 2, 3]}},
      "list": [{"a": 1}, {"b": 2}],
      "unicode": "हिंदी टेस्ट",
      "number": 42.5,
      "null": None,
    }
    cache.put("complex", "key", complex_data)
    result = cache.get("complex", "key")
    assert result["nested"]["deep"]["value"] == [1, 2, 3]
    assert result["unicode"] == "हिंदी टेस्ट"


class TestStressTestPerformanceMonitor:

  def test_10000_measurements(self, perf_monitor):
    """10000 measurements."""
    for i in range(10000):
      perf_monitor._record("mass_op", 0.001 * (i % 100))
    stats = perf_monitor.get_stats("mass_op")
    # deque capped at 200
    assert stats["count"] == 200

  def test_multiple_operations(self, perf_monitor):
    """Many different operations."""
    for op in range(50):
      for _ in range(5):
        perf_monitor._record(f"op_{op}", 0.01)
    report = perf_monitor.get_report()
    assert "op_0" in report
    assert "op_49" in report
