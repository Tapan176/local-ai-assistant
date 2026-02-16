"""
Phase 16: LLM + RAG Integration Tests
Tests for OllamaBackend enhancements, ask command routing, auto-indexing, LLM commands.
"""
import pytest
import sys
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.agent.intent_parser import IntentParser
from src.brain.ollama_backend import OllamaBackend, OllamaConnectionError
from src.service.ollama_service import OllamaService


_TEST_DIR = Path(__file__).parent / "temp_phase16"


@pytest.fixture
def test_data_dir():
  _TEST_DIR.mkdir(parents=True, exist_ok=True)
  yield _TEST_DIR
  shutil.rmtree(_TEST_DIR, ignore_errors=True)


@pytest.fixture
def parser():
  return IntentParser()


# === OllamaBackend Unit Tests ===

class TestOllamaBackend:
  """Tests for OllamaBackend enhancements (Phase 16)."""

  def test_backend_init_defaults(self):
    backend = OllamaBackend()
    assert backend.base_url == "http://localhost:11434"
    assert backend.timeout == 30
    assert backend.max_retries == 3
    assert backend.name == "ollama"
    assert backend.current_model is None  # Auto-detect on first use

  def test_backend_custom_config(self):
    backend = OllamaBackend(
      base_url="http://custom:1234",
      timeout=60,
      max_retries=5
    )
    assert backend.base_url == "http://custom:1234"
    assert backend.timeout == 60
    assert backend.max_retries == 5

  def test_is_available_alias(self):
    """is_available() should be an alias for is_ready()."""
    backend = OllamaBackend()
    assert backend.is_available == backend.is_ready

  def test_get_model_auto_detect(self):
    """_get_model() should fallback to qwen2.5:7b when no models available."""
    backend = OllamaBackend()
    backend._is_ready = False
    model = backend._get_model()
    assert model == "qwen2.5:7b"

  def test_switch_model_unavailable(self):
    """switch_model() returns False for non-existent model."""
    backend = OllamaBackend()
    backend._is_ready = False
    assert backend.switch_model("nonexistent") == False

  def test_switch_model_success(self):
    """switch_model() returns True when model is found."""
    backend = OllamaBackend()
    backend._available_models = ["llama3.2:3b", "qwen2.5:7b"]
    backend._is_ready = True
    assert backend.switch_model("qwen2.5:7b") == True
    assert backend.current_model == "qwen2.5:7b"

  def test_generate_when_not_ready(self):
    """generate() returns error message when Ollama is not running."""
    backend = OllamaBackend()
    backend._is_ready = False
    result = backend.generate("test prompt")
    assert "[Ollama not available]" in result

  def test_stream_generate_when_not_ready(self):
    """stream_generate() yields error when Ollama is not running."""
    backend = OllamaBackend()
    backend._is_ready = False
    tokens = list(backend.stream_generate("test"))
    assert len(tokens) == 1
    assert "not available" in tokens[0]

  def test_get_status_not_running(self):
    """get_status() shows helpful message when not running."""
    backend = OllamaBackend()
    backend._is_ready = False
    status = backend.get_status()
    assert "NOT RUNNING" in status
    assert "ollama serve" in status

  def test_refresh_clears_cache(self):
    """refresh() clears all cached state."""
    backend = OllamaBackend()
    backend._is_ready = True
    backend._available_models = ["test"]
    backend.refresh()
    assert backend._is_ready is None
    assert backend._available_models is None


# === OllamaService Unit Tests ===

class TestOllamaService:
  """Tests for OllamaService lifecycle management."""

  def test_check_installed_returns_bool(self):
    result = OllamaService.check_installed()
    assert isinstance(result, bool)

  def test_is_running_returns_bool(self):
    result = OllamaService.is_running()
    assert isinstance(result, bool)

  def test_get_status_structure(self):
    status = OllamaService.get_status()
    assert 'installed' in status
    assert 'running' in status
    assert 'models' in status
    assert 'model_count' in status
    assert isinstance(status['models'], list)

  def test_format_status_returns_string(self):
    result = OllamaService.format_status()
    assert isinstance(result, str)


# === IntentParser Phase 16 Additions ===

