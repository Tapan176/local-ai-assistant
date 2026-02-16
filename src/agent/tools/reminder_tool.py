"""
Reminder Tool - Time Management
"""
from typing import Any, Dict, List, Optional
from pathlib import Path
from src.agent.tools.base import BaseTool, ToolResult
from src.db.base_repository import BaseRepository

class ReminderTool(BaseTool):
  def __init__(self, data_dir: Path):
    self.data_dir = Path(data_dir)
    self.db_path = self.data_dir / "reminders.db"

    schema = """
    CREATE TABLE IF NOT EXISTS reminders (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      text TEXT NOT NULL,
      due_date TEXT,
      status TEXT DEFAULT 'pending',
      priority INTEGER DEFAULT 1,
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """
    self.repo = BaseRepository(self.db_path, "reminders", schema)

  @property
  def name(self) -> str:
    return "reminder"

  @property
  def description(self) -> str:
    return "Manage reminders and tasks"

  @property
  def actions(self) -> list:
    return ["add", "list", "delete", "delete_by_text", "delete_by_id", "update", "mark_done"]

  def execute(self, action: str, params: Dict[str, Any]) -> ToolResult:
    try:
      if action == "add":
        return self.add(params)
      if action == "list":
        return self.list_reminders(params)
      if action == "delete" or action == "delete_by_text":
        return self.delete_by_text(params)
      if action == "delete_by_id":
        return self.delete_by_id(params)
      if action == "update":
        return self.update(params)
      if action == "mark_done":
        return self.mark_done(params)

      return ToolResult(False, f"Unknown action: {action}")
    except Exception as e:
      return ToolResult(False, f"Error: {str(e)}")

  def delete_by_id(self, params: Dict) -> ToolResult:
    id_ = params.get("id")
    if not id_: return ToolResult(False, "ID required.")
    success = self.repo.delete(id_)
    if success:
      return ToolResult(True, f"Deleted reminder {id_}.")
    return ToolResult(False, f"Reminder {id_} not found.")

  def add(self, params: Dict) -> ToolResult:
    text = params.get("text")
    if not text: return ToolResult(False, "Text required.")

    self.repo.create({
      "text": text,
      "due_date": params.get("due_date", ""),
      "priority": int(params.get("priority", 1))
    })
    return ToolResult(True, f"✓ Reminder added: {text}")

  def list_reminders(self, params: Dict) -> ToolResult:
    status = params.get("status", "pending")
    items = self.repo.list({"status": status}, limit=50)

    if not items: return ToolResult(True, "No pending reminders.")
    lines = ["📋 Reminders:"]
    for i in items:
      lines.append(f"- {i['text']} (Due: {i.get('due_date') or 'Anytime'})")
    return ToolResult(True, "\n".join(lines))

  def delete_by_text(self, params: Dict) -> ToolResult:
    text = params.get("text")
    if not text: return ToolResult(False, "Text required.")
    count = self.repo.delete_by_text(text)
    return ToolResult(True, f"Deleted {count} reminders.")

  def update(self, params: Dict) -> ToolResult:
    item_id = params.get("id")
    new_text = params.get("new_text")
    
    if item_id:
      updates = {}
      if new_text: updates["text"] = new_text
      if "due_date" in params: updates["due_date"] = params["due_date"]
      if "priority" in params: updates["priority"] = params["priority"]
      
      if self.repo.update(item_id, updates):
        return ToolResult(True, f"Updated reminder {item_id}.")
      return ToolResult(False, f"Reminder {item_id} not found.")

    search = params.get("search_text")
    if not search: return ToolResult(False, "Search text required.")
    
    count = self.repo.update_by_text(search, {"text": new_text})
    return ToolResult(True, f"Updated {count} reminders.")

  def mark_done(self, params: Dict) -> ToolResult:
    text = params.get("text")
    if not text: return ToolResult(False, "Text required.")
    count = self.repo.update_by_text(text, {"status": "done"})
    return ToolResult(True, f"Marked {count} reminders as done.")
