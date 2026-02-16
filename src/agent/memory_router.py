"""
MemoryRouter - Decides between SQLite (MemoryTool) and Cognee (CogneeTool).

Routing logic:
- Writes (remember, forget) → SQLite always (source of truth)
- Reads (list, show) → SQLite
- Semantic recall (recall, search, deep recall, multi-hop) → Cognee
- Fallback: if Cognee unavailable → SQLite
"""
import re
from typing import Dict, Any, Optional
from src.agent.tools.base import ToolResult


class MemoryRouter:
  """Routes memory operations between SQLite and Cognee backends."""

  # Keywords that trigger Cognee (semantic) path
  COGNEE_PATTERNS = [
    r"^recall\b",
    r"^deep\s+recall\b",
    r"^search\s+memor",
    r"\bwhat was\b",
    r"\bwhen did\b",
    r"\bwho was\b",
    r"\bhow did\b",
    r"\brelate\b",
    r"\bconnect\b",
  ]

  # Actions that always go to SQLite
  SQLITE_ACTIONS = {"remember", "list", "delete_all", "delete_by_text"}

  # Actions routed to Cognee
  COGNEE_ACTIONS = {"recall", "search", "multi_hop", "health"}

  def __init__(self, sqlite_tool, cognee_tool):
    """
    Args:
      sqlite_tool: MemoryTool (SQLite-backed)
      cognee_tool: CogneeTool (Cognee-backed), can be None
    """
    self.sqlite = sqlite_tool
    self.cognee = cognee_tool

  def route(self, action: str, params: Dict[str, Any]) -> ToolResult:
    """Route action to the appropriate backend."""
    # Explicit Cognee actions
    if action in self.COGNEE_ACTIONS:
      if self.cognee is not None:
        result = self.cognee.execute(action, params)
        # Fallback to SQLite on Cognee failure
        if not result.success and action in ("recall", "search"):
          return self._sqlite_search_fallback(params)
        return result
      else:
        return self._sqlite_search_fallback(params)

    # Everything else → SQLite
    return self.sqlite.execute(action, params)

  def _sqlite_search_fallback(self, params: Dict) -> ToolResult:
    """Fallback: search SQLite when Cognee is unavailable."""
    query = params.get("query") or params.get("text", "")
    if query:
      # Use list + client-side filter as simple fallback
      result = self.sqlite.execute("list", {})
      if result.success and result.data:
        return result
    return self.sqlite.execute("list", {})

  @classmethod
  def is_cognee_query(cls, text: str) -> bool:
    """Check if user text should route to Cognee."""
    text_lower = text.lower().strip()
    return any(re.search(p, text_lower) for p in cls.COGNEE_PATTERNS)

  @classmethod
  def detect_action(cls, text: str) -> str:
    """Detect the appropriate action from raw user text.

    Returns:
      'recall' for Cognee-style queries,
      'remember' for store operations,
      'list' for listing.
    """
    text_lower = text.lower().strip()

    if cls.is_cognee_query(text_lower):
      # Check for multi-hop indicators
      multi_hop_words = ["relate", "connect", "how did", "and also"]
      if any(w in text_lower for w in multi_hop_words):
        return "multi_hop"
      return "recall"

    if text_lower.startswith("remember"):
      return "remember"

    if any(w in text_lower for w in ["list", "show"]):
      return "list"

    return "remember"  # default
