"""
Profile Manager - Stores user preferences and personal alignment settings
"""
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, List, Tuple


class ProfileManager:
  """Manages user preferences, priorities, and personal settings"""

  # Default profile values
  DEFAULTS = {
    'risk_level': ('moderate', 'finance'),
    'daily_routine': ('balanced', 'lifestyle'),
    'wake_time': ('07:00', 'routine'),
    'sleep_time': ('23:00', 'routine'),
    'work_start': ('09:00', 'routine'),
    'work_end': ('18:00', 'routine'),
    'language_preference': ('hinglish', 'general'),
    'currency': ('INR', 'finance'),
    'savings_goal': ('20', 'finance'),  # % of income
    'priority_1': ('health', 'priorities'),
    'priority_2': ('work', 'priorities'),
    'priority_3': ('family', 'priorities'),
  }

  def __init__(self, db_path: Path, schema_path: Path = None):
    self.db_path = Path(db_path)
    self.schema_path = schema_path
    self._init_db()

  def _init_db(self):
    """Initialize database with schema"""
    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()

    # Create profile table
    cursor.execute("""
      CREATE TABLE IF NOT EXISTS profile (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        category TEXT DEFAULT 'general',
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
      )
    """)

    # Insert defaults if not exist
    for key, (value, category) in self.DEFAULTS.items():
      cursor.execute("""
        INSERT OR IGNORE INTO profile (key, value, category)
        VALUES (?, ?, ?)
      """, (key, value, category))

    conn.commit()
    conn.close()

  def get(self, key: str, default: str = None) -> Optional[str]:
    """Get a profile value"""
    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT value FROM profile WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()

    if row:
      return row[0]
    return default

  def set(self, key: str, value: str, category: str = 'general') -> str:
    """Set a profile value"""
    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()

    cursor.execute("""
      INSERT OR REPLACE INTO profile (key, value, category, updated_at)
      VALUES (?, ?, ?, ?)
    """, (key, value, category, datetime.now().isoformat()))

    conn.commit()
    conn.close()

    return f"✓ Set {key} = {value}"

  def get_all(self) -> Dict[str, str]:
    """Get all profile values as dict"""
    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT key, value FROM profile ORDER BY key")
    rows = cursor.fetchall()
    conn.close()

    return {row[0]: row[1] for row in rows}

  def get_by_category(self, category: str) -> Dict[str, str]:
    """Get profile values by category"""
    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()

    cursor.execute(
      "SELECT key, value FROM profile WHERE category = ?",
      (category,)
    )
    rows = cursor.fetchall()
    conn.close()

    return {row[0]: row[1] for row in rows}

  def get_risk_level(self) -> str:
    """Get financial risk preference"""
    return self.get('risk_level', 'moderate')

  def set_risk_level(self, level: str) -> str:
    """Set financial risk preference"""
    valid_levels = ['conservative', 'moderate', 'aggressive']
    level = level.lower()

    if level not in valid_levels:
      return f"❌ Invalid risk level. Choose from: {', '.join(valid_levels)}"

    return self.set('risk_level', level, 'finance')

  def get_priorities(self) -> List[str]:
    """Get user priorities in order"""
    priorities = []
    for i in range(1, 6):
      p = self.get(f'priority_{i}')
      if p:
        priorities.append(p)
    return priorities

  def set_priority(self, rank: int, value: str) -> str:
    """Set a priority at given rank (1-5)"""
    if rank < 1 or rank > 5:
      return "❌ Priority rank must be 1-5"
    return self.set(f'priority_{rank}', value, 'priorities')

  def get_routine(self) -> Dict[str, str]:
    """Get daily routine settings"""
    return self.get_by_category('routine')

  def show_profile(self) -> str:
    """Display formatted profile"""
    output = "\n" + "=" * 50 + "\n"
    output += "   👤 YOUR PROFILE\n"
    output += "=" * 50 + "\n\n"

    # Group by category
    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()

    cursor.execute("""
      SELECT category, key, value 
      FROM profile 
      ORDER BY category, key
    """)
    rows = cursor.fetchall()
    conn.close()

    current_category = None
    for category, key, value in rows:
      if category != current_category:
        if current_category:
          output += "\n"
        output += f"📁 {category.upper()}\n"
        current_category = category

      # Format key nicely
      display_key = key.replace('_', ' ').title()
      output += f"   {display_key}: {value}\n"

    output += "\n" + "-" * 50 + "\n"
    output += "💡 Use 'profile set <key> <value>' to update\n"
    output += "   Example: profile set risk_level conservative\n"

    return output

  def get_profile_for_reasoning(self) -> Dict:
    """Get profile dict for reasoning engine"""
    return {
      'risk_level': self.get_risk_level(),
      'daily_routine': self.get('daily_routine', 'balanced'),
      'priorities': self.get_priorities(),
      'wake_time': self.get('wake_time', '07:00'),
      'sleep_time': self.get('sleep_time', '23:00'),
      'savings_goal': int(self.get('savings_goal', '20')),
    }


def get_profile_manager(data_dir: Path = None) -> ProfileManager:
  """Factory function for profile manager"""
  if data_dir is None:
    data_dir = Path(__file__).parent.parent / "data"

  db_path = data_dir / "profile.db"
  schema_path = data_dir / "profile_schema.sql"

  return ProfileManager(db_path, schema_path)
