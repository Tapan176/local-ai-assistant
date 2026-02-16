"""
PHASE 15: Ingestion Pipeline

Migrates data from SQLite to Cognee + Neo4j.

Flow:
1. Read from SQLite (source of truth)
2. Transform to MemoryNode
3. Ingest to Cognee (async)
4. Create Neo4j nodes + relationships
5. Verify ingestion

Domains:
- memories → Preference nodes
- experiences → Experience nodes (episodic)
- relations → Person nodes + graph
- habits → Habit nodes
- finance → Purchase nodes (structured ontology)
"""
import sqlite3
import json
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from .cognee_brain import CogneeBrain, CogneeBrainSync, MemoryNode


@dataclass
class MigrationResult:
  """Result of migration operation"""
  domain: str
  total_records: int
  migrated: int
  failed: int
  errors: List[str]


class IngestionPipeline:
  """
  SQLite → Cognee + Neo4j migration pipeline.

  Principles:
  1. SQLite remains source of truth
  2. Cognee is async ingestion
  3. Neo4j gets structured graph
  4. Provenance tracked via source_id
  """

  # SQLite → Cognee domain mapping
  DOMAIN_MAP = {
    "memories.db": {
      "table": "memories",
      "domain": "memory",
      "node_type": "Preference",
      "text_col": "text",
      "id_col": "id",
    },
    "experiences.db": {
      "table": "experiences",
      "domain": "experience",
      "node_type": "Experience",
      "text_col": "text",
      "id_col": "id",
    },
    "relations.db": {
      "table": "relations",
      "domain": "relation",
      "node_type": "Person",
      "text_col": "name",
      "id_col": "id",
    },
    "habits.db": {
      "table": "habits",
      "domain": "habit",
      "node_type": "Habit",
      "text_col": "name",
      "id_col": "id",
    },
    "finance.db": {
      "table": "transactions",
      "domain": "finance",
      "node_type": "Purchase",
      "text_col": "note",
      "id_col": "id",
    },
  }

  def __init__(self, data_dir: Path, cognee_brain: Optional[CogneeBrainSync] = None):
    self.data_dir = Path(data_dir)
    self.brain = cognee_brain or CogneeBrainSync(data_dir)
    self.migration_log: List[MigrationResult] = []

  def migrate_all(self) -> Dict[str, MigrationResult]:
    """Migrate all domains from SQLite to Cognee"""
    results = {}

    for db_name, config in self.DOMAIN_MAP.items():
      db_path = self.data_dir / db_name
      if db_path.exists():
        result = self.migrate_domain(db_path, config)
        results[config["domain"]] = result
        self.migration_log.append(result)
      else:
        results[config["domain"]] = MigrationResult(
          domain=config["domain"],
          total_records=0,
          migrated=0,
          failed=0,
          errors=[f"Database not found: {db_name}"]
        )

    # Create relationships after all nodes exist
    self._create_relationships()

    return results

  def migrate_domain(self, db_path: Path, config: Dict) -> MigrationResult:
    """Migrate a single domain"""
    domain = config["domain"]
    table = config["table"]
    text_col = config["text_col"]
    id_col = config["id_col"]

    migrated = 0
    failed = 0
    errors = []

    try:
      conn = sqlite3.connect(db_path)
      conn.row_factory = sqlite3.Row
      cursor = conn.cursor()

      # Get all records
      cursor.execute(f"SELECT * FROM {table}")
      rows = cursor.fetchall()
      total = len(rows)

      for row in rows:
        try:
          # Build text from row
          text = self._build_text(dict(row), text_col, domain)

          # Build metadata
          metadata = self._build_metadata(dict(row), domain)

          # Ingest to Cognee
          self.brain.remember(
            text=text,
            domain=domain,
            metadata=metadata,
            source_id=row[id_col]
          )
          migrated += 1

        except Exception as e:
          failed += 1
          errors.append(f"Row {row[id_col]}: {str(e)}")

      conn.close()

    except Exception as e:
      errors.append(f"Database error: {str(e)}")
      total = 0

    return MigrationResult(
      domain=domain,
      total_records=total,
      migrated=migrated,
      failed=failed,
      errors=errors[:10]  # Limit error list
    )

  def _build_text(self, row: Dict, text_col: str, domain: str) -> str:
    """Build searchable text from row"""
    if domain == "experience":
      # Rich experience text
      parts = [row.get("text", "")]
      if row.get("place"):
        parts.append(f"at {row['place']}")
      if row.get("city"):
        parts.append(f"in {row['city']}")
      if row.get("people"):
        parts.append(f"with {row['people']}")
      if row.get("amount"):
        parts.append(f"spent ₹{row['amount']}")
      if row.get("date"):
        parts.append(f"on {row['date']}")
      return " ".join(parts)

    elif domain == "relation":
      # Person description
      parts = [row.get("name", "")]
      if row.get("relationship"):
        parts.append(f"({row['relationship']})")
      if row.get("notes"):
        parts.append(f"- {row['notes']}")
      return " ".join(parts)

    elif domain == "habit":
      # Habit description
      parts = [row.get("name", "")]
      if row.get("frequency"):
        parts.append(f"({row['frequency']})")
      if row.get("streak_current"):
        parts.append(f"streak: {row['streak_current']}")
      return " ".join(parts)

    elif domain == "finance":
      # Transaction description
      parts = []
      if row.get("type"):
        parts.append(row["type"])
      if row.get("amount"):
        parts.append(f"₹{row['amount']}")
      if row.get("category"):
        parts.append(f"for {row['category']}")
      if row.get("note"):
        parts.append(f"- {row['note']}")
      return " ".join(parts) or "transaction"

    else:
      # Default: use text column
      return row.get(text_col, "")

  def _build_metadata(self, row: Dict, domain: str) -> Dict:
    """Build metadata from row"""
    # Remove None values and convert to JSON-safe types
    metadata = {}
    for key, value in row.items():
      if value is not None:
        if isinstance(value, (int, float, str, bool)):
          metadata[key] = value
        else:
          metadata[key] = str(value)
    return metadata

  def _create_relationships(self):
    """Create Neo4j relationships between nodes"""
    # This requires Neo4j to be connected
    if not self.brain._brain.neo4j_driver:
      return

    # Read experiences and create relationships
    exp_db = self.data_dir / "experiences.db"
    if exp_db.exists():
      self._create_experience_relationships(exp_db)

    # Read relations and create person graph
    rel_db = self.data_dir / "relations.db"
    if rel_db.exists():
      self._create_relation_relationships(rel_db)

  def _create_experience_relationships(self, db_path: Path):
    """Create relationships from experiences"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM experiences")
    for row in cursor.fetchall():
      exp_id = f"experience_{row['id']}"

      # DID_WITH relationship (person)
      if row["people"]:
        for person in row["people"].split(","):
          person = person.strip()
          if person:
            # Find or create person node
            person_id = f"person_{person.lower()}"
            self.brain._brain.create_relationship(
              exp_id, person_id, "DID_WITH",
              {"date": row["date"]}
            )

      # SPENT_AT relationship (place)
      if row["place"]:
        place_id = f"place_{row['place'].lower()}"
        self.brain._brain.create_relationship(
          exp_id, place_id, "SPENT_AT",
          {"amount": row["amount"], "date": row["date"]}
        )

    conn.close()

  def _create_relation_relationships(self, db_path: Path):
    """Create person graph relationships"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Get interactions
    try:
      cursor.execute("""
        SELECT r.name, i.interaction_date, i.type, i.summary
        FROM relations r
        JOIN interactions i ON r.id = i.person_id
      """)
      for row in cursor.fetchall():
        person_id = f"person_{row['name'].lower()}"
        interaction_id = f"interaction_{row['interaction_date']}_{row['name'].lower()}"

        self.brain._brain.create_relationship(
          person_id, interaction_id, "HAD_INTERACTION",
          {"date": row["interaction_date"], "type": row["type"]}
        )
    except sqlite3.OperationalError:
      pass  # No interactions table

    conn.close()

  def get_migration_report(self) -> str:
    """Generate migration report"""
    lines = ["# Migration Report", ""]

    total_records = 0
    total_migrated = 0
    total_failed = 0

    for result in self.migration_log:
      lines.append(f"## {result.domain.upper()}")
      lines.append(f"- Total: {result.total_records}")
      lines.append(f"- Migrated: {result.migrated}")
      lines.append(f"- Failed: {result.failed}")
      if result.errors:
        lines.append(f"- Errors: {', '.join(result.errors[:3])}")
      lines.append("")

      total_records += result.total_records
      total_migrated += result.migrated
      total_failed += result.failed

    lines.append("## SUMMARY")
    lines.append(f"- Total Records: {total_records}")
    lines.append(f"- Total Migrated: {total_migrated}")
    lines.append(f"- Total Failed: {total_failed}")
    lines.append(f"- Success Rate: {(total_migrated/total_records*100) if total_records else 0:.1f}%")

    return "\n".join(lines)