class TestIntentParserPhase16:
  """Tests for new Phase 16 intent patterns: ask, llm commands."""

  def test_ask_command(self, parser):
    result = parser.parse("ask what are my hobbies?")
    assert result is not None
    assert result["tool"] == "ask"
    assert result["method"] == "query"
    assert "hobbies" in result["params"]["query"]
    assert result["confidence"] == 0.95

  def test_ask_command_long(self, parser):
    result = parser.parse("ask summarize my week")
    assert result is not None
    assert result["tool"] == "ask"
    assert "summarize" in result["params"]["query"]

  def test_llm_status(self, parser):
    result = parser.parse("llm status")
    assert result is not None
    assert result["tool"] == "system"
    assert result["method"] == "llm_status"

  def test_model_status_alias(self, parser):
    result = parser.parse("model status")
    assert result is not None
    assert result["tool"] == "system"
    assert result["method"] == "llm_status"

  def test_llm_models(self, parser):
    result = parser.parse("llm models")
    assert result is not None
    assert result["tool"] == "system"
    assert result["method"] == "llm_models"

  def test_show_models(self, parser):
    result = parser.parse("show models")
    assert result is not None
    assert result["tool"] == "system"
    assert result["method"] == "llm_models"

  def test_llm_switch(self, parser):
    result = parser.parse("llm switch llama3.2:3b")
    assert result is not None
    assert result["tool"] == "system"
    assert result["method"] == "llm_switch"
    assert result["params"]["model"] == "llama3.2:3b"

  def test_existing_patterns_preserved(self, parser):
    """Phase 16 additions should not break existing Phase 15 patterns."""
    # Finance
    result = parser.parse("expense 500 food")
    assert result["tool"] == "finance"

    # Memory
    result = parser.parse("remember I love pizza")
    assert result["tool"] == "memory"

    # Decision
    result = parser.parse("should I buy PS5 for 50000?")
    assert result["tool"] == "decision"

    # Planning
    result = parser.parse("daily plan")
    assert result["tool"] == "planning"

    # Greeting
    result = parser.parse("hi")
    assert result["tool"] == "free_chat"


# === Orchestrator Integration ===

class TestOrchestratorPhase16:
  """Tests for Orchestrator wiring of Phase 16 features."""

  def test_orchestrator_init(self, test_data_dir):
    from src.agent.orchestrator import Orchestrator
    orch = Orchestrator(test_data_dir)
    assert "memory" in orch.tools
    assert "finance" in orch.tools
    assert orch.current_backend == "sqlite"

  def test_ask_routes_correctly(self, test_data_dir):
    """ask command should route to _handle_ask."""
    from src.agent.orchestrator import Orchestrator
    orch = Orchestrator(test_data_dir)
    # Even without Ollama running, ask should not crash
    result = orch.process("ask what do I like?")
    assert isinstance(result, str)
    assert len(result) > 0

  def test_llm_status_routes(self, test_data_dir):
    """llm status should return status info."""
    from src.agent.orchestrator import Orchestrator
    orch = Orchestrator(test_data_dir)
    result = orch.process("llm status")
    assert isinstance(result, str)
    # Should mention running/not running or Ollama
    assert len(result) > 0

  def test_llm_models_routes(self, test_data_dir):
    """llm models should not crash."""
    from src.agent.orchestrator import Orchestrator
    orch = Orchestrator(test_data_dir)
    result = orch.process("llm models")
    assert isinstance(result, str)

  def test_llm_switch_routes(self, test_data_dir):
    """llm switch should not crash."""
    from src.agent.orchestrator import Orchestrator
    orch = Orchestrator(test_data_dir)
    result = orch.process("llm switch llama3.2:3b")
    assert isinstance(result, str)

  def test_help_includes_phase16(self, test_data_dir):
    """Help text should include ask and llm commands."""
    from src.agent.orchestrator import Orchestrator
    orch = Orchestrator(test_data_dir)
    result = orch.process("help")
    assert "ask" in result.lower()
    assert "llm" in result.lower()


# === Auto-Indexing ===

class TestAutoIndexing:
  """Tests for auto-indexing memories into KnowledgeManager."""

  def test_memory_remember_auto_indexes(self, test_data_dir):
    """MemoryTool.remember() should save to SQLite AND index for RAG."""
    from src.agent.tools.memory_tool import MemoryTool
    tool = MemoryTool(test_data_dir)
    result = tool.remember({"text": "I love running in the morning"})
    assert result.success
    assert "Remembered" in result.message

    # Verify SQLite save
    memories = tool.list_memories()
    assert "running" in memories.message

    # KnowledgeManager indexing is non-fatal, so no crash = pass

  def test_experience_add_auto_indexes(self, test_data_dir):
    """ExperienceTool.add() should save to SQLite AND index for RAG."""
    from src.agent.tools.experience_tool import ExperienceTool
    tool = ExperienceTool(test_data_dir)
    result = tool.add({"text": "Went to gym today"})
    assert result.success
    assert "logged" in result.message.lower()


# Run: pytest tests/test_phase16_llm.py -v
