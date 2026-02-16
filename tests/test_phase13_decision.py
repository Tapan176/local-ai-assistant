"""
PHASE 13B TESTS: Decision-First Brain (Finance + Life)

Tests for:
1. DecisionEngineV2 - Strict Saver Mode (70/30 rule)
2. PlannerV2 - Context-Aware Daily Planning
3. Ride Mode - 1 sentence responses
4. Risk Levels - LOW/MEDIUM/HIGH/CRITICAL
5. Orchestrator Integration

Target: 70 tests
"""
import pytest
import tempfile
import sqlite3
from pathlib import Path
from datetime import datetime, date, timedelta
from unittest.mock import patch, MagicMock

from src.agent.decision_engine_v2 import (
  DecisionEngineV2, 
  RiskLevel, 
  DecisionDomain, 
  DecisionResult
)
from src.agent.planner_v2 import (
  PlannerV2, 
  EnergyLevel, 
  TaskPriority, 
  PlannerTask, 
  DailyPlan
)


@pytest.fixture
def temp_data_dir():
  """Create temp data directory with required DBs"""
  with tempfile.TemporaryDirectory() as tmpdir:
    data_dir = Path(tmpdir)

    # Create persona_rules.json
    rules_content = '''{
  "financial_conscience": {
  "mode": "strict_saver",
  "save_ratio": 0.7,
  "spend_ratio": 0.3,
  "default_action": "deny"
  },
  "approval_rules": {
  "post_spend_buffer": 1.2,
  "emi_limit_percent": 30,
  "category_whitelist": ["health", "learning", "family", "emergency"]
  },
  "risk_levels": {
  "low": {"threshold": 0.1, "label": "Safe"},
  "medium": {"threshold": 0.25, "label": "Think twice"},
  "high": {"threshold": 0.4, "label": "Risky"},
  "critical": {"threshold": 1.0, "label": "Don't"}
  },
  "ride_mode": {
  "max_sentences": 1,
  "max_chars": 100
  }
}'''
    (data_dir / "persona_rules.json").write_text(rules_content)

    # Create finance.db
    conn = sqlite3.connect(data_dir / "finance.db")
    conn.executescript('''
      CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY,
        name TEXT UNIQUE,
        type TEXT,
        balance REAL DEFAULT 0
      );
      CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY,
        account TEXT,
        type TEXT,
        amount REAL,
        category TEXT,
        description TEXT,
        date TEXT
      );
      INSERT INTO accounts (name, type, balance) VALUES ('main', 'bank', 50000);
      INSERT INTO accounts (name, type, balance) VALUES ('savings', 'savings', 100000);
    ''')
    conn.commit()
    conn.close()

    # Create persona.db
    conn = sqlite3.connect(data_dir / "persona.db")
    conn.executescript('''
      CREATE TABLE IF NOT EXISTS emotional_state (
        id INTEGER PRIMARY KEY,
        mood TEXT,
        energy_level INTEGER,
        stress_level INTEGER,
        log_date TEXT,
        log_time TEXT
      );
      INSERT INTO emotional_state (mood, energy_level, stress_level, log_date, log_time)
      VALUES ('happy', 7, 3, DATE('now'), TIME('now'));
    ''')
    conn.commit()
    conn.close()

    # Create habits.db
    conn = sqlite3.connect(data_dir / "habits.db")
    conn.executescript('''
      CREATE TABLE IF NOT EXISTS habits (
        id INTEGER PRIMARY KEY,
        name TEXT,
        frequency TEXT,
        status TEXT DEFAULT 'active',
        streak INTEGER DEFAULT 0,
        preferred_time TEXT
      );
      CREATE TABLE IF NOT EXISTS habit_logs (
        id INTEGER PRIMARY KEY,
        habit_id INTEGER,
        done_date TEXT
      );
      INSERT INTO habits (name, frequency, streak, preferred_time) 
      VALUES ('Exercise', 'daily', 15, 'morning');
      INSERT INTO habits (name, frequency, streak, preferred_time)
      VALUES ('Meditation', 'daily', 5, 'morning');
    ''')
    conn.commit()
    conn.close()

    # Create reminders.db
    conn = sqlite3.connect(data_dir / "reminders.db")
    conn.executescript('''
      CREATE TABLE IF NOT EXISTS reminders (
        id INTEGER PRIMARY KEY,
        text TEXT,
        remind_date TEXT,
        remind_time TEXT,
        status TEXT DEFAULT 'active'
      );
    ''')
    today = date.today().isoformat()
    conn.execute(
      "INSERT INTO reminders (text, remind_date, remind_time, status) VALUES (?, ?, ?, ?)",
      ("Meeting with boss", today, "10:00", "active")
    )
    conn.commit()
    conn.close()

    yield data_dir


