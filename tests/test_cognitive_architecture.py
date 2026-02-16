"""
Test Cognitive Architecture (Phase 20)
"""
import unittest
import sys
from unittest.mock import MagicMock, patch
from pathlib import Path
import json

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from src.agent.semantic_intent_parser import SemanticIntentParser
from src.agent.memory_router import MemoryRouter
from src.agent.tools.base import ToolResult

class TestCognitiveArchitecture(unittest.TestCase):

    def setUp(self):
        self.data_dir = Path("./test_data")
        
    def test_semantic_parser(self):
        mock_llm = MagicMock()
        # Mock LLM response for "save money"
        mock_llm.generate.return_value = '```json\n{"tool": "finance", "method": "expense", "params": {"amount": 100}}\n```'
        
        parser = SemanticIntentParser(self.data_dir, mock_llm)
        result = parser.parse("spent 100 on food")
        
        self.assertEqual(result["tool"], "finance")
        self.assertEqual(result["method"], "expense")
        self.assertEqual(result["params"]["amount"], 100)
        
    def test_memory_router_dual_write(self):
        mock_sqlite = MagicMock()
        mock_cognee = MagicMock()
        
        mock_sqlite.execute.return_value = ToolResult(True, "Saved to SQLite")
        mock_cognee.execute.return_value = ToolResult(True, "Saved to Cognee")
        
        router = MemoryRouter(mock_sqlite, mock_cognee)
        
        # Test Remember (Dual Write)
        res = router.route("remember", {"text": "I like pizza"})
        
        # Check SQLite called
        mock_sqlite.execute.assert_called_with("remember", {"text": "I like pizza"})
        # Check Cognee called (best effort)
        # Check Cognee called (best effort)
        mock_cognee.execute.assert_called_with("remember", {"text": "I like pizza"})
        
        self.assertTrue(res.success)
        self.assertEqual(res.message, "Saved to SQLite")
        
    def test_memory_router_search_fallback(self):
        mock_sqlite = MagicMock()
        mock_cognee = MagicMock()
        
        router = MemoryRouter(mock_sqlite, mock_cognee)
        
        # Case 1: Cognee Success
        mock_cognee.execute.return_value = ToolResult(True, "Found in Graph")
        res = router.route("search", {"query": "pizza"})
        self.assertEqual(res.message, "Found in Graph")
        
        # Case 2: Cognee Failure -> SQLite Fallback
        mock_cognee.execute.return_value = ToolResult(False, "Graph offline")
        mock_sqlite.execute.return_value = ToolResult(True, "Found in SQLite")
        
        res = router.route("search", {"query": "pizza"})
        self.assertEqual(res.message, "Found in SQLite")
        
if __name__ == "__main__":
    unittest.main()
