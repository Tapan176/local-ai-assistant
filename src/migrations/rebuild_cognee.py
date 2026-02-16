"""
Migration Script: Rebuild Cognee/Neo4j Graph from SQLite Source of Truth

This script:
1. Connects to the SQLite databases (memories, experiences, relations, etc.)
2. Clears the existing Neo4j graph (to remove potential hallucinations/drift)
3. Re-ingests all data from SQLite into Cognee using CogneeBrain
4. Rebuilds embeddings and vector indices

Usage:
  python -m src.migrations.rebuild_cognee
"""
import sys
import sqlite3
import asyncio
from pathlib import Path
from typing import List, Dict, Any

# Ensure src is in path
sys.path.append(str(Path(__file__).parent.parent.parent))

from src.memory.cognee_brain import CogneeBrain
from src.core.sync_manager import SyncManager

# Configuration
DATA_DIR = Path("data")

def get_sqlite_data(domain: str, table: str) -> List[Dict[str, Any]]:
  """Fetch all rows from a SQLite domain table"""
  db_path = DATA_DIR / f"{domain}.db"
  if not db_path.exists():
    print(f"[WARN] Database not found: {db_path}")
    return []

  conn = sqlite3.connect(db_path)
  conn.row_factory = sqlite3.Row
  try:
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM {table}")
    rows = [dict(row) for row in cursor.fetchall()]
    return rows
  except Exception as e:
    print(f"[ERROR] Failed to read {domain}.{table}: {e}")
    return []
  finally:
    conn.close()

async def rebuild_graph():
  print("🚀 Starting Cognee/Neo4j Rebuild...")

  # 1. Initialize Brain
  brain = CogneeBrain(DATA_DIR)

  # 2. Clear Neo4j
  if brain.neo4j_driver:
    print("🧹 Clearing Neo4j graph...")
    with brain.neo4j_driver.session() as session:
      session.run("MATCH (n) DETACH DELETE n")
    print("✓ Neo4j cleared")
  else:
    print("⚠️ Neo4j not available, skipping clear")

  # 3. Migration Plan
  # (domain, table, text_column)
  migration_map = [
    ("memory", "memories", "text"),
    ("experience", "experiences", "text"),
    ("relation", "relations", "notes"), # Relations often have notes/context
    ("habit", "habits", "name"),
    # Finance usually not fully graphed, but maybe high-value purchases?
    # Leaving finance out for now to avoid noise
  ]

  total_ingested = 0

  for domain, table, text_col in migration_map:
    print(f"\n📦 Migrating {domain}...")
    rows = get_sqlite_data(domain, table)
    print(f"   Found {len(rows)} records in SQLite")

    for row in rows:
      text = row.get(text_col)
      if not text:
        continue

      # Construct metadata from other columns
      metadata = {k: v for k, v in row.items() if k != text_col}
      source_id = row.get("id")

      # Special handling for Relations (Humanize text)
      if domain == "relation":
        name = row.get("name", "Unknown")
        rel = row.get("relationship", "associate")
        text = f"{name} is my {rel}. {text}"

      try:
        await brain.remember(text, domain, metadata, source_id)
        print(f"   ✓ Ingested: {text[:50]}...")
        total_ingested += 1
      except Exception as e:
        print(f"   ❌ Failed to ingest ID {source_id}: {e}")

  print(f"\n✨ Rebuild Complete! Ingested {total_ingested} nodes.")
  brain.close()

if __name__ == "__main__":
  asyncio.run(rebuild_graph())