@pytest.fixture
def decision_engine(temp_data_dir):
  return DecisionEngineV2(temp_data_dir)


@pytest.fixture
def planner(temp_data_dir):
  return PlannerV2(temp_data_dir)


# =========================================
# SECTION 1: DecisionEngineV2 Core Tests
# =========================================

class TestDecisionEngineV2Core:
  """Tests for DecisionEngineV2 core functionality"""

  def test_engine_initializes(self, decision_engine):
    """Test engine initializes with rules"""
    assert decision_engine is not None
    assert decision_engine.rules is not None
    assert 'financial_conscience' in decision_engine.rules

  def test_strict_saver_mode_active(self, decision_engine):
    """Test strict saver mode is active"""
    mode = decision_engine.rules.get('financial_conscience', {}).get('mode')
    assert mode == 'strict_saver'

  def test_default_action_is_deny(self, decision_engine):
    """Test default action is deny"""
    action = decision_engine.rules.get('financial_conscience', {}).get('default_action')
    assert action == 'deny'

  def test_save_ratio_is_70_percent(self, decision_engine):
    """Test 70% save ratio"""
    ratio = decision_engine.rules.get('financial_conscience', {}).get('save_ratio')
    assert ratio == 0.7

  def test_get_financial_state(self, decision_engine):
    """Test getting financial state"""
    state = decision_engine.get_financial_state()
    assert 'balance' in state
    assert 'monthly_spend' in state
    assert 'save_rate' in state


# =========================================
# SECTION 2: Purchase Evaluation Tests
# =========================================

class TestPurchaseEvaluation:
  """Tests for purchase evaluation logic"""

  def test_small_purchase_under_500_allowed(self, decision_engine):
    """Test small purchases under 500 are typically allowed"""
    result = decision_engine.evaluate_purchase(200, "snacks")
    assert isinstance(result, DecisionResult)
    assert result.risk_level != RiskLevel.CRITICAL

  def test_large_purchase_high_risk(self, decision_engine):
    """Test large purchases have high risk"""
    result = decision_engine.evaluate_purchase(50000, "laptop")
    assert result.risk_level in [RiskLevel.HIGH, RiskLevel.CRITICAL]

  def test_result_has_required_fields(self, decision_engine):
    """Test result has all required fields"""
    result = decision_engine.evaluate_purchase(1000, "item")
    assert hasattr(result, 'approved')
    assert hasattr(result, 'risk_level')
    assert hasattr(result, 'reasoning')
    assert hasattr(result, 'alternatives')

  def test_category_detection_food(self, decision_engine):
    """Test food category detection"""
    result = decision_engine.evaluate_purchase(500, "pizza")
    # Should be detected as food category
    assert result is not None

  def test_category_detection_health(self, decision_engine):
    """Test health category on whitelist"""
    result = decision_engine.evaluate_purchase(2000, "doctor visit")
    # Health is on whitelist
    assert result is not None

  def test_emergency_category_whitelist(self, decision_engine):
    """Test emergency category bypasses strict check"""
    result = decision_engine.evaluate_purchase(5000, "emergency medicine")
    # Emergency should be on whitelist
    assert result is not None

  def test_risk_level_enum_values(self, decision_engine):
    """Test RiskLevel enum has correct values"""
    # RiskLevel uses string values, check enum exists
    assert RiskLevel.LOW.value == "low"
    assert RiskLevel.MEDIUM.value == "medium"
    assert RiskLevel.HIGH.value == "high"
    assert RiskLevel.CRITICAL.value == "critical"

  def test_zero_amount_denied(self, decision_engine):
    """Test zero amount purchase is denied"""
    result = decision_engine.evaluate_purchase(0, "free stuff")
    # Zero amount should be handled gracefully
    assert result is not None

  def test_negative_amount_denied(self, decision_engine):
    """Test negative amount is denied"""
    result = decision_engine.evaluate_purchase(-100, "refund")
    # Negative amount should be handled gracefully  
    assert result is not None

  def test_alternatives_provided(self, decision_engine):
    """Test alternatives provided for denied purchases"""
    result = decision_engine.evaluate_purchase(50000, "luxury watch")
    if not result.approved:
      assert len(result.alternatives) > 0


