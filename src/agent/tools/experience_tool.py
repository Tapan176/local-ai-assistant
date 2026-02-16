"""
Experience Tool - Life Logging & Stats
"""
from typing import Any, Dict, List, Optional
from pathlib import Path
from src.agent.tools.base import BaseTool, ToolResult
from src.db.base_repository import BaseRepository

class ExperienceTool(BaseTool):
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.db_path = self.data_dir / "experiences.db"
        
        schema = """
        CREATE TABLE IF NOT EXISTS experiences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            date TEXT NOT NULL,
            category TEXT DEFAULT 'general',
            place TEXT,
            people TEXT,
            tags TEXT
        )
        """
        self.repo = BaseRepository(self.db_path, "experiences", schema)

    @property
    def name(self) -> str:
        return "experience"

    @property
    def description(self) -> str:
        return "Log and analyze life experiences"

    @property
    def actions(self) -> list:
        return ["add", "log", "stats", "delete_all", "delete_by_category", "delete_by_text", "on_date", "list"]

    def execute(self, action: str, params: Dict[str, Any]) -> ToolResult:
        try:
            if action in ["add", "log"]:
                return self.add(params)
            if action == "stats":
                return self.stats()
            if action == "list":
                return self.list_experiences(params)
            if action == "delete_all":
                count = self.repo.delete_all()
                return ToolResult(True, f"Deleted {count} experiences.")
            if action == "delete_by_category":
                return self.delete_by_category(params)
            if action == "delete_by_text":
                return self.delete_by_text(params)
            if action == "on_date":
                return self.on_date(params)
                
            return ToolResult(False, f"Unknown action: {action}")
        except Exception as e:
            return ToolResult(False, f"Error: {str(e)}")

    def add(self, params: Dict) -> ToolResult:
        text = params.get("text")
        if not text: return ToolResult(False, "Text required.")
        
        self.repo.create({
            "text": text,
            "date": params.get("date", "today"),
            "category": params.get("category", "general"),
            "place": params.get("place", ""),
            "people": params.get("people", ""),
            "tags": params.get("tags", "")
        })
        return ToolResult(True, "Experience logged.")

    def stats(self) -> ToolResult:
        all_exp = self.repo.list(limit=1000)
        total = len(all_exp)
        cats = {}
        for e in all_exp:
            c = e.get("category", "general")
            cats[c] = cats.get(c, 0) + 1
            
        lines = [f"Total Experiences: {total}", "By Category:"]
        for c, n in cats.items():
            lines.append(f"- {c}: {n}")
            
        return ToolResult(True, "\n".join(lines))

    def delete_by_category(self, params: Dict) -> ToolResult:
        cat = params.get("category")
        if not cat: return ToolResult(False, "Category required.")
        # BaseRepository doesn't have delete_by_filter directly, but we can list then bulk_delete
        # Or add delete_by_field to BaseRepository? 
        # For now, list -> bulk delete
        items = self.repo.list({"category": cat}, limit=1000)
        ids = [i['id'] for i in items]
        count = self.repo.bulk_delete(ids)
        return ToolResult(True, f"Deleted {count} items in '{cat}'")

    def delete_by_text(self, params: Dict) -> ToolResult:
        text = params.get("text") or params.get("query")
        if not text: return ToolResult(False, "Text required.")
        count = self.repo.delete_by_text(text)
        return ToolResult(True, f"Deleted {count} matching items.")

    def on_date(self, params: Dict) -> ToolResult:
        date = params.get("date")
        if not date: return ToolResult(False, "Date required.")
        # Naive string match for date
        items = self.repo.search_by_text(date, columns=["date"])
        if not items: return ToolResult(True, f"No entries on {date}")
        
        lines = [f"📅 On {date}:"]
        for i in items:
            lines.append(f"- {i['text']} ({i.get('category')})")
        return ToolResult(True, "\n".join(lines))
