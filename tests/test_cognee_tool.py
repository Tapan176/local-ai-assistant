"""
Tests for CogneeTool - Semantic memory tool.
Uses mocks to test without requiring Cognee/Neo4j.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock
from dataclasses import dataclass

import pytest

project_root = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(project_root))

from src.agent.tools.base import ToolResult


# === Mock Cognee types ===

@dataclass
class MockMemoryNode:
    id: str = "test_node_1"
    type: str = "Preference"
    text: str = "test"
    domain: str = "memory"


@dataclass
class MockRecallResult:
    text: str = "I like pizza"
    node_id: str = "node_1"
    node_type: str = "Preference"
    confidence: float = 0.95
    source: str = "cache"
    timestamp: str = "2025-01-01"
    related_nodes: list = None

    def __post_init__(self):
        if self.related_nodes is None:
            self.related_nodes = []


# === Tests ===

class TestCogneeToolBasics:
    """Test CogneeTool interface and graceful degradation."""

    def test_tool_properties(self):
        """Test that CogneeTool has correct BaseTool properties."""
        from src.agent.tools.cognee_tool import CogneeTool
        tool = CogneeTool(Path("test_data"))
        assert tool.name == "cognee"
        assert "cognee" in tool.description.lower() or "semantic" in tool.description.lower()
        assert "recall" in tool.actions
        assert "remember" in tool.actions

    def test_unknown_action(self):
        """Test unknown action returns error."""
        from src.agent.tools.cognee_tool import CogneeTool
        tool = CogneeTool(Path("test_data"))
        result = tool.execute("nonexistent_action", {})
        assert not result.success
        assert "Unknown action" in result.message

    def test_remember_without_text(self):
        """Test remember with missing text returns error."""
        from src.agent.tools.cognee_tool import CogneeTool
        tool = CogneeTool(Path("test_data"))
        result = tool.execute("remember", {})
        assert not result.success
        assert "Text required" in result.message

    def test_recall_without_query(self):
        """Test recall with missing query returns error."""
        from src.agent.tools.cognee_tool import CogneeTool
        tool = CogneeTool(Path("test_data"))
        result = tool.execute("recall", {})
        assert not result.success


class TestCogneeToolWithMockedBrain:
    """Test CogneeTool with mocked CogneeBrainSync."""

    @pytest.fixture
    def tool_with_brain(self):
        from src.agent.tools.cognee_tool import CogneeTool
        tool = CogneeTool(Path("test_data"))
        # Mock the brain
        mock_brain = MagicMock()
        tool._brain = mock_brain
        tool._available = True
        return tool, mock_brain

    def test_remember_success(self, tool_with_brain):
        tool, brain = tool_with_brain
        brain.remember.return_value = MockMemoryNode(id="node_42", text="pizza lover")

        result = tool.execute("remember", {"text": "I love pizza", "domain": "memory"})
        assert result.success
        assert "Cognee remembered" in result.message
        brain.remember.assert_called_once()

    def test_recall_with_results(self, tool_with_brain):
        tool, brain = tool_with_brain
        brain.recall.return_value = [
            MockRecallResult(text="I like pizza", confidence=0.95),
            MockRecallResult(text="Pizza at Mario's", confidence=0.80),
        ]

        result = tool.execute("recall", {"query": "pizza"})
        assert result.success
        assert "Cognitive Recall" in result.message
        assert "pizza" in result.message.lower()

    def test_recall_no_results(self, tool_with_brain):
        tool, brain = tool_with_brain
        brain.recall.return_value = []

        result = tool.execute("recall", {"query": "nonexistent"})
        assert result.success
        assert "No matching" in result.message

    def test_multi_hop(self, tool_with_brain):
        tool, brain = tool_with_brain
        brain.multi_hop_query.return_value = [
            MockRecallResult(text="gym → mood improvement", node_type="Correlation"),
        ]

        result = tool.execute("multi_hop", {"query": "gym and mood"})
        assert result.success
        assert "Multi-hop" in result.message

    def test_health_check(self, tool_with_brain):
        tool, brain = tool_with_brain
        brain.check_health.return_value = {"neo4j": True, "cache": True}

        result = tool.execute("health", {})
        assert result.success
        assert "Health" in result.message

    def test_delete_all(self, tool_with_brain):
        tool, brain = tool_with_brain
        # Add a mock cache
        brain._brain = MagicMock()
        brain._brain._cache = {"key": "value"}

        result = tool.execute("delete_all", {})
        assert result.success
        assert "cleared" in result.message.lower()


class TestCogneeUnavailable:
    """Test graceful degradation when Cognee is not installed."""

    def test_remember_when_unavailable(self):
        from src.agent.tools.cognee_tool import CogneeTool
        tool = CogneeTool(Path("test_data"))
        tool._available = False

        result = tool.execute("remember", {"text": "test"})
        assert not result.success
        assert "not available" in result.message.lower()

    def test_recall_when_unavailable(self):
        from src.agent.tools.cognee_tool import CogneeTool
        tool = CogneeTool(Path("test_data"))
        tool._available = False

        result = tool.execute("recall", {"query": "test"})
        assert not result.success
        assert "not available" in result.message.lower()

    def test_health_when_unavailable(self):
        from src.agent.tools.cognee_tool import CogneeTool
        tool = CogneeTool(Path("test_data"))
        tool._available = False

        result = tool.execute("health", {})
        assert result.success  # health check should succeed
        assert "NOT AVAILABLE" in result.message