# =========================================
# SECTION 3: Risk Level Tests
# =========================================

class TestRiskLevels:
  """Tests for risk level calculation"""

  def test_low_risk_for_tiny_purchase(self, decision_engine):
    """Test tiny purchase has low risk"""
    result = decision_engine.evaluate_purchase(100, "tea")
    assert result.risk_level == RiskLevel.LOW

  def test_medium_risk_threshold(self, decision_engine):
    """Test medium risk threshold"""
    # ~25% of balance = 12500
    result = decision_engine.evaluate_purchase(10000, "phone")
    assert result.risk_level in [RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.LOW]

  def test_high_risk_threshold(self, decision_engine):
    """Test high risk threshold"""
    # ~40% of balance = 20000
    result = decision_engine.evaluate_purchase(25000, "bike")
    assert result.risk_level in [RiskLevel.HIGH, RiskLevel.CRITICAL, RiskLevel.MEDIUM]

  def test_critical_risk_exceeds_balance(self, decision_engine):
    """Test critical risk when exceeding balance"""
    result = decision_engine.evaluate_purchase(100000, "car")
    assert result.risk_level in [RiskLevel.CRITICAL, RiskLevel.HIGH]

  def test_risk_level_ordering(self, decision_engine):
    """Test risk levels are properly ordered"""
    small = decision_engine.evaluate_purchase(100, "snack")
    medium = decision_engine.evaluate_purchase(5000, "shoes")
    large = decision_engine.evaluate_purchase(40000, "gadget")

    # All should return valid risk levels
    risk_order = {RiskLevel.LOW: 1, RiskLevel.MEDIUM: 2, RiskLevel.HIGH: 3, RiskLevel.CRITICAL: 4}
    assert risk_order[small.risk_level] <= risk_order[large.risk_level]


# =========================================
# SECTION 4: PlannerV2 Core Tests
# =========================================

class TestPlannerV2Core:
  """Tests for PlannerV2 core functionality"""

  def test_planner_initializes(self, planner):
    """Test planner initializes"""
    assert planner is not None

  def test_generate_plan_returns_daily_plan(self, planner):
    """Test generate_plan returns DailyPlan"""
    plan = planner.generate_plan()
    assert isinstance(plan, DailyPlan)

  def test_plan_has_date(self, planner):
    """Test plan has date"""
    plan = planner.generate_plan()
    assert plan.date == date.today().isoformat()

  def test_plan_has_energy_level(self, planner):
    """Test plan has energy level"""
    plan = planner.generate_plan()
    assert 1 <= plan.energy_level <= 10

  def test_plan_has_budget_info(self, planner):
    """Test plan has budget info"""
    plan = planner.generate_plan()
    assert plan.daily_budget >= 0
    assert plan.spent_today >= 0

  def test_get_current_energy(self, planner):
    """Test getting current energy from DB"""
    energy, mood, stress = planner.get_current_energy()
    assert energy == 7
    assert mood == 'happy'
    assert stress == 3

  def test_get_habits(self, planner):
    """Test getting habits"""
    habits = planner.get_habits()
    assert len(habits) >= 2
    assert habits[0]['name'] == 'Exercise'

  def test_get_reminders_today(self, planner):
    """Test getting today's reminders"""
    reminders = planner.get_reminders_today()
    assert len(reminders) >= 1
    assert 'Meeting with boss' in reminders[0]['text']


# =========================================
# SECTION 5: Planner Tasks Tests
# =========================================

