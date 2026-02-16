"""
Tests for PHASE 7 - Personal Reasoning Layer
Tests reasoning traces, profile management, and safety guards
"""
import sys
from pathlib import Path
import tempfile

# Add project root to path
project_root = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(project_root))


def test_reasoning_trace():
  """Test multi-step reasoning trace"""
  print("\n" + "="*50)
  print("TEST: Reasoning Trace")
  print("="*50)

  from src.brain.reasoning import ReasoningEngine

  with tempfile.TemporaryDirectory() as tmpdir:
    engine = ReasoningEngine(Path(tmpdir))

    # Test finance query detection
    query1 = "should I buy a phone for 50000"
    trace1 = engine.reason(query1, {
      'finance_state': {'balance': 30000, 'monthly_income': 50000, 'monthly_expense': 20000},
      'profile': {'risk_level': 'moderate'}
    })

    print(f"  Query: '{query1}'")
    print(f"  ✓ Type: {trace1.reasoning_type}")
    print(f"  ✓ Steps: {len(trace1.steps)}")
    print(f"  ✓ Decision: {trace1.decision}")

    type_ok = trace1.reasoning_type == 'finance'
    steps_ok = len(trace1.steps) >= 3
    has_decision = bool(trace1.decision)

    # Test planning query
    query2 = "how should I plan my day today"
    trace2 = engine.reason(query2, {
      'reminders': [{'text': 'Meeting at 10'}],
      'habits': [{'name': 'exercise', 'streak': 5}],
      'profile': {'daily_routine': 'balanced'}
    })

    print(f"\n  Query: '{query2}'")
    print(f"  ✓ Type: {trace2.reasoning_type}")
    print(f"  ✓ Steps: {len(trace2.steps)}")

    planning_ok = trace2.reasoning_type == 'planning'

    return type_ok and steps_ok and has_decision and planning_ok


def test_finance_safety_guards():
  """Test safety guards for finance decisions"""
  print("\n" + "="*50)
  print("TEST: Finance Safety Guards")
  print("="*50)

  from src.brain.reasoning import ReasoningEngine

  with tempfile.TemporaryDirectory() as tmpdir:
    engine = ReasoningEngine(Path(tmpdir))

    # Scenario 1: Purchase > 50% of balance (should warn)
    query_expensive = "should I buy laptop for 60000"
    trace1 = engine.reason(query_expensive, {
      'finance_state': {'balance': 50000, 'monthly_income': 60000, 'monthly_expense': 30000},
      'profile': {'risk_level': 'moderate'}
    })

    has_warning = trace1.has_warnings()
    print(f"  Expensive purchase (60k on 50k balance)")
    print(f"  ✓ Has warning: {has_warning}")
    print(f"  ✓ Decision: {trace1.decision}")

    # Scenario 2: Affordable purchase (should be OK)
    query_cheap = "should I buy book for 500"
    trace2 = engine.reason(query_cheap, {
      'finance_state': {'balance': 50000, 'monthly_income': 60000, 'monthly_expense': 30000},
      'profile': {'risk_level': 'moderate'}
    })

    is_ok = not trace2.has_warnings() or trace2.decision == 'appears_affordable'
    print(f"\n  Cheap purchase (500 on 50k balance)")
    print(f"  ✓ Appears affordable: {is_ok}")

    return has_warning and is_ok


def test_profile_management():
  """Test profile CRUD operations"""
  print("\n" + "="*50)
  print("TEST: Profile Management")
  print("="*50)

  from src.core.profile import ProfileManager

  with tempfile.TemporaryDirectory() as tmpdir:
    db_path = Path(tmpdir) / "test_profile.db"
    pm = ProfileManager(db_path)

    # Test default values
    risk = pm.get_risk_level()
    print(f"  ✓ Default risk level: {risk}")
    default_ok = risk == 'moderate'

    # Test set
    pm.set('test_key', 'test_value', 'test')
    retrieved = pm.get('test_key')
    print(f"  ✓ Set/Get works: {retrieved}")
    set_ok = retrieved == 'test_value'

    # Test set risk level
    result = pm.set_risk_level('conservative')
    new_risk = pm.get_risk_level()
    print(f"  ✓ Risk level changed: {new_risk}")
    risk_ok = new_risk == 'conservative'

    # Test invalid risk level
    invalid_result = pm.set_risk_level('invalid')
    print(f"  ✓ Invalid risk rejected: {'Error' in invalid_result or '❌' in invalid_result}")

    # Test priorities
    pm.set_priority(1, 'health')
    priorities = pm.get_priorities()
    print(f"  ✓ Priorities: {priorities}")
    priority_ok = 'health' in priorities

    # Test show profile
    profile_str = pm.show_profile()
    print(f"  ✓ Show profile output: {len(profile_str)} chars")

    return default_ok and set_ok and risk_ok and priority_ok


