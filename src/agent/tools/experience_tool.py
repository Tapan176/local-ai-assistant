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
    return ["add", "log", "stats", "sum", "delete_all", "delete_by_category", "delete_by_text", "on_date", "list"]

  def execute(self, action: str, params: Dict[str, Any]) -> ToolResult:
    try:
      if action in ["add", "log"]:
        return self.add(params)
      if action == "stats":
        return self.stats()
      if action == "sum":
        return self.get_sum(params)
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

  def get_sum(self, params: Dict) -> ToolResult:
    place = params.get("place")
    category = params.get("category")
    
    filters = {}
    if place: filters["place"] = place
    if category: filters["category"] = category
    
    items = self.repo.list(limit=10000)
    total = 0.0
    count = 0
    
    query_place = place.lower() if place else None
    
    for i in items:
      text_lower = i.get("text", "").lower()
      
      # Check place (in column OR in text)
      if query_place:
        p = i.get("place", "").lower() if i.get("place") else ""
        if query_place not in p and query_place not in text_lower: continue
        
      # Check category
      if category and i.get("category") != category: continue
      
      # Extract amount from text if not in dedicated column
      # Look for number at end or distinct number
      import re
      text = i.get("text", "")
      # match numbers, including simple commas
      # Match: 1,000 or 1000. Optional decimal.
      # Using non-capturing groups so findall returns full strings.
      nums = re.findall(r'(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?', text)
      if nums:
        try:
           # Clean commas from the full match
           val_str = nums[-1].replace(',', '')
           val = float(val_str)
           total += val
           count += 1
        except:
           pass
           
    return ToolResult(True, f"Total spent: {total:,.1f}")

  def list_experiences(self, params: Dict) -> ToolResult:
    limit = params.get("limit", 10)
    text = params.get("text")
    if text:
      # BaseRepo search_by_text doesn't support limit argument
      items = self.repo.search_by_text(text)
      items = items[:limit]
    else:
      items = self.repo.list(limit=limit)
    
    lines = []
    for i in items:
      d = i.get("date", "")
      t = i.get("text", "")
      lines.append(f"- {t} ({d})")
      
    if not lines: return ToolResult(True, "No experiences found.")
    return ToolResult(True, "\n".join(lines))

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

    # Auto-index into KnowledgeManager for RAG (non-fatal)
    try:
      from src.core.knowledge import KnowledgeManager
      pass 
    except Exception:
      pass 

    return ToolResult(True, f"Logged experience: {text}")

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