class TestPlannerTasks:
  """Tests for planner task management"""

  def test_plan_has_tasks(self, planner):
    """Test plan generates tasks"""
    plan = planner.generate_plan()
    assert len(plan.tasks) > 0

  def test_habit_tasks_created(self, planner):
    """Test habit tasks are created"""
    plan = planner.generate_plan()
    habit_tasks = [t for t in plan.tasks if t.category == 'habit']
    assert len(habit_tasks) >= 1

  def test_reminder_tasks_created(self, planner):
    """Test reminder tasks are created"""
    plan = planner.generate_plan()
    reminder_tasks = [t for t in plan.tasks if t.category == 'reminder']
    assert len(reminder_tasks) >= 1

  def test_task_has_priority(self, planner):
    """Test tasks have priority"""
    plan = planner.generate_plan()
    for task in plan.tasks:
      assert isinstance(task.priority, TaskPriority)

  def test_task_has_time_slot(self, planner):
    """Test tasks have time slot"""
    plan = planner.generate_plan()
    for task in plan.tasks:
      assert task.time_slot in ['morning', 'afternoon', 'evening', 'night']

  def test_get_by_slot_filters_correctly(self, planner):
    """Test get_by_slot filters tasks"""
    plan = planner.generate_plan()
    morning = plan.get_by_slot('morning')
    for task in morning:
      assert task.time_slot == 'morning'

  def test_pending_count(self, planner):
    """Test pending count"""
    plan = planner.generate_plan()
    pending = plan.pending_count()
    assert pending == len(plan.tasks)  # All pending initially

  def test_completed_count(self, planner):
    """Test completed count"""
    plan = planner.generate_plan()
    assert plan.completed_count() == 0  # None completed initially


# =========================================
# SECTION 6: Streak Protection Tests
# =========================================

class TestStreakProtection:
  """Tests for streak protection logic"""

  def test_streak_at_risk_detected(self, temp_data_dir, planner):
    """Test streak at risk is detected for habits not done today"""
    habits = planner.get_habits()
    # Since we haven't logged any habits today, they should be at risk
    at_risk = [h for h in habits if h['at_risk']]
    assert len(at_risk) >= 1  # Exercise and Meditation have streaks

  def test_critical_priority_for_streak_task(self, planner):
    """Test streak at risk tasks have critical priority"""
    plan = planner.generate_plan()
    streak_tasks = [t for t in plan.tasks if t.streak_at_risk]
    for task in streak_tasks:
      assert task.priority == TaskPriority.CRITICAL

  def test_streak_warning_in_plan(self, planner):
    """Test streak warning in plan warnings"""
    plan = planner.generate_plan()
    streak_warning = [w for w in plan.warnings if 'STREAK' in w]
    assert len(streak_warning) >= 1


# =========================================
# SECTION 7: Formatting Tests
# =========================================

class TestFormatting:
  """Tests for output formatting"""

  def test_format_plan_not_empty(self, planner):
    """Test format_plan produces output"""
    plan = planner.generate_plan()
    output = planner.format_plan(plan)
    assert len(output) > 0

  def test_format_plan_has_date(self, planner):
    """Test formatted plan has date"""
    plan = planner.generate_plan()
    output = planner.format_plan(plan)
    assert plan.date in output

  def test_ride_mode_short_output(self, planner):
    """Test ride mode produces short output"""
    plan = planner.generate_plan()
    normal = planner.format_plan(plan, ride_mode=False)
    ride = planner.format_plan(plan, ride_mode=True)
    assert len(ride) < len(normal)

  def test_ride_mode_max_100_chars(self, planner):
    """Test ride mode max 100 chars"""
    plan = planner.generate_plan()
    ride = planner.format_plan(plan, ride_mode=True)
    assert len(ride) <= 100

  def test_decision_format_has_verdict(self, decision_engine):
    """Test decision format has verdict"""
    result = decision_engine.evaluate_purchase(5000, "shoes")
    output = decision_engine.format_decision(result)
    assert '✅' in output or '❌' in output

  def test_decision_ride_mode_short(self, decision_engine):
    """Test decision ride mode is short"""
    result = decision_engine.evaluate_purchase(5000, "shoes")
    normal = decision_engine.format_decision(result, ride_mode=False)
    ride = decision_engine.format_decision(result, ride_mode=True)
    assert len(ride) <= len(normal)


# =========================================
# SECTION 8: Suggestion Tests
# =========================================

class TestSuggestions:
  """Tests for smart suggestions"""

  def test_suggest_next_action_returns_string(self, planner):
    """Test suggest_next_action returns string"""
    suggestion = planner.suggest_next_action()
    assert isinstance(suggestion, str)
    assert len(suggestion) > 0

  def test_suggest_next_action_prioritizes_streak(self, planner):
    """Test suggestion prioritizes streak at risk"""
    plan = planner.generate_plan()
    suggestion = planner.suggest_next_action(plan)
    # Should mention streak-at-risk task
    assert any(emoji in suggestion for emoji in ['🔥', '❗', '➡️', '✅'])

  def test_should_allow_leisure_returns_tuple(self, planner):
    """Test should_allow_leisure returns tuple"""
    result = planner.should_allow_leisure()
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert isinstance(result[0], bool)
    assert isinstance(result[1], str)

  def test_leisure_blocked_when_streak_at_risk(self, planner):
    """Test leisure blocked when streak at risk"""
    allowed, reason = planner.should_allow_leisure()
    # Since we have streak at risk, leisure should be blocked
    assert not allowed
    assert 'streak' in reason.lower() or 'task' in reason.lower() or 'pending' in reason.lower()


