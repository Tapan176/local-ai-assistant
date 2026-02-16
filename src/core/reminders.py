"""
Reminder Manager - Offline reminders and tasks
"""
import sqlite3
import re
from pathlib import Path
from datetime import datetime, timedelta


class ReminderManager:
  """Manage reminders and tasks"""

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

  def _parse_datetime(self, date_str):
    """Parse date/time string to datetime object

    Supports formats:
    - "tomorrow" -> tomorrow at current time
    - "2026-02-10" -> specific date
    - "2026-02-10 15:30" -> specific date and time
    - "in 2 hours" -> 2 hours from now
    - "in 3 days" -> 3 days from now
    """
    date_str = date_str.strip().lower()
    now = datetime.now()

    # Handle "tomorrow"
    if date_str == "tomorrow":
      return now + timedelta(days=1)

    # Handle "in X hours/days"
    match = re.match(r'in (\d+) (hour|hours|day|days)', date_str)
    if match:
      amount = int(match.group(1))
      unit = match.group(2)
      if 'hour' in unit:
        return now + timedelta(hours=amount)
      else:
        return now + timedelta(days=amount)

    # Try parsing as ISO date/datetime
    try:
      if ' ' in date_str:
        # Has time component
        return datetime.strptime(date_str, '%Y-%m-%d %H:%M')
      else:
        # Only date
        return datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
      return None

  def add_reminder(self, text, remind_at_str, recurring=None):
    """Add a reminder

    Args:
      text: Reminder text
      remind_at_str: When to remind (string)
      recurring: Recurring pattern (None, 'daily', 'weekly', 'monthly')

    Returns:
      Success message or error
    """
    remind_at = self._parse_datetime(remind_at_str)

    if remind_at is None:
      return f"❌ Error: Could not parse date '{remind_at_str}'"

    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()
    cursor.execute(
      """INSERT INTO reminders (text, remind_at, recurring, status)
         VALUES (?, ?, ?, 'pending')""",
      (text, remind_at, recurring)
    )
    reminder_id = cursor.lastrowid
    conn.commit()
    conn.close()

    recurring_info = f" (recurring: {recurring})" if recurring else ""
    return f"✓ Reminder set for {remind_at.strftime('%Y-%m-%d %H:%M')}{recurring_info}"

  def list_reminders(self, status='pending', include_past=False):
    """List reminders

    Args:
      status: Filter by status ('pending', 'done', 'all')
      include_past: Include past reminders

    Returns:
      Formatted list of reminders
    """
    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()

    query = "SELECT id, text, remind_at, recurring, status FROM reminders WHERE 1=1"
    params = []

    if status != 'all':
      query += " AND status = ?"
      params.append(status)

    if not include_past:
      query += " AND remind_at >= datetime('now')"

    query += " ORDER BY remind_at ASC"

    cursor.execute(query, params)
    reminders = cursor.fetchall()
    conn.close()

    if not reminders:
      return "\n⏰ No reminders found\n"

    output = f"\n⏰ Reminders ({len(reminders)}):\n\n"

    now = datetime.now()
    for reminder_id, text, remind_at, recurring, status in reminders:
      remind_dt = datetime.strptime(remind_at, '%Y-%m-%d %H:%M:%S')

      # Status indicator
      if status == 'done':
        indicator = "✓"
      elif remind_dt < now:
        indicator = "🔴"  # Overdue
      else:
        indicator = "⏳"  # Pending

      # Format output
      output += f"{indicator} [{reminder_id}] {text}\n"
      output += f"   {remind_dt.strftime('%Y-%m-%d %H:%M')}"

      if recurring:
        output += f" (recurring: {recurring})"

      output += "\n\n"

    return output

  def mark_done(self, reminder_id):
    """Mark reminder as done

    Args:
      reminder_id: ID of the reminder

    Returns:
      Success message or error
    """
    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()

    # Check if reminder exists
    cursor.execute("SELECT text FROM reminders WHERE id = ?", (reminder_id,))
    result = cursor.fetchone()

    if not result:
      conn.close()
      return f"❌ Error: Reminder {reminder_id} not found"

    # Mark as done
    cursor.execute(
      """UPDATE reminders
         SET status = 'done', completed_at = datetime('now')
         WHERE id = ?""",
      (reminder_id,)
    )
    conn.commit()
    conn.close()

    return f"✓ Reminder {reminder_id} marked as done"

  def get_pending_count(self):
    """Get count of pending reminders

    Returns:
      Number of pending reminders
    """
    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()
    cursor.execute(
      """SELECT COUNT(*) FROM reminders
         WHERE status = 'pending'"""
    )
    count = cursor.fetchone()[0]
    conn.close()

    return count

  def get_overdue_reminders(self):
    """Get overdue reminders

    Returns:
      List of overdue reminders
    """
    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()
    cursor.execute(
      """SELECT id, text, remind_at FROM reminders
         WHERE status = 'pending'
         AND remind_at < datetime('now', 'localtime')
         ORDER BY remind_at"""
    )
    reminders = cursor.fetchall()
    conn.close()

    return reminders
