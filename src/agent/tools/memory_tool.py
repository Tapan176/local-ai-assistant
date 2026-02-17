"""
Memory Tool - Facts & Preferences
"""
from typing import Any, Dict, List, Optional
from pathlib import Path
from src.agent.tools.base import BaseTool, ToolResult
from src.db.base_repository import BaseRepository

class MemoryTool(BaseTool):
  def __init__(self, data_dir: Path):
    self.data_dir = Path(data_dir)
    self.db_path = self.data_dir / "memories.db"

    schema = """
    CREATE TABLE IF NOT EXISTS memories (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      text TEXT NOT NULL,
      category TEXT DEFAULT 'fact',
      tags TEXT,
      confidence REAL DEFAULT 1.0,
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """
    self.repo = BaseRepository(self.db_path, "memories", schema)

  @property
  def name(self) -> str:
    return "memory"

  @property
  def description(self) -> str:
    return "Remember facts and preferences"

  @property
  def actions(self) -> list:
    return ["remember", "delete_all", "delete_by_text", "list"]

  def execute(self, action: str, params: Dict[str, Any]) -> ToolResult:
    try:
      if action == "remember":
        return self.remember(params)
      if action == "list":
        return self.list_memories()
      if action == "delete_all":
        count = self.repo.delete_all()
        return ToolResult(True, f"Forgot {count} memories.")
      if action == "delete_by_text":
        return self.delete_by_text(params)

      return ToolResult(False, f"Unknown action: {action}")
    except Exception as e:
      return ToolResult(False, f"Error: {str(e)}")

  def remember(self, params: Dict) -> ToolResult:
    text = params.get("text")
    if not text: return ToolResult(False, "Text required.")

    # Check duplicate
    existing = self.repo.search_by_text(text, columns=["text"])
    if existing:
      return ToolResult(True, f"Already remember: {text}")

    self.repo.create({
      "text": text,
      "category": params.get("category", "fact"),
      "tags": params.get("tags", "")
    })

    # Auto-index into KnowledgeManager for RAG (non-fatal)
    try:
      from src.core.knowledge import KnowledgeManager
      kb_path = self.data_dir / "knowledge.db"
      km = KnowledgeManager(kb_path, self.data_dir)
      km.ingest_from_memory([(text, "")])
    except Exception:
      pass

    # Save to Semantic Memory (Vector Store)
    try:
      from src.agent.semantic_memory import SemanticMemory
      sm = SemanticMemory(self.data_dir)
      sm.remember(text, {"category": params.get("category", "fact"), "tags": params.get("tags", "")})
    except Exception as e:
      print(f"[MemoryTool] Semantic save failed: {e}")

    return ToolResult(True, f"[OK] Remembered: {text}")

  def list_memories(self) -> ToolResult:
    items = self.repo.list(limit=50)
    if not items: return ToolResult(True, "No memories yet.")
    lines = ["[MEMORIES] Your Memories:"]
    for i in items:
      lines.append(f"- {i['text']} ({i.get('category')})")
    return ToolResult(True, "\n".join(lines))

  def delete_by_text(self, params: Dict) -> ToolResult:
    text = params.get("text")
    if not text: return ToolResult(False, "Text required.")
    count = self.repo.delete_by_text(text)
    return ToolResult(True, f"Deleted {count} memories matching '{text}'.")