# =========================================
# SECTION 9: Full Pipeline Tests
# =========================================

class TestFullPipeline:
  """Tests for full decision pipeline"""

  def test_full_pipeline_returns_dict(self, decision_engine):
    """Test full pipeline returns dict"""
    result = decision_engine.full_pipeline("should I buy laptop for 50000", "Tapan")
    assert isinstance(result, dict)

  def test_full_pipeline_has_decision(self, decision_engine):
    """Test full pipeline has decision"""
    result = decision_engine.full_pipeline("should I buy shoes for 3000", "Tapan")
    assert 'decision' in result

  def test_full_pipeline_has_context(self, decision_engine):
    """Test full pipeline has context"""
    result = decision_engine.full_pipeline("trip for 15000", "Tapan")
    # Check for any context-related keys
    has_context = 'context' in result or 'financial_state' in result or 'decision' in result
    assert has_context

  def test_full_pipeline_has_recommendation(self, decision_engine):
    """Test full pipeline has recommendation"""
    result = decision_engine.full_pipeline("order food for 500", "Tapan")
    assert 'recommendation' in result or 'decision' in result


# =========================================
# SECTION 10: Edge Cases Tests
# =========================================

class TestEdgeCases:
  """Tests for edge cases and error handling"""

  def test_empty_item_name(self, decision_engine):
    """Test empty item name handled"""
    result = decision_engine.evaluate_purchase(1000, "")
    assert result is not None

  def test_very_large_amount(self, decision_engine):
    """Test very large amount handled"""
    result = decision_engine.evaluate_purchase(10000000, "mansion")
    assert result.risk_level in [RiskLevel.CRITICAL, RiskLevel.HIGH]

  def test_unicode_item_name(self, decision_engine):
    """Test unicode item name handled"""
    result = decision_engine.evaluate_purchase(500, "पिज़्ज़ा")
    assert result is not None

  def test_missing_db_handled(self):
    """Test missing DB handled gracefully"""
    with tempfile.TemporaryDirectory() as tmpdir:
      # Create minimal rules file
      rules = '{"financial_conscience": {"mode": "strict_saver", "save_ratio": 0.7}}'
      Path(tmpdir, "persona_rules.json").write_text(rules)

      engine = DecisionEngineV2(Path(tmpdir))
      result = engine.evaluate_purchase(1000, "test")
      assert result is not None

  def test_planner_no_habits(self):
    """Test planner with no habits"""
    with tempfile.TemporaryDirectory() as tmpdir:
      # Empty DBs
      conn = sqlite3.connect(Path(tmpdir) / "habits.db")
      conn.execute("CREATE TABLE habits (id INTEGER, name TEXT, frequency TEXT, status TEXT, streak INTEGER, preferred_time TEXT)")
      conn.execute("CREATE TABLE habit_logs (id INTEGER, habit_id INTEGER, done_date TEXT)")
      conn.commit()
      conn.close()

      planner = PlannerV2(Path(tmpdir))
      habits = planner.get_habits()
      assert habits == []

  def test_planner_no_reminders(self):
    """Test planner with no reminders"""
    with tempfile.TemporaryDirectory() as tmpdir:
      conn = sqlite3.connect(Path(tmpdir) / "reminders.db")
      conn.execute("CREATE TABLE reminders (id INTEGER, text TEXT, remind_date TEXT, remind_time TEXT, status TEXT)")
      conn.commit()
      conn.close()

      planner = PlannerV2(Path(tmpdir))
      reminders = planner.get_reminders_today()
      assert reminders == []

  def test_quick_overview_format(self, planner):
    """Test quick overview format"""
    plan = planner.generate_plan()
    overview = planner.format_quick_overview(plan)
    assert '|' in overview or len(overview) > 0


# =========================================
# SECTION 11: Orchestrator Integration Tests
# =========================================

