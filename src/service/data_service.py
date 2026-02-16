"""
Data Service - Exposes Finance, Memory, Journal, Reminders, Habits, Profile
"""
from pathlib import Path
from typing import Optional, Dict

# Lazy loaded managers
_finance = None
_memory = None
_journal = None
_reminders = None
_habits = None
_profile = None
_backup = None


def get_finance(data_dir: Optional[Path] = None):
  """Get finance manager"""
  global _finance
  if _finance is None:
    from src.core.finance import FinanceManager
    data_dir = data_dir or Path("data")
    db_path = data_dir / "finance.db"
    schema_path = data_dir / "finance_schema.sql"
    _finance = FinanceManager(db_path, schema_path)
  return _finance


def get_memory(data_dir: Optional[Path] = None):
  """Get memory manager"""
  global _memory
  if _memory is None:
    from src.core.memory import MemoryManager
    data_dir = data_dir or Path("data")
    db_path = data_dir / "memory.db"
    schema_path = data_dir / "memory_schema.sql"
    _memory = MemoryManager(db_path, schema_path)
  return _memory


def get_journal(data_dir: Optional[Path] = None):
  """Get journal manager"""
  global _journal
  if _journal is None:
    from src.core.journal import JournalManager
    data_dir = data_dir or Path("data")
    db_path = data_dir / "journal.db"
    schema_path = data_dir / "journal_schema.sql"
    _journal = JournalManager(db_path, schema_path)
  return _journal


def get_reminders(data_dir: Optional[Path] = None):
  """Get reminders manager"""
  global _reminders
  if _reminders is None:
    from src.core.reminders import ReminderManager
    data_dir = data_dir or Path("data")
    db_path = data_dir / "reminders.db"
    schema_path = data_dir / "reminders_schema.sql"
    _reminders = ReminderManager(db_path, schema_path)
  return _reminders


def get_habits(data_dir: Optional[Path] = None):
  """Get habits tracker"""
  global _habits
  if _habits is None:
    from src.core.habits import HabitTracker
    data_dir = data_dir or Path("data")
    db_path = data_dir / "habits.db"
    schema_path = data_dir / "habits_schema.sql"
    _habits = HabitTracker(db_path, schema_path)
  return _habits


def get_profile(data_dir: Optional[Path] = None):
  """Get profile manager"""
  global _profile
  if _profile is None:
    from src.core.profile import ProfileManager
    data_dir = data_dir or Path("data")
    db_path = data_dir / "profile.db"
    _profile = ProfileManager(db_path)
  return _profile


def get_backup(data_dir: Optional[Path] = None, backup_dir: Optional[Path] = None):
  """Get backup manager"""
  global _backup
  if _backup is None:
    from src.core.backup import BackupManager
    data_dir = data_dir or Path("data")
    backup_dir = backup_dir or Path("backup")
    _backup = BackupManager(data_dir, backup_dir)
  return _backup


def reset():
  """Reset all cached services"""
  global _finance, _memory, _journal, _reminders, _habits, _profile, _backup
  _finance = None
  _memory = None
  _journal = None
  _reminders = None
  _habits = None
  _profile = None
  _backup = None
