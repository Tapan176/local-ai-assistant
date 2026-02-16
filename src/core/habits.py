"""
Habit Tracker - Track and manage daily habits
"""
import sqlite3
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional


class HabitTracker:
  """Manage habits and track completion"""

  def __init__(self, db_path, schema_path=None):
    self.db_path = Path(db_path)
    self.schema_path = Path(schema_path) if schema_path else None
    self._init_db()

  def _init_db(self):
    """Initialize database with schema"""
    if self.schema_path and self.schema_path.exists():
      with open(self.schema_path, 'r', encoding='utf-8') as f:
        schema = f.read()
      conn = sqlite3.connect(self.db_path)
      cursor = conn.cursor()
      cursor.executescript(schema)
      conn.commit()
      conn.close()

  def add_habit(self, name: str, description: str = "", frequency: str = "daily") -> str:
    """Add a new habit to track

    Args:
      name: Habit name
      description: Optional description
      frequency: 'daily' or 'weekly'

    Returns:
      Success message
    """
    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()

    try:
      cursor.execute(
        "INSERT INTO habits (name, description, frequency) VALUES (?, ?, ?)",
        (name.lower(), description, frequency)
      )
      conn.commit()
      conn.close()
      return f"✓ Habit '{name}' added! Track it with: habit done {name}"
    except sqlite3.IntegrityError:
      conn.close()
      return f"❌ Habit '{name}' already exists"

  def mark_done(self, name: str, note: str = "") -> str:
    """Mark a habit as done for today

    Args:
      name: Habit name
      note: Optional note

    Returns:
      Success message with streak info
    """
    name = name.lower()
    today = date.today()

    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()

    # Check if habit exists
    cursor.execute("SELECT id FROM habits WHERE name = ?", (name,))
    result = cursor.fetchone()

    if not result:
      conn.close()
      return f"❌ Habit '{name}' not found. Add it with: habit add {name}"

    habit_id = result[0]

    # Check if already logged today
    cursor.execute(
      "SELECT id FROM habit_logs WHERE habit_id = ? AND log_date = ?",
      (habit_id, today)
    )
    if cursor.fetchone():
      conn.close()
      return f"✓ Already marked '{name}' as done today!"

    # Log the completion
    cursor.execute(
      "INSERT INTO habit_logs (habit_id, name, log_date, note) VALUES (?, ?, ?, ?)",
      (habit_id, name, today, note)
    )
    conn.commit()

    # Calculate streak
    streak = self._calculate_streak(cursor, habit_id)

    conn.close()

    emoji = "🔥" if streak >= 3 else "✓"
    streak_msg = f" (streak: {streak} days!)" if streak > 1 else ""

    return f"{emoji} Habit '{name}' marked done{streak_msg}"

  def _calculate_streak(self, cursor, habit_id: int) -> int:
    """Calculate current streak for a habit"""
    cursor.execute(
      """SELECT log_date FROM habit_logs
         WHERE habit_id = ?
         ORDER BY log_date DESC""",
      (habit_id,)
    )
    logs = cursor.fetchall()

    if not logs:
      return 0

    streak = 1
    prev_date = datetime.strptime(logs[0][0], '%Y-%m-%d').date()

    for i in range(1, len(logs)):
      log_date = datetime.strptime(logs[i][0], '%Y-%m-%d').date()
      if (prev_date - log_date).days == 1:
        streak += 1
        prev_date = log_date
      else:
        break

    return streak

  def list_habits(self) -> str:
    """List all habits with today's status

    Returns:
      Formatted list of habits
    """
    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT id, name, description, frequency FROM habits ORDER BY name")
    habits = cursor.fetchall()

    if not habits:
      conn.close()
      return "\n📋 No habits tracked yet\n  Add one with: habit add <name>\n"

    today = date.today()
    output = "\n📋 HABITS\n"
    output += "-" * 50 + "\n"

    for habit_id, name, description, frequency in habits:
      # Check if done today
      cursor.execute(
        "SELECT id FROM habit_logs WHERE habit_id = ? AND log_date = ?",
        (habit_id, today)
      )
      done_today = cursor.fetchone() is not None

      # Get streak
      streak = self._calculate_streak(cursor, habit_id)

      # Format output
      status = "✅" if done_today else "⬜"
      streak_str = f" 🔥{streak}" if streak >= 3 else ""

      output += f"{status} {name}{streak_str}"
      if description:
        output += f" - {description}"
      output += f" ({frequency})\n"

    conn.close()

    output += "\nCommands:\n"
    output += "  habit done <name>  - Mark as complete\n"
    output += "  habit add <name>   - Add new habit\n"

    return output

  def get_weekly_summary(self) -> str:
    """Get weekly habit summary

    Returns:
      Formatted weekly summary
    """
    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()

    # Get all habits
    cursor.execute("SELECT id, name FROM habits")
    habits = cursor.fetchall()

    if not habits:
      conn.close()
      return "\nNo habits to summarize\n"

    # Calculate week range
    today = date.today()
    week_start = today - timedelta(days=6)

    output = "\n📊 WEEKLY HABIT SUMMARY\n"
    output += f"   {week_start} to {today}\n"
    output += "-" * 50 + "\n"

    for habit_id, name in habits:
      cursor.execute(
        """SELECT log_date FROM habit_logs
           WHERE habit_id = ?
           AND log_date >= ?
           AND log_date <= ?""",
        (habit_id, week_start, today)
      )
      logs = {row[0] for row in cursor.fetchall()}

      # Build weekly view
      days = []
      for i in range(7):
        day = week_start + timedelta(days=i)
        day_str = day.strftime('%Y-%m-%d')
        days.append("✅" if day_str in logs else "⬜")

      completion = len(logs)
      pct = completion / 7 * 100

      output += f"{name}:\n"
      output += f"  {' '.join(days)}\n"
      output += f"  Completed: {completion}/7 ({pct:.0f}%)\n\n"

    conn.close()
    return output

  def remove_habit(self, name: str) -> str:
    """Remove a habit

    Args:
      name: Habit name to remove

    Returns:
      Success message
    """
    name = name.lower()

    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM habits WHERE name = ?", (name,))
    result = cursor.fetchone()

    if not result:
      conn.close()
      return f"❌ Habit '{name}' not found"

    habit_id = result[0]

    # Delete logs first
    cursor.execute("DELETE FROM habit_logs WHERE habit_id = ?", (habit_id,))
    # Delete habit
    cursor.execute("DELETE FROM habits WHERE id = ?", (habit_id,))

    conn.commit()
    conn.close()

    return f"✓ Habit '{name}' removed"

  def get_today_pending(self) -> List[str]:
    """Get habits not yet done today

    Returns:
      List of pending habit names
    """
    today = date.today()

    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()

    cursor.execute(
      """SELECT h.name FROM habits h
         WHERE h.id NOT IN (
           SELECT habit_id FROM habit_logs WHERE log_date = ?
         )""",
      (today,)
    )
    pending = [row[0] for row in cursor.fetchall()]
    conn.close()

    return pending