def test_pros_cons_builder():
  """Test pros/cons analysis"""
  print("\n" + "="*50)
  print("TEST: Pros/Cons Builder")
  print("="*50)

  from src.brain.reasoning import ProsCons

  pc = ProsCons()

  # Add items
  pc.add_pro("Within budget")
  pc.add_pro("Good investment")
  pc.add_con("High one-time cost")

  print(f"  ✓ Pros: {len(pc.pros)}")
  print(f"  ✓ Cons: {len(pc.cons)}")
  print(f"  ✓ Balance: {pc.get_balance()}")

  pros_ok = len(pc.pros) == 2
  cons_ok = len(pc.cons) == 1
  balance_ok = pc.get_balance() == 'positive'

  return pros_ok and cons_ok and balance_ok


def test_persona_reasoning_format():
  """Test persona formatting with reasoning"""
  print("\n" + "="*50)
  print("TEST: Persona Reasoning Format")
  print("="*50)

  from src.core.persona import PersonaGenerator
  from src.brain.reasoning import ReasoningTrace, ReasoningStep, ProsCons, SafetyCheck

  persona = PersonaGenerator()

  # Create a mock trace
  trace = ReasoningTrace(
    query="should I buy phone",
    reasoning_type="finance"
  )
  trace.add_step("Understanding query", "Query type: finance", 0.9)
  trace.add_step("Checking balance", "Balance: ₹50,000", 0.9)
  trace.add_step("Affordability", "Item cost: ₹30000 (60% of balance)", 0.85)

  trace.pros_cons = ProsCons()
  trace.pros_cons.add_pro("Good value")
  trace.pros_cons.add_con("60% of savings")

  trace.safety_checks.append(SafetyCheck(
    check_type="affordability",
    passed=False,
    warning="⚠️ High cost relative to balance",
    severity="warning"
  ))
  trace.decision = "reconsider"

  # Format it
  output = persona.format_reasoning_response(trace, "Bhai, thoda soch lo!")

  print(f"  ✓ Output length: {len(output)} chars")
  print(f"  ✓ Contains reasoning: {'Soch' in output or 'step' in output.lower()}")
  print(f"  ✓ Contains answer: {'Answer' in output}")

  has_content = len(output) > 100
  has_structure = 'Answer' in output

  return has_content and has_structure


def test_intent_parsing():
  """Test profile intent parsing"""
  print("\n" + "="*50)
  print("TEST: Intent Parsing (Profile)")
  print("="*50)

  from src.core.intents import IntentRouter

  router = IntentRouter()

  tests = [
    ("profile", "show_profile"),
    ("profile show", "show_profile"),
    ("profile set risk_level conservative", "set_profile"),
  ]

  all_pass = True
  for cmd, expected in tests:
    result = router.parse_intent(cmd)
    actual = result['intent']
    passed = actual == expected
    status = "✓" if passed else "✗"
    print(f"  {status} '{cmd}' → {actual}")
    if not passed:
      all_pass = False

  return all_pass


def run_all_tests():
  """Run all Phase 7 tests"""
  print("\n" + "="*60)
  print("   TAPAN_AI PHASE 7 - Test Suite")
  print("   Personal Reasoning Layer")
  print("="*60)

  results = {
    'Reasoning Trace': test_reasoning_trace(),
    'Finance Safety': test_finance_safety_guards(),
    'Profile Management': test_profile_management(),
    'Pros/Cons Builder': test_pros_cons_builder(),
    'Persona Reasoning': test_persona_reasoning_format(),
    'Intent Parsing': test_intent_parsing(),
  }

  print("\n" + "="*60)
  print("   TEST SUMMARY")
  print("="*60)

  passed = sum(1 for v in results.values() if v)
  total = len(results)

  for name, result in results.items():
    status = "✓ PASS" if result else "✗ FAIL"
    print(f"  {status} - {name}")

  print("\n" + "-"*60)
  print(f"  Total: {passed}/{total} tests passed")

  if passed == total:
    print("\n  🎉 All tests passed!")
  else:
    print(f"\n  ⚠️ {total - passed} tests failed")

  print("="*60 + "\n")

  return passed == total


if __name__ == "__main__":
  success = run_all_tests()
  sys.exit(0 if success else 1)