class IncrementalIngestion:
  """
  Incremental ingestion for real-time updates.

  Called after each SQLite write to sync to Cognee.
  """

  def __init__(self, cognee_brain: CogneeBrainSync):
    self.brain = cognee_brain

  def ingest_memory(self, text: str, category: str, source_id: int) -> MemoryNode:
    """Ingest a new memory"""
    return self.brain.remember(
      text=text,
      domain="memory",
      metadata={"category": category},
      source_id=source_id
    )

  def ingest_experience(self, text: str, date: str, place: str = None,
             people: str = None, amount: float = None,
             source_id: int = None) -> MemoryNode:
    """Ingest a new experience"""
    metadata = {"date": date}
    if place:
      metadata["place"] = place
    if people:
      metadata["people"] = people
    if amount:
      metadata["amount"] = amount

    return self.brain.remember(
      text=text,
      domain="experience",
      metadata=metadata,
      source_id=source_id
    )

  def ingest_relation(self, name: str, relationship: str,
             notes: str = None, source_id: int = None) -> MemoryNode:
    """Ingest a new relation"""
    text = f"{name} ({relationship})"
    if notes:
      text += f" - {notes}"

    return self.brain.remember(
      text=text,
      domain="relation",
      metadata={"name": name, "relationship": relationship},
      source_id=source_id
    )

  def ingest_habit(self, name: str, frequency: str = "daily",
          source_id: int = None) -> MemoryNode:
    """Ingest a new habit"""
    return self.brain.remember(
      text=f"{name} ({frequency})",
      domain="habit",
      metadata={"name": name, "frequency": frequency},
      source_id=source_id
    )

  def ingest_transaction(self, amount: float, type: str, category: str,
              note: str = None, source_id: int = None) -> MemoryNode:
    """Ingest a new transaction"""
    text = f"{type} ₹{amount} for {category}"
    if note:
      text += f" - {note}"

    return self.brain.remember(
      text=text,
      domain="finance",
      metadata={"amount": amount, "type": type, "category": category},
      source_id=source_id
    )
