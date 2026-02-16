"""
SyncManager - Deprecated (Stub)
Replaced by src.db.base_repository.BaseRepository
"""
from pathlib import Path

class SyncManager:
  def __init__(self, data_dir: Path):
    self.data_dir = Path(data_dir)
    # No-op

  def get_connection(self, db_name: str):
    raise DeprecationWarning("SyncManager is deprecated. Use BaseRepository.")
