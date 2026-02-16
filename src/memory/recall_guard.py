"""
Phase 15 Recall Guard.

Strict rule:
If SQLite has no proof, return exactly: "No record in database."
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .cognee_brain import CogneeBrainSync, RecallResult


NO_RECORD_TEXT = "No record in database."


@dataclass
class GuardedResponse:
  text: str
  grounded: bool
  sources: List[str]
  confidence: float
  domain: str
  timestamp: str


class RecallGuard:
  """Verifies semantic recalls against SQLite source of truth."""

  HALLUCINATION_MARKERS = [
    "i think",
    "probably",
    "maybe",
    "might have",
    "i believe",
    "i assume",
    "likely",
    "it seems",
  ]

  _DOMAIN_META = {
    "memory": {"db": "memories.db", "table": "memories", "columns": ["text", "category", "tags"]},
    "experience": {"db": "experiences.db", "table": "experiences", "columns": ["text", "place", "people", "category"]},
    "relation": {"db": "relations.db", "table": "relations", "columns": ["name", "relationship", "notes"]},
    "habit": {"db": "habits.db", "table": "habits", "columns": ["name", "description"]},
    "finance": {"db": "finance.db", "table": "transactions", "columns": ["category", "note", "type", "account"]},
    "reminder": {"db": "reminders.db", "table": "reminders", "columns": ["text"]},
  }

  def __init__(self, cognee_brain: CogneeBrainSync):
    self.brain = cognee_brain
    base_path = Path(".")
    if hasattr(cognee_brain, "_brain") and hasattr(cognee_brain._brain, "data_dir"):
      base_path = Path(cognee_brain._brain.data_dir)
    self.data_dir = base_path

  def _normalize_domain(self, domain: Optional[str]) -> str:
    value = (domain or "").strip().lower()
    if value in ("memory", "memories"):
      return "memory"
    if value in ("experience", "experiences"):
      return "experience"
    if value in ("relation", "relations"):
      return "relation"
    if value in ("habit", "habits"):
      return "habit"
    if value in ("finance",):
      return "finance"
    if value in ("reminder", "reminders"):
      return "reminder"
    return value or "memory"

  def _sqlite_exists(self, domain: str, text: str) -> bool:
    meta = self._DOMAIN_META.get(domain)
    if not meta:
      return False
    db_path = self.data_dir / meta["db"]
    if not db_path.exists():
      return False
    snippet = self._snippet(text)
    if not snippet:
      return False

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    try:
      if not self._table_exists(cursor, str(meta["table"])):
        return False
      where = " OR ".join([f"{col} LIKE ?" for col in meta["columns"]])
      params = [f"%{snippet}%" for _ in meta["columns"]]
      cursor.execute(f"SELECT 1 FROM {meta['table']} WHERE {where} LIMIT 1", params)
      return cursor.fetchone() is not None
    except Exception:
      return False
    finally:
      conn.close()

  def _table_exists(self, cursor: sqlite3.Cursor, table_name: str) -> bool:
    cursor.execute(
      "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
      (table_name,),
    )
    return cursor.fetchone() is not None

  def _snippet(self, text: str) -> str:
    base = re.sub(r"\s+", " ", (text or "").strip())
    base = re.sub(r"[^a-zA-Z0-9\s]", " ", base)
    tokens = [tok for tok in base.split() if len(tok) >= 3]
    if not tokens:
      return ""
    return " ".join(tokens[:6])

  def _contains_hallucination(self, text: str) -> bool:
    text_lower = (text or "").lower()
    return any(marker in text_lower for marker in self.HALLUCINATION_MARKERS)

  def _strip_hallucination(self, text: str) -> str:
    result = text or ""
    for marker in self.HALLUCINATION_MARKERS:
      result = re.sub(
        rf"[^.!?\n]*\b{re.escape(marker)}\b[^.!?\n]*[.!?]?",
        "",
        result,
        flags=re.IGNORECASE,
      )
    result = re.sub(r"\s+", " ", result).strip()
    return result or NO_RECORD_TEXT

  def _build_no_record(self, domain: str) -> GuardedResponse:
    return GuardedResponse(
      text=NO_RECORD_TEXT,
      grounded=False,
      sources=[],
      confidence=0.0,
      domain=domain,
      timestamp=datetime.now().isoformat(),
    )

  def _format_verified(self, rows: List[RecallResult]) -> str:
    lines: List[str] = []
    for row in rows[:5]:
      clean_text = self._strip_hallucination(row.text)
      if clean_text == NO_RECORD_TEXT:
        continue
      lines.append(clean_text)
    return "\n".join(lines).strip() or NO_RECORD_TEXT

  def recall_with_guard(self, query: str, domain: Optional[str] = None) -> GuardedResponse:
    domain_norm = self._normalize_domain(domain)
    try:
      results = self.brain.recall(query, domain_norm)
    except Exception:
      results = []

    verified: List[RecallResult] = []
    for result in results:
      if self._sqlite_exists(domain_norm, result.text):
        verified.append(result)

    if not verified:
      return self._build_no_record(domain_norm)

    text = self._format_verified(verified)
    if text == NO_RECORD_TEXT:
      return self._build_no_record(domain_norm)

    return GuardedResponse(
      text=text,
      grounded=True,
      sources=[v.node_id for v in verified if v.node_id],
      confidence=max((v.confidence for v in verified), default=0.0),
      domain=domain_norm,
      timestamp=datetime.now().isoformat(),
    )

  def _exists_any_domain(self, text: str) -> bool:
    for domain in self._DOMAIN_META.keys():
      if self._sqlite_exists(domain, text):
        return True
    return False

  def multi_hop_with_guard(self, query: str) -> GuardedResponse:
    try:
      results = self.brain.multi_hop_query(query)
    except Exception:
      results = []
    if not results:
      return self._build_no_record("multi-hop")

    valid = [
      row
      for row in results
      if row.node_type != "NoResult" and self._exists_any_domain(row.text)
    ]
    if not valid:
      return self._build_no_record("multi-hop")

    text = self._format_verified(valid)
    if text == NO_RECORD_TEXT:
      return self._build_no_record("multi-hop")
    return GuardedResponse(
      text=text,
      grounded=True,
      sources=[row.node_id for row in valid if row.node_id],
      confidence=max((row.confidence for row in valid), default=0.0),
      domain="multi-hop",
      timestamp=datetime.now().isoformat(),
    )

  def recall_experience(self, query: str) -> GuardedResponse:
    return self.recall_with_guard(query, "experience")

  def recall_memory(self, query: str) -> GuardedResponse:
    return self.recall_with_guard(query, "memory")

  def recall_relation(self, name: str) -> GuardedResponse:
    return self.recall_with_guard(name, "relation")

  def recall_habit(self, query: str) -> GuardedResponse:
    return self.recall_with_guard(query, "habit")

  def recall_finance(self, query: str) -> GuardedResponse:
    return self.recall_with_guard(query, "finance")

  def validate_response(self, response: str, expected_sources: List[str]) -> bool:
    if self._contains_hallucination(response):
      return False
    if response.strip() == NO_RECORD_TEXT:
      return True
    if expected_sources:
      return any(source in response for source in expected_sources)
    return True

  def audit_response(self, response: GuardedResponse) -> Dict[str, Any]:
    return {
      "grounded": response.grounded,
      "has_sources": len(response.sources) > 0,
      "confidence": response.confidence,
      "hallucination_free": not self._contains_hallucination(response.text),
      "domain": response.domain,
      "source_count": len(response.sources),
      "timestamp": response.timestamp,
    }


class ResponseFormatter:
  """Simple plain-text formatters."""

  @staticmethod
  def format_experience(result: GuardedResponse) -> str:
    return result.text if result.grounded else NO_RECORD_TEXT

  @staticmethod
  def format_memory(result: GuardedResponse) -> str:
    return result.text if result.grounded else NO_RECORD_TEXT

  @staticmethod
  def format_relation(result: GuardedResponse) -> str:
    return result.text if result.grounded else NO_RECORD_TEXT

  @staticmethod
  def format_multi_hop(result: GuardedResponse) -> str:
    return result.text if result.grounded else NO_RECORD_TEXT
