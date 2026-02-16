"""
Relation Tool - People & Connections
"""
from typing import Any, Dict, List, Optional
from pathlib import Path
from src.agent.tools.base import BaseTool, ToolResult
from src.db.base_repository import BaseRepository

class RelationTool(BaseTool):
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.db_path = self.data_dir / "relations.db"
        
        schema = """
        CREATE TABLE IF NOT EXISTS relations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            relationship TEXT,
            notes TEXT,
            last_interaction TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
        self.repo = BaseRepository(self.db_path, "relations", schema)

    @property
    def name(self) -> str:
        return "relation"

    @property
    def description(self) -> str:
        return "Manage people and relationships"

    @property
    def actions(self) -> list:
        return ["add", "list", "delete", "delete_by_text", "get"]

    def execute(self, action: str, params: Dict[str, Any]) -> ToolResult:
        try:
            if action == "add":
                return self.add(params)
            if action == "list":
                return self.list_relations()
            if action == "delete" or action == "delete_by_text":
                return self.delete_by_text(params)
            if action == "get" or action == "who":
                return self.get_relation(params)
                
            return ToolResult(False, f"Unknown action: {action}")
        except Exception as e:
            return ToolResult(False, f"Error: {str(e)}")

    def add(self, params: Dict) -> ToolResult:
        name = params.get("name")
        if not name: return ToolResult(False, "Name required.")
        
        # Upsert logic? BaseRepository doesn't natively upsert yet.
        # Check exist
        existing = self.repo.search_by_text(name, columns=["name"])
        if existing:
             # Update
             self.repo.update_by_text(name, {
                 "relationship": params.get("relationship", existing[0].get("relationship")),
                 "notes": params.get("notes", "")
             }, "name")
             return ToolResult(True, f"Updated relation: {name}")
             
        self.repo.create({
            "name": name,
            "relationship": params.get("relationship", "acquantance"),
            "notes": params.get("notes", "")
        })
        return ToolResult(True, f"Added relation: {name}")

    def list_relations(self) -> ToolResult:
        items = self.repo.list(limit=50)
        if not items: return ToolResult(True, "No relations found.")
        lines = ["👥 People:"]
        for i in items:
            lines.append(f"- {i['name']} ({i.get('relationship')})")
        return ToolResult(True, "\n".join(lines))

    def delete_by_text(self, params: Dict) -> ToolResult:
        text = params.get("text") or params.get("name")
        if not text: return ToolResult(False, "Name required.")
        count = self.repo.delete_by_text(text, column="name")
        return ToolResult(True, f"Deleted {count} relations.")

    def get_relation(self, params: Dict) -> ToolResult:
        name = params.get("name")
        if not name: return ToolResult(False, "Name required.")
        items = self.repo.search_by_text(name, columns=["name"])
        if not items: return ToolResult(True, f"Who is {name}? I don't know yet.")
        
        i = items[0]
        return ToolResult(True, f"👤 {i['name']}\nRelationship: {i.get('relationship')}\nNotes: {i.get('notes')}")
