"""
Persona Tool - Self-Identity management
Stores: traits, values, core memories, communication style
"""
from typing import Dict, Any, List
import sqlite3
from pathlib import Path
from src.agent.tools.base import BaseTool, ToolResult


class PersonaTool(BaseTool):
  """
  Manages the agent's self-identity (Persona).
  Stores:
  - Traits (e.g., curious, empathetic)
  - Values (e.g., honesty, privacy)
  - Goals (e.g., help Tapan learn Python)
  - Style (e.g., Hinglish, concise)
  """

  def __init__(self, data_dir: Path):
    self.data_dir = Path(data_dir)
    self.db_path = self.data_dir / "persona.db"
    self._ensure_schema()

  def _ensure_schema(self):
    """Create persona tables"""
    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()

    cursor.execute("""
      CREATE TABLE IF NOT EXISTS traits (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        category TEXT DEFAULT 'personality'
      )
    """)

    # Seed default traits if empty
    cursor.execute("SELECT COUNT(*) FROM traits")
    if cursor.fetchone()[0] == 0:
      defaults = [
        ("name", "TapanAI", "identity"),
        ("role", "Digital Twin", "identity"),
        ("tone", "Friendly, Professional, Hinglish", "style"),
        ("core_value", "Privacy-first", "values"),
        ("hobby", "Helping Tapan coding", "traits")
      ]
      cursor.executemany("INSERT INTO traits (key, value, category) VALUES (?, ?, ?)", defaults)
      conn.commit()

    conn.commit()
    conn.close()

  @property
  def name(self) -> str:
    return "persona"

  @property
  def description(self) -> str:
    return "Access and modify your own persona/identity traits"

  @property
  def actions(self) -> list:
    return ["get", "set", "list", "delete"]

  def execute(self, action: str, params: Dict[str, Any]) -> ToolResult:
    conn = sqlite3.connect(self.db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
      if action == "get":
        key = params.get("key", "").lower()
        cursor.execute("SELECT value, category FROM traits WHERE lower(key) = ?", (key,))
        row = cursor.fetchone()
        if row:
          return ToolResult(success=True, message=f"{row['category'].title()}: {row['value']}")
        return ToolResult(success=True, message=f"I don't have a defined trait for '{key}'.")

      elif action == "set":
        key = params.get("key", "").lower()
        value = params.get("value", "")
        category = params.get("category", "personality")

        if not key or not value:
          return ToolResult(success=False, message="Key and Value required")

        cursor.execute(
          "INSERT OR REPLACE INTO traits (key, value, category) VALUES (?, ?, ?)",
          (key, value, category)
        )
        conn.commit()
        return ToolResult(success=True, message=f"✓ Updated my {key} to: {value}")

      elif action == "list":
        cursor.execute("SELECT key, value, category FROM traits ORDER BY category, key")
        rows = cursor.fetchall()
        if not rows:
          return ToolResult(success=True, message="Persona is blank.")

        lines = ["👤 My Persona:"]
        current_cat = None
        for row in rows:
          cat = row['category'].upper()
          if cat != current_cat:
            lines.append(f"\n[{cat}]")
            current_cat = cat
          lines.append(f"  {row['key']}: {row['value']}")

        return ToolResult(success=True, message="\n".join(lines))

      elif action == "delete":
        key = params.get("key", "").lower()
        cursor.execute("DELETE FROM traits WHERE lower(key) = ?", (key,))
        conn.commit()
        return ToolResult(success=True, message=f"Removed trait '{key}'")

      else:
        return ToolResult(success=False, message=f"Unknown action: {action}")

    except Exception as e:
      return ToolResult(success=False, message=f"Error: {e}")
    finally:
      conn.close()