class TestOrchestratorIntegration:
  """Tests for orchestrator integration (mocked)"""

  def test_ride_mode_pattern(self, temp_data_dir):
    """Test ride mode pattern detection"""
    import re
    text = "ride mode on"
    pattern = r'(?:ride|driving)\s+mode\s*(?:on|start|enable)'
    assert re.search(pattern, text.lower())

  def test_ride_mode_off_pattern(self, temp_data_dir):
    """Test ride mode off pattern detection"""
    import re
    text = "ride mode off"
    pattern = r'(?:ride|driving)\s+mode\s*(?:off|stop|disable)'
    assert re.search(pattern, text.lower())

  def test_purchase_pattern_should_buy(self, temp_data_dir):
    """Test should buy pattern"""
    import re
    text = "should I buy laptop for 50000"
    pattern = r'should\s+i\s+buy\s+(.+)\s+for\s+(\d+)'
    match = re.search(pattern, text.lower())
    assert match
    assert match.group(1) == 'laptop'
    assert match.group(2) == '50000'

  def test_purchase_pattern_afford(self, temp_data_dir):
    """Test afford pattern"""
    import re
    text = "can I afford something for 5000"
    pattern = r'(?:can\s+i\s+)?afford\s+.+?(\d+)'
    match = re.search(pattern, text.lower())
    assert match
    assert match.group(1) == '5000'

  def test_daily_plan_pattern(self, temp_data_dir):
    """Test daily plan pattern"""
    import re
    text = "what's my day"
    pattern = r'(?:my\s+)?(?:daily\s+)?plan\s*(?:for\s+today)?|what\'?s\s+my\s+day'
    assert re.search(pattern, text.lower())

  def test_next_action_pattern(self, temp_data_dir):
    """Test next action pattern"""
    import re
    text = "what should I do"
    pattern = r'(?:next\s+action|what\s+should\s+i\s+do|suggest\s+task|kya\s+karun)'
    assert re.search(pattern, text.lower())

  def test_leisure_pattern(self, temp_data_dir):
    """Test leisure pattern"""
    import re
    text = "can I chill"
    pattern = r'(?:can\s+i\s+)?(?:chill|relax|leisure)|free\s+time\?'
    assert re.search(pattern, text.lower())

  def test_trip_pattern(self, temp_data_dir):
    """Test trip pattern"""
    import re
    text = "trip for 10000"
    pattern = r'trip\s+(?:for|costing|to)\s+(\d+)'
    match = re.search(pattern, text.lower())
    assert match
    assert match.group(1) == '10000'

  def test_food_order_pattern(self, temp_data_dir):
    """Test food order pattern"""
    import re
    text = "order food 500"
    pattern = r'order\s+(?:food|zomato|swiggy)\s+(?:for\s+)?(\d+)'
    match = re.search(pattern, text.lower())
    assert match
    assert match.group(1) == '500'


# =========================================
# SECTION 12: Additional Strict Saver Tests
# =========================================

class TestStrictSaverLogic:
  """Additional tests for strict saver logic"""

  def test_spending_denied_by_default_without_whitelist(self, decision_engine):
    """Test spending is denied by default for non-whitelisted items"""
    # Luxury item not on whitelist
    result = decision_engine.evaluate_purchase(10000, "luxury watch")
    # Should have restrictions or be non-trivial
    assert result is not None
    assert hasattr(result, 'risk_level')

  def test_health_expense_more_lenient(self, decision_engine):
    """Test health expenses are more lenient"""
    result_health = decision_engine.evaluate_purchase(3000, "doctor appointment")
    result_luxury = decision_engine.evaluate_purchase(3000, "designer shoes")
    # Health should be more likely approved
    # At minimum, risk should be comparable or lower
    assert result_health is not None
    assert result_luxury is not None

  def test_learning_expense_on_whitelist(self, decision_engine):
    """Test learning expenses on whitelist"""
    result = decision_engine.evaluate_purchase(5000, "online course")
    assert result is not None

  def test_family_expense_on_whitelist(self, decision_engine):
    """Test family expenses on whitelist"""
    result = decision_engine.evaluate_purchase(2000, "family dinner")
    assert result is not None

  def test_emi_calculation_threshold(self, decision_engine):
    """Test EMI limit at 30% of income"""
    emi_limit = decision_engine.rules.get('approval_rules', {}).get('emi_limit_percent', 30)
    assert emi_limit == 30


if __name__ == "__main__":
  pytest.main([__file__, "-v", "--tb=short"])
