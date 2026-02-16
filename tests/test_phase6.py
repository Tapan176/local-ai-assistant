"""
Tests for PHASE 6 - Local Brain + Multi Model Router
Tests router decisions, RAG retrieval, ask flow, persona formatting
"""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(project_root))


def test_router_decisions():
  """Test model router task routing"""
  print("\n" + "="*50)
  print("TEST: Router Decisions")
  print("="*50)

  from src.brain.router import ModelRouter, TaskType, ModelTier

  router = ModelRouter()

  # Register test backends
  router.register_backend('tiny', ModelTier.TINY, lambda: True)
  router.register_backend('small', ModelTier.SMALL, lambda: False)  # Not ready
  router.register_backend('bitnet', ModelTier.HEAVY, lambda: False)  # Not ready
  router.register_backend('placeholder', ModelTier.TINY, lambda: True)

  test_cases = [
    (TaskType.REASONING, ModelTier.TINY),  # Falls back to tiny since heavy not ready
    (TaskType.CHAT, ModelTier.TINY),       # Falls back since small not ready
    (TaskType.SUMMARIZE, ModelTier.TINY),
    (TaskType.CLASSIFY, ModelTier.TINY),   # Intent tier falls to tiny
  ]

  all_passed = True
  for task, expected_tier in test_cases:
    decision = router.route(task)
    # Check that we get a valid decision (may fall back)
    if decision.backend_name in ['tiny', 'placeholder']:
      print(f"  ✓ {task.value:12} → {decision.backend_name} ({decision.reason})")
    else:
      print(f"  ✗ {task.value:12} → {decision.backend_name} (unexpected)")
      all_passed = False

  return all_passed


def test_task_type_inference():
  """Test task type inference from user input"""
  print("\n" + "="*50)
  print("TEST: Task Type Inference")
  print("="*50)

  from src.brain.router import ModelRouter, TaskType

  router = ModelRouter()

  test_cases = [
    ("why is my expense high", TaskType.REASONING),
    ("explain my spending pattern", TaskType.REASONING),
    ("summarize my week", TaskType.SUMMARIZE),
    ("what type of expense is this", TaskType.CLASSIFY),
    ("hello how are you", TaskType.CHAT),
    ("find all my gym entries", TaskType.EXTRACT),
  ]

  all_passed = True
  for text, expected_task in test_cases:
    inferred = router.infer_task_type(text)
    passed = inferred == expected_task
    status = "✓" if passed else "✗"
    print(f"  {status} '{text[:35]:35}' → {inferred.value}")
    if not passed:
      print(f"      Expected: {expected_task.value}")
      all_passed = False

  return all_passed


def test_rag_retrieval():
  """Test RAG knowledge retrieval"""
  print("\n" + "="*50)
  print("TEST: RAG Retrieval")
  print("="*50)

  import tempfile
  from src.core.knowledge import KnowledgeManager

  with tempfile.TemporaryDirectory() as tmpdir:
    tmpdir = Path(tmpdir)
    db_path = tmpdir / "test_knowledge.db"

    km = KnowledgeManager(db_path, tmpdir)

    # Ingest test documents
    test_docs = [
      ("I spent 500 on petrol for my bike", "2026-01-01"),
      ("Monthly salary received 50000", "2026-01-15"),
      ("Gym membership renewed for 2000", "2026-01-20"),
      ("Bought groceries worth 1500", "2026-01-25"),
    ]

    km.ingest_from_memory(test_docs)

    # Test search
    results = km.search("bike petrol", top_k=3)

    if results:
      print(f"  ✓ Found {len(results)} results for 'bike petrol'")
      for r in results:
        print(f"      Score: {r['score']:.3f} - {r['text'][:50]}...")
      passed = any('bike' in r['text'].lower() for r in results)
    else:
      print("  ✗ No results found")
      passed = False

    # Test context building
    context = km.build_context("spending on vehicle")
    if context:
      print(f"  ✓ Built context ({len(context)} chars)")
    else:
      print("  ⚠ No context built (may be expected)")

    # Test stats
    stats = km.get_stats()
    print(f"  ℹ Stats: {stats['documents']} docs, {stats['chunks']} chunks")

    return passed


def test_ask_flow():
  """Test end-to-end ask flow"""
  print("\n" + "="*50)
  print("TEST: Ask Flow")
  print("="*50)

  from src.brain.llm_interface import get_llm

  llm = get_llm('unified')

  test_queries = [
    "what is my main expense",
    "summarize my spending",
    "hello",
  ]

  all_passed = True
  for query in test_queries:
    response = llm.generate(query, "Test context: petrol 500, food 300")

    if response and len(response) > 10:
      print(f"  ✓ '{query[:30]:30}' → Response ({len(response)} chars)")
    else:
      print(f"  ✗ '{query[:30]:30}' → Empty or short response")
      all_passed = False

  return all_passed


