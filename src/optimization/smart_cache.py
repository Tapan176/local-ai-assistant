"""
Smart Cache - SQLite-backed intelligent caching for expensive operations.

Phase 17: Cache LLM responses and expensive computations:
- In-memory LRU for fast path
- SQLite persistence for durability
- TTL-based expiration (24h default)
- No pickle (security risk) — JSON only
"""
import json
import hashlib
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from collections import OrderedDict


class SmartCache:
  """SQLite-backed intelligent caching."""

  def __init__(self, data_dir: Path, max_memory: int = 100,
               ttl_hours: int = 24):
    self.data_dir = Path(data_dir)
    self.db_path = self.data_dir / "cache.db"
    self.max_memory = max_memory
    self.ttl_hours = ttl_hours
    self._memory: OrderedDict = OrderedDict()
    self._init_db()

  def _init_db(self):
    """Initialize SQLite cache table."""
    try:
      conn = sqlite3.connect(self.db_path)
      conn.execute("""
        CREATE TABLE IF NOT EXISTS cache (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL,
          metadata TEXT,
          created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
          expires_at DATETIME
        )
      """)
      conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_cache_expires ON cache(expires_at)
      """)
      conn.commit()
      conn.close()
    except Exception:
      pass

  def _hash_key(self, *parts: str) -> str:
    """Generate hash key from input parts."""
    combined = "|".join(str(p) for p in parts)
    return hashlib.sha256(combined.encode()).hexdigest()[:24]

  # ── LLM Response Cache ──────────────────────────────────────

  def cache_llm_response(self, prompt: str, context: str,
                         response: str):
    """Cache an LLM response for identical prompts."""
    key = self._hash_key(prompt, context)
    self._put(key, response, metadata={"type": "llm", "prompt_len": len(prompt)})

  def get_llm_response(self, prompt: str, context: str) -> Optional[str]:
    """Get cached LLM response if available and fresh."""
    key = self._hash_key(prompt, context)
    return self._get(key)

  # ── Generic Cache ───────────────────────────────────────────

  def put(self, namespace: str, key: str, value: Any,
          ttl_hours: int = None):
    """Cache any JSON-serializable value."""
    full_key = self._hash_key(namespace, key)
    value_str = json.dumps(value, default=str)
    self._put(full_key, value_str, ttl_hours=ttl_hours)

  def get(self, namespace: str, key: str) -> Optional[Any]:
    """Get cached value."""
    full_key = self._hash_key(namespace, key)
    raw = self._get(full_key)
    if raw is None:
      return None
    try:
      return json.loads(raw)
    except json.JSONDecodeError:
      return raw

  # ── Internal ────────────────────────────────────────────────

  def _put(self, key: str, value: str, metadata: Dict = None,
           ttl_hours: int = None):
    """Store in both memory and SQLite."""
    ttl = ttl_hours or self.ttl_hours

    # Memory cache
    self._memory[key] = value
    if len(self._memory) > self.max_memory:
      self._memory.popitem(last=False)  # Remove oldest

    # SQLite cache
    try:
      expires_at = (datetime.now() + timedelta(hours=ttl)).isoformat()
      meta_str = json.dumps(metadata, default=str) if metadata else None
      conn = sqlite3.connect(self.db_path)
      conn.execute("""
        INSERT OR REPLACE INTO cache (key, value, metadata, created_at, expires_at)
        VALUES (?, ?, ?, ?, ?)
      """, (key, value, meta_str, datetime.now().isoformat(), expires_at))
      conn.commit()
      conn.close()
    except Exception:
      pass

  def _get(self, key: str) -> Optional[str]:
    """Retrieve from memory or SQLite."""
    # Memory first
    if key in self._memory:
      return self._memory[key]

    # SQLite fallback
    try:
      conn = sqlite3.connect(self.db_path)
      cursor = conn.execute(
        "SELECT value, expires_at FROM cache WHERE key = ?", (key,)
      )
      row = cursor.fetchone()
      conn.close()

      if row:
        value, expires_at = row
        # Check expiration
        if expires_at:
          exp_time = datetime.fromisoformat(expires_at)
          if datetime.now() > exp_time:
            self._delete(key)
            return None

        # Promote to memory cache
        self._memory[key] = value
        return value
    except Exception:
      pass

    return None

  def _delete(self, key: str):
    """Delete from both caches."""
    self._memory.pop(key, None)
    try:
      conn = sqlite3.connect(self.db_path)
      conn.execute("DELETE FROM cache WHERE key = ?", (key,))
      conn.commit()
      conn.close()
    except Exception:
      pass

  def cleanup_expired(self) -> int:
    """Remove expired entries. Returns count removed."""
    try:
      now = datetime.now().isoformat()
      conn = sqlite3.connect(self.db_path)
      cursor = conn.execute(
        "DELETE FROM cache WHERE expires_at IS NOT NULL AND expires_at < ?",
        (now,)
      )
      removed = cursor.rowcount
      conn.commit()
      conn.close()
      return removed
    except Exception:
      return 0

  def get_stats(self) -> Dict:
    """Get cache statistics."""
    memory_count = len(self._memory)
    disk_count = 0

    try:
      conn = sqlite3.connect(self.db_path)
      cursor = conn.execute("SELECT COUNT(*) FROM cache")
      disk_count = cursor.fetchone()[0]
      conn.close()
    except Exception:
      pass

    return {
      "memory_items": memory_count,
      "disk_items": disk_count,
      "max_memory": self.max_memory,
      "ttl_hours": self.ttl_hours,
    }

  def clear(self):
    """Clear all caches."""
    self._memory.clear()
    try:
      conn = sqlite3.connect(self.db_path)
      conn.execute("DELETE FROM cache")
      conn.commit()
      conn.close()
    except Exception:
      pass


def get_smart_cache(data_dir: Path = None) -> SmartCache:
  """Factory for SmartCache."""
  if data_dir is None:
    data_dir = Path("data")
  return SmartCache(data_dir)
