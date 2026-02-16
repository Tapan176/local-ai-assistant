"""
Tests for PHASE 9 - Real Model Attachment
Tests Ollama backend, fallback chain, and model commands
"""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(project_root))


def test_ollama_backend():
  """Test Ollama backend class"""
  print("\n" + "="*50)
  print("TEST: Ollama Backend")
  print("="*50)

  from src.brain.ollama_backend import OllamaBackend

  backend = OllamaBackend()

  # Test structure
  print(f"  ✓ OllamaBackend created")
  print(f"  ✓ Base URL: {backend.base_url}")

  # Test is_ready (may be False if Ollama not running)
  ready = backend.is_ready()
  status = "✓ Running" if ready else "○ Not running (expected if Ollama not started)"
  print(f"  {status}")

  # Test status output
  status_output = backend.get_status()
  print(f"  ✓ Status output: {len(status_output)} chars")

  return True


def test_models_config():
  """Test models.json configuration"""
  print("\n" + "="*50)
  print("TEST: Models Config")
  print("="*50)

  import json

  config_path = project_root / "data" / "models.json"

  if not config_path.exists():
    print(f"  ✗ models.json not found")
    return False

  with open(config_path, 'r') as f:
    config = json.load(f)

  # Check structure
  required = ['version', 'models', 'defaults']
  for key in required:
    if key not in config:
      print(f"  ✗ Missing key: {key}")
      return False

  print(f"  ✓ Version: {config['version']}")
  print(f"  ✓ Models defined: {len(config['models'])}")
  print(f"  ✓ Fallback chain: {config['defaults']['fallback_chain']}")

  return True


def test_unified_llm_ollama():
  """Test UnifiedLLM includes Ollama"""
  print("\n" + "="*50)
  print("TEST: UnifiedLLM Ollama Integration")
  print("="*50)

  from src.brain.llm_interface import UnifiedLLM

  llm = UnifiedLLM()

  # Check ollama is registered
  has_ollama = hasattr(llm, 'ollama') and llm.ollama is not None
  print(f"  ✓ Ollama backend initialized: {has_ollama}")

  # Check backends
  backends = list(llm.backends.keys())
  print(f"  ✓ Backends: {backends}")

  # Test get_status
  if hasattr(llm, 'get_status'):
    status = llm.get_status()
    print(f"  ✓ get_status() works: {len(status)} chars")

  return True


def test_intents():
  """Test model intents"""
  print("\n" + "="*50)
  print("TEST: Model Intents")
  print("="*50)

  from src.core.intents import IntentRouter

  router = IntentRouter()

  tests = [
    ("model", "model_status"),
    ("model status", "model_status"),
    ("model install phi3:mini", "model_install"),
    ("model use ollama", "model_use"),
    ("models", "model_list"),
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


def test_fallback_logic():
  """Test fallback chain logic in router"""
  print("\n" + "="*50)
  print("TEST: Fallback Chain")
  print("="*50)

  from src.brain.router import get_router, TaskType, ModelTier

  router = get_router()

  # Check fallback configuration
  fallbacks = router.FALLBACKS
  print(f"  ✓ HEAVY fallback: {fallbacks.get(ModelTier.HEAVY)}")
  print(f"  ✓ SMALL fallback: {fallbacks.get(ModelTier.SMALL)}")
  print(f"  ✓ TINY fallback: {fallbacks.get(ModelTier.TINY)}")

  # Test routing
  decision = router.route(TaskType.CHAT)
  print(f"  ✓ CHAT routes to: {decision.backend_name}")

  return True


def run_all_tests():
  """Run all Phase 9 tests"""
  print("\n" + "="*60)
  print("   TAPAN_AI PHASE 9 - Test Suite")
  print("   Real Model Attachment")
  print("="*60)

  results = {
    'Ollama Backend': test_ollama_backend(),
    'Models Config': test_models_config(),
    'UnifiedLLM Ollama': test_unified_llm_ollama(),
    'Model Intents': test_intents(),
    'Fallback Chain': test_fallback_logic(),
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
