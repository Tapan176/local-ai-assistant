"""
CogneeTool - Semantic Memory via Cognee + Neo4j
Routes to CogneeBrain for vector/graph-based recall.
"""
from typing import Any, Dict, List, Optional
from pathlib import Path
from src.agent.tools.base import BaseTool, ToolResult

# Graceful import — Cognee is optional
try:
  from src.memory.cognee_brain import CogneeBrainSync, COGNEE_AVAILABLE
except ImportError:
  COGNEE_AVAILABLE = False
  CogneeBrainSync = None


class CogneeTool(BaseTool):
  """Semantic memory tool using Cognee + Neo4j graph."""

  def __init__(self, data_dir: Path):
    self.data_dir = Path(data_dir)
    self._brain = None
    self._available = COGNEE_AVAILABLE

  def _get_brain(self):
    """Lazy-init CogneeBrainSync to avoid import-time failures."""
    if self._brain is None and self._available and CogneeBrainSync is not None:
      try:
        self._brain = CogneeBrainSync(self.data_dir)
      except Exception:
        self._available = False
    return self._brain

  # -- BaseTool interface --

  @property
  def name(self) -> str:
    return "cognee"

  @property
  def description(self) -> str:
    return "Semantic memory recall using Cognee + Neo4j graph"

  @property
  def actions(self) -> list:
    return ["remember", "recall", "search", "multi_hop", "health", "delete_all"]

  def execute(self, action: str, params: Dict[str, Any]) -> ToolResult:
    try:
      if action == "remember":
        return self._remember(params)
      if action in ("recall", "search"):
        return self._recall(params)
      if action == "multi_hop":
        return self._multi_hop(params)
      if action == "health":
        return self._health()
      if action == "delete_all":
        return self._delete_all()
      return ToolResult(False, f"Unknown action: {action}")
    except Exception as e:
      return ToolResult(False, f"Cognee error: {str(e)}")

  # -- Actions --

  def _remember(self, params: Dict) -> ToolResult:
    """Store a memory in the cognitive graph."""
    text = params.get("text")
    if not text:
      return ToolResult(False, "Text required.")

    brain = self._get_brain()
    if brain is None:
      return ToolResult(False, "Cognee is not available. Memory stored in SQLite only.")

    domain = params.get("domain", "memory")
    metadata = params.get("metadata")
    source_id = params.get("source_id")

    node = brain.remember(text=text, domain=domain, metadata=metadata, source_id=source_id)
    return ToolResult(True, f"✓ Cognee remembered: {text} (node: {node.id})", {"node_id": node.id})

  def _recall(self, params: Dict) -> ToolResult:
    """Recall memories semantically from the graph."""
    query = params.get("query") or params.get("text")
    if not query:
      return ToolResult(False, "Query required.")

    brain = self._get_brain()
    if brain is None:
      return ToolResult(False, "Cognee is not available. Use 'show memories' for SQLite lookup.")

    domain = params.get("domain")
    limit = params.get("limit", 10)

    results = brain.recall(query=query, domain=domain, limit=limit)
    if not results:
      return ToolResult(True, "No matching memories found in cognitive graph.")

    lines = ["🧠 Cognitive Recall:"]
    for r in results:
      conf = f"{r.confidence:.0%}" if r.confidence else "?"
      lines.append(f"- {r.text} [{r.node_type}, {conf}]")
    return ToolResult(True, "\n".join(lines), {"count": len(results)})

  def _multi_hop(self, params: Dict) -> ToolResult:
    """Execute multi-hop graph query for complex questions."""
    query = params.get("query") or params.get("text")
    if not query:
      return ToolResult(False, "Query required.")

    brain = self._get_brain()
    if brain is None:
      return ToolResult(False, "Cognee is not available for multi-hop queries.")

    results = brain.multi_hop_query(query)
    if not results:
      return ToolResult(True, "No results from multi-hop graph traversal.")

    lines = ["🔗 Multi-hop Results:"]
    for r in results:
      lines.append(f"- {r.text} [{r.node_type}]")
      if r.related_nodes:
        lines.append(f"  → Related: {', '.join(r.related_nodes[:3])}")
    return ToolResult(True, "\n".join(lines), {"count": len(results)})

  def _health(self) -> ToolResult:
    """Check Cognee + Neo4j health status."""
    brain = self._get_brain()
    if brain is None:
      return ToolResult(True, "Cognee: NOT AVAILABLE (dependencies missing)")

    status = brain.check_health()
    lines = ["🏥 Cognee Health:"]
    for key, val in status.items():
      emoji = "✅" if val else "❌"
      lines.append(f"  {emoji} {key}: {val}")
    return ToolResult(True, "\n".join(lines), status)

  def _delete_all(self) -> ToolResult:
    """Clear local Cognee cache (does not touch SQLite)."""
    brain = self._get_brain()
    if brain is None:
      return ToolResult(True, "Cognee not available — nothing to clear.")

    # Clear the in-memory cache
    if hasattr(brain, '_brain') and hasattr(brain._brain, '_cache'):
      brain._brain._cache.clear()
    return ToolResult(True, "Cognee local cache cleared.")
