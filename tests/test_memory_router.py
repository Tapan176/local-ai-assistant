"""
Tests for MemoryRouter - SQLite vs Cognee routing logic.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on sys.path
project_root = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(project_root))

from src.agent.tools.base import ToolResult
from src.agent.memory_router import MemoryRouter
from src.agent.intent_parser import IntentParser


# === Fixtures ===

@pytest.fixture
def mock_sqlite():
  """Mock MemoryTool (SQLite backend)."""
  tool = MagicMock()
  tool.name = "memory"
  tool.execute.return_value = ToolResult(True, "SQLite result")
  return tool


@pytest.fixture
def mock_cognee():
  """Mock CogneeTool (Cognee backend)."""
  tool = MagicMock()
  tool.name = "cognee"
  tool.execute.return_value = ToolResult(True, "Cognee result")
  return tool


@pytest.fixture
def router(mock_sqlite, mock_cognee):
  return MemoryRouter(mock_sqlite, mock_cognee)


@pytest.fixture
def router_no_cognee(mock_sqlite):
  return MemoryRouter(mock_sqlite, None)


# === Routing Tests ===

class TestRouting:
  """Test that actions route to the correct backend."""

  def test_remember_goes_to_sqlite(self, router, mock_sqlite):
    result = router.route("remember", {"text": "I like pizza"})
    mock_sqlite.execute.assert_called_once_with("remember", {"text": "I like pizza"})
    assert result.success

  def test_list_goes_to_sqlite(self, router, mock_sqlite):
    result = router.route("list", {})
    mock_sqlite.execute.assert_called_once_with("list", {})
    assert result.success

  def test_delete_all_goes_to_sqlite(self, router, mock_sqlite):
    result = router.route("delete_all", {})
    mock_sqlite.execute.assert_called_once_with("delete_all", {})
    assert result.success

  def test_recall_goes_to_cognee(self, router, mock_cognee):
    result = router.route("recall", {"query": "food preferences"})
    mock_cognee.execute.assert_called_once_with("recall", {"query": "food preferences"})
    assert result.success
    assert result.message == "Cognee result"

  def test_search_goes_to_cognee(self, router, mock_cognee):
    result = router.route("search", {"query": "gym"})
    mock_cognee.execute.assert_called_once_with("search", {"query": "gym"})
    assert result.success

  def test_multi_hop_goes_to_cognee(self, router, mock_cognee):
    result = router.route("multi_hop", {"query": "how does gym relate to mood"})
    mock_cognee.execute.assert_called_once_with("multi_hop", {"query": "how does gym relate to mood"})
    assert result.success

  def test_health_goes_to_cognee(self, router, mock_cognee):
    result = router.route("health", {})
    mock_cognee.execute.assert_called_once_with("health", {})
    assert result.success


# === Fallback Tests ===

class TestFallback:
  """Test fallback when Cognee is unavailable."""

  def test_recall_fallback_to_sqlite_when_no_cognee(self, router_no_cognee, mock_sqlite):
    result = router_no_cognee.route("recall", {"query": "food"})
    # Should fall back to SQLite list
    mock_sqlite.execute.assert_called()
    assert result.success

  def test_cognee_failure_falls_back_to_sqlite(self, router, mock_cognee, mock_sqlite):
    mock_cognee.execute.return_value = ToolResult(False, "Cognee error")
    result = router.route("recall", {"query": "food"})
    # Should fall back to SQLite
    mock_sqlite.execute.assert_called()

  def test_remember_unaffected_by_cognee_absence(self, router_no_cognee, mock_sqlite):
    result = router_no_cognee.route("remember", {"text": "test"})
    mock_sqlite.execute.assert_called_once_with("remember", {"text": "test"})
    assert result.success


# === Keyword Detection Tests ===

class TestKeywordDetection:
  """Test is_cognee_query heuristic."""

  @pytest.mark.parametrize("text", [
    "recall my food preferences",
    "deep recall gym sessions",
    "search memory pizza",
    "what was the last time I went to gym",
    "when did I meet Rahul",
    "who was at the party",
    "how did my mood relate to exercise",
  ])
  def test_cognee_queries_detected(self, text):
    assert MemoryRouter.is_cognee_query(text)

  @pytest.mark.parametrize("text", [
    "remember I like pizza",
    "show memories",
    "list memories",
    "expense 500 food",
    "hello",
  ])
  def test_non_cognee_queries_not_detected(self, text):
    assert not MemoryRouter.is_cognee_query(text)


# === IntentParser Integration Tests ===

class TestIntentParserCognee:
  """Test IntentParser recognises new Cognee intents."""

  @pytest.fixture
  def parser(self):
    return IntentParser()

  def test_recall_intent(self, parser):
    result = parser.parse("recall my pizza preference")
    assert result is not None
    assert result["tool"] == "cognee"
    assert result["method"] == "recall"
    assert "pizza" in result["params"]["query"]

  def test_deep_recall_intent(self, parser):
    result = parser.parse("deep recall gym habits")
    assert result is not None
    assert result["tool"] == "cognee"
    assert result["method"] == "recall"
    assert "gym" in result["params"]["query"]

  def test_search_memory_intent(self, parser):
    result = parser.parse("search memory food")
    assert result is not None
    assert result["tool"] == "cognee"
    assert result["method"] == "search"
    assert "food" in result["params"]["query"]

  def test_multi_hop_intent(self, parser):
    result = parser.parse("how does gym relate to mood")
    assert result is not None
    assert result["tool"] == "cognee"
    assert result["method"] == "multi_hop"

  def test_cognee_health_intent(self, parser):
    result = parser.parse("cognee health")
    assert result is not None
    assert result["tool"] == "cognee"
    assert result["method"] == "health"

  def test_remember_still_goes_to_sqlite(self, parser):
    """Ensure existing 'remember' intent still works."""
    result = parser.parse("remember I like pizza")
    assert result is not None
    assert result["tool"] == "memory"
    assert result["method"] == "remember"

  def test_show_memories_still_works(self, parser):
    """Ensure 'show memories' still routes to SQLite."""
    result = parser.parse("show memories")
    assert result is not None
    assert result["tool"] == "memory"
    assert result["method"] == "list"
