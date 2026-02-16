"""
RecallGuard - Anti-Hallucination Gate.

Ensures that any semantic path (Cognee) is grounded in actual SQLite records.
If SQLite cannot prove existence, the memory is rejected.
"""
from typing import Dict, Any, Optional, List
from pathlib import Path
import sqlite3
import re

class RecallGuard:
  """
  Verifies semantic search results against SQLite Source of Truth.
  """

  def __init__(self, data_dir: Path):
    self.data_dir = Path(data_dir)
    self.db_map = {
      "memory": "memories",
      "experience": "experiences",
      "relation": "relations",
      "habit": "habits",
      "reminder": "reminders",
      "finance": "finance"
    }
    self.table_map = {
      "memory": "memories",
      "experience": "experiences",
      "relation": "relations",
      "habit": "habits",
      "reminder": "reminders",
      "finance": "transactions" # check this mapping
    }

  def _get_connection(self, domain: str) -> sqlite3.Connection:
    db_name = self.db_map.get(domain, domain)
    db_path = self.data_dir / f"{db_name}.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

  def verify_result(self, text: str, domain: str, source_id: Optional[int] = None) -> str:
    """
    Verify if a semantic result exists in SQLite.

    Args:
      text: The text returned by semantic search
      domain: The domain of the data
      source_id: The claimed SQLite ID (if available from graph)

    Returns:
      The verified text OR "No record in database."
    """
    # 1. If we have a source_id, check it directly (Strongest Proof)
    if source_id:
      conn = self._get_connection(domain)
      cursor = conn.cursor()
      table = self.table_map.get(domain, domain + "s")

      try:
        # Handle finance table naming
        if domain == 'finance' and table == 'finance' and not self._table_exists(cursor, 'finance'):
           # Finance DB structure might be different (accounts, transactions)
           # For now, let's assume generic check or skip finance strict ID check if ambiguous
           pass
        else:
          cursor.execute(f"SELECT id FROM {table} WHERE id = ?", (source_id,))
          if cursor.fetchone():
            return text # Verified!
      except Exception:
        pass
      finally:
        conn.close()

    # 2. If no ID, fuzzy match text in SQLite (Weaker Proof, but necessary if graph lacks ID)
    # This prevents "Ghost" nodes that were deleted in SQLite but persist in Graph
    conn = self._get_connection(domain)
    cursor = conn.cursor()
    table = self.table_map.get(domain, domain + "s")

    # Map domain to text column
    col_map = {
      "memory": "text",
      "experience": "text",
      "reminder": "text",
      "relation": "notes", # Relations defined by notes/context
      "habit": "name",
      "finance": "note"
    }
    text_col = col_map.get(domain, "text")

    try:
      # Check if column exists first (to avoid crashes on mismatched schemas)
      # cursor.execute(f"PRAGMA table_info({table})") ... skipped for speed, assume schema is standard

      # STRICT MODE: If we can't find it by ID or exact-ish text, reject.
      # Let's try to match a snippet.
      snippet = text[:50] # First 50 chars

      # Special handling for Relations: check name OR notes
      if domain == "relation":
         cursor.execute(f"SELECT id FROM {table} WHERE notes LIKE ? OR name LIKE ?", (f"%{snippet}%", f"%{snippet}%"))
      else:
         cursor.execute(f"SELECT id FROM {table} WHERE {text_col} LIKE ?", (f"%{snippet}%",))

      if cursor.fetchone():
        return text

    except Exception as e:
      # print(f"[GUARD] Verification failed: {e}") # Silent fail to avoid log spam
      pass
    finally:
      conn.close()

    # 3. FAILURE
    return "No record in database."

  def _table_exists(self, cursor, table_name):
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
    return cursor.fetchone() is not None

  def check_hallucination_markers(self, text: str) -> bool:
    """Check for forbidden phrases"""
    forbidden = [
      "I think", "probably", "might have", "maybe", 
      "I assume", "likely", "it seems"
    ]
    text_lower = text.lower()
    for phrase in forbidden:
      if phrase in text_lower:
        return True
    return False