def test_persona_formatting():
  """Test persona response formatting"""
  print("\n" + "="*50)
  print("TEST: Persona Formatting")
  print("="*50)

  from src.core.persona import PersonaGenerator

  persona = PersonaGenerator()

  # Test plan formatting
  plan_data = {
    'reminders': [{'text': 'Call mom'}, {'text': 'Meeting at 5'}],
    'habits': [{'name': 'exercise', 'streak': 5}],
    'finance': {'balance': 10000, 'today_expense': 500},
    'suggestions': ['Review your monthly budget']
  }

  plan_output = persona.format_plan(plan_data)
  plan_ok = 'Plan' in plan_output or 'Agenda' in plan_output
  print(f"  {'✓' if plan_ok else '✗'} Plan formatting: {len(plan_output)} chars")

  # Test report formatting
  report_data = {
    'finance': {'balance': 10000, 'month_expense': 5000, 'month_income': 15000},
    'journal': {'total': 10, 'this_month': 5, 'top_tags': [('work', 3), ('gym', 2)]},
    'habits': {'total': 3, 'completed_today': 2, 'streaks': [('exercise', 7)]}
  }

  report_output = persona.format_report(report_data)
  report_ok = 'FINANCE' in report_output and 'JOURNAL' in report_output
  print(f"  {'✓' if report_ok else '✗'} Report formatting: {len(report_output)} chars")

  # Test ask response formatting
  ask_output = persona.format_ask_response(
    "what is my expense",
    "petrol: 500",
    "Your main expense is petrol at 500"
  )
  ask_ok = len(ask_output) > 20
  print(f"  {'✓' if ask_ok else '✗'} Ask response formatting: {len(ask_output)} chars")

  # Test greeting
  greeting = persona.get_greeting()
  greet_ok = len(greeting) > 5
  print(f"  {'✓' if greet_ok else '✗'} Greeting: {greeting}")

  return plan_ok and report_ok and ask_ok


def test_backend_interfaces():
  """Test backend interface consistency"""
  print("\n" + "="*50)
  print("TEST: Backend Interfaces")
  print("="*50)

  from src.brain.bitnet_backend import BitNetBackend
  from src.brain.small_backend import SmallBackend
  from src.brain.tiny_backend import TinyBackend

  backends = [
    ('BitNet', BitNetBackend()),
    ('Small', SmallBackend()),
    ('Tiny', TinyBackend()),
  ]

  all_passed = True
  for name, backend in backends:
    # Check required methods
    has_generate = hasattr(backend, 'generate')
    has_summarize = hasattr(backend, 'summarize')
    has_is_ready = hasattr(backend, 'is_ready')
    has_get_info = hasattr(backend, 'get_info')

    if has_generate and has_summarize and has_is_ready and has_get_info:
      info = backend.get_info()
      print(f"  ✓ {name:10} - tier: {info.get('tier', 'N/A')}, ready: {backend.is_ready()}")
    else:
      print(f"  ✗ {name:10} - Missing required methods")
      all_passed = False

  return all_passed


def test_model_list():
  """Test model list command"""
  print("\n" + "="*50)
  print("TEST: Model List")
  print("="*50)

  from src.brain.router import get_router, ModelTier

  router = get_router()

  # Register some backends
  router.register_backend('tiny', ModelTier.TINY, lambda: True)
  router.register_backend('placeholder', ModelTier.TINY, lambda: True)

  output = router.list_models()

  has_content = 'AVAILABLE MODELS' in output or 'models' in output.lower()
  print(f"  {'✓' if has_content else '✗'} Model list output generated")

  if has_content:
    lines = output.strip().split('\n')
    print(f"      Output: {len(lines)} lines")

  return has_content


def run_all_tests():
  """Run all Phase 6 tests"""
  print("\n" + "="*60)
  print("   TAPAN_AI PHASE 6 - Test Suite")
  print("   Local Brain + Multi Model Router")
  print("="*60)

  results = {
    'Router Decisions': test_router_decisions(),
    'Task Type Inference': test_task_type_inference(),
    'RAG Retrieval': test_rag_retrieval(),
    'Ask Flow': test_ask_flow(),
    'Persona Formatting': test_persona_formatting(),
    'Backend Interfaces': test_backend_interfaces(),
    'Model List': test_model_list(),
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
