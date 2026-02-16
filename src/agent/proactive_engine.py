"""
Proactive Engine - On-demand contextual suggestions.

Phase 17: Generates proactive tips based on:
- User routines and patterns
- Exercise/health gaps
- Spending anomalies
- Pending habits and reminders
- Time-of-day context

Design: On-demand (not threaded) to avoid SQLite concurrency issues.
"""
import sqlite3
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional


class ProactiveEngine:
  """Generates contextual suggestions and proactive tips."""

  def __init__(self, data_dir: Path, user_profile=None):
    self.data_dir = Path(data_dir)
    self.profile = user_profile

  def get_suggestions(self) -> List[Dict]:
    """Generate all contextual suggestions.

    Returns list of {type, priority, message, action} dicts.
    """
    suggestions = []

    # Time-based suggestions
    suggestions.extend(self._time_suggestions())

    # Profile-based suggestions (if available)
    if self.profile:
      suggestions.extend(self._profile_suggestions())

    # Data-based suggestions
    suggestions.extend(self._habit_suggestions())
    suggestions.extend(self._finance_suggestions())
    suggestions.extend(self._reminder_suggestions())
    suggestions.extend(self._exercise_suggestions())

    # Sort by priority
    priority_order = {"high": 0, "medium": 1, "low": 2}
    suggestions.sort(key=lambda s: priority_order.get(s.get("priority", "low"), 3))

    return suggestions[:6]  # Top 6 suggestions

  def format_suggestions(self, suggestions: List[Dict] = None) -> str:
    """Format suggestions into a displayable string."""
    if suggestions is None:
      suggestions = self.get_suggestions()

    if not suggestions:
      return "💡 No suggestions right now — sab sorted hai!"

    lines = ["💡 Proactive Suggestions:\n"]
    emoji_map = {
      "routine": "🔄",
      "health": "🏃",
      "finance": "💰",
      "habit": "✅",
      "reminder": "⏰",
      "planning": "📋",
      "wellness": "🧘",
    }

    for i, s in enumerate(suggestions, 1):
      emoji = emoji_map.get(s.get("type", ""), "💡")
      priority = s.get("priority", "low")
      flag = "⚠️ " if priority == "high" else ""
      lines.append(f"  {i}. {emoji} {flag}{s['message']}")

    return "\n".join(lines)

  # ── Time-based suggestions ──────────────────────────────────

  def _time_suggestions(self) -> List[Dict]:
    """Suggestions based on time of day and day of week."""
    suggestions = []
    now = datetime.now()
    hour = now.hour
    weekday = now.weekday()

    if 5 <= hour < 9 and weekday < 5:
      suggestions.append({
        "type": "planning",
        "priority": "medium",
        "message": "Good morning! Review today's agenda? (type: agenda)",
        "action": "agenda"
      })

    if 12 <= hour < 14:
      suggestions.append({
        "type": "wellness",
        "priority": "low",
        "message": "Lunch break — stay hydrated aur stretch karo! 💧",
        "action": None
      })

    if 18 <= hour < 21:
      suggestions.append({
        "type": "planning",
        "priority": "medium",
        "message": "Evening time — log today's experiences? (type: log <activity>)",
        "action": "experience"
      })

    if weekday == 6 and 10 <= hour < 12:  # Sunday morning
      suggestions.append({
        "type": "finance",
        "priority": "medium",
        "message": "Sunday review: check this week's spending? (type: report)",
        "action": "report"
      })

    return suggestions

  # ── Profile-based suggestions ───────────────────────────────

  def _profile_suggestions(self) -> List[Dict]:
    """Suggestions from user profile engine."""
    if not self.profile:
      return []

    suggestions = []

    # Upcoming routines
    try:
      upcoming = self.profile.get_upcoming_routines(hours_ahead=2)
      for routine in upcoming[:2]:
        action = routine.get("action", "")
        suggestions.append({
          "type": "routine",
          "priority": "medium",
          "message": f"You usually do '{action}' around this time",
          "action": action
        })
    except Exception:
      pass

    # Mood-based
    try:
      mood = self.profile.get_current_mood()
      if mood == "stressed":
        suggestions.append({
          "type": "wellness",
          "priority": "high",
          "message": "You seem stressed — take a break, do some deep breathing 🧘",
          "action": None
        })
      elif mood == "sad":
        suggestions.append({
          "type": "wellness",
          "priority": "high",
          "message": "Feeling low? Kisi se baat karo ya journal mein likh lo ❤️",
          "action": "journal"
        })
    except Exception:
      pass

    return suggestions

  # ── Habit suggestions ───────────────────────────────────────

  def _habit_suggestions(self) -> List[Dict]:
    """Check pending habits for today."""
    habits_db = self.data_dir / "habits.db"
    if not habits_db.exists():
      return []

    try:
      conn = sqlite3.connect(habits_db)
      cursor = conn.cursor()

      # Get all habits
      cursor.execute("SELECT name FROM habits")
      all_habits = [r[0] for r in cursor.fetchall()]

      # Get today's completions
      today = date.today().isoformat()
      cursor.execute(
        "SELECT DISTINCT name FROM habit_logs WHERE log_date = ?",
        (today,)
      )
      done = {r[0] for r in cursor.fetchall()}
      conn.close()

      pending = [h for h in all_habits if h not in done]
      if pending:
        if len(pending) >= 3:
          return [{
            "type": "habit",
            "priority": "high",
            "message": f"{len(pending)} habits pending today: {', '.join(pending[:3])}...",
            "action": "habit list"
          }]
        else:
          return [{
            "type": "habit",
            "priority": "medium",
            "message": f"Pending habits: {', '.join(pending)}",
            "action": "habit list"
          }]
    except Exception:
      pass

    return []

  # ── Finance suggestions ─────────────────────────────────────

  def _finance_suggestions(self) -> List[Dict]:
    """Check for spending anomalies."""
    finance_db = self.data_dir / "finance.db"
    if not finance_db.exists():
      return []

    try:
      conn = sqlite3.connect(finance_db)
      cursor = conn.cursor()

      # This week's spending
      week_start = (date.today() - timedelta(days=date.today().weekday())).isoformat()
      cursor.execute("""
        SELECT COALESCE(SUM(amount), 0) FROM transactions
        WHERE type = 'expense' AND date >= ?
      """, (week_start,))
      this_week = cursor.fetchone()[0]

      # Last week's spending
      last_week_start = (date.today() - timedelta(days=date.today().weekday() + 7)).isoformat()
      last_week_end = (date.today() - timedelta(days=date.today().weekday() + 1)).isoformat()
      cursor.execute("""
        SELECT COALESCE(SUM(amount), 0) FROM transactions
        WHERE type = 'expense' AND date >= ? AND date <= ?
      """, (last_week_start, last_week_end))
      last_week = cursor.fetchone()[0]

      conn.close()

      # Spending spike detection
      if last_week > 0 and this_week > last_week * 1.2:
        pct = int((this_week / last_week - 1) * 100)
        return [{
          "type": "finance",
          "priority": "medium",
          "message": f"This week's spending is {pct}% higher than last week (₹{this_week:.0f} vs ₹{last_week:.0f})",
          "action": "report"
        }]

      # Low balance warning
      cursor_b = sqlite3.connect(finance_db).cursor()
      cursor_b.execute("SELECT COALESCE(SUM(balance), 0) FROM accounts")
      balance = cursor_b.fetchone()[0]
      cursor_b.connection.close()

      if 0 < balance < 1000:
        return [{
          "type": "finance",
          "priority": "high",
          "message": f"⚠️ Low balance warning: ₹{balance:.0f} remaining",
          "action": "balance"
        }]

    except Exception:
      pass

    return []

  # ── Reminder suggestions ────────────────────────────────────

  def _reminder_suggestions(self) -> List[Dict]:
    """Check for overdue or upcoming reminders."""
    reminders_db = self.data_dir / "reminders.db"
    if not reminders_db.exists():
      return []

    try:
      conn = sqlite3.connect(reminders_db)
      cursor = conn.cursor()

      now = datetime.now().isoformat()
      cursor.execute("""
        SELECT text, remind_at FROM reminders
        WHERE status = 'pending' AND remind_at <= ?
        ORDER BY remind_at ASC LIMIT 3
      """, (now,))
      overdue = cursor.fetchall()
      conn.close()

      if overdue:
        texts = [r[0] for r in overdue]
        return [{
          "type": "reminder",
          "priority": "high",
          "message": f"{len(overdue)} overdue reminder(s): {', '.join(texts[:2])}",
          "action": "reminders"
        }]
    except Exception:
      pass

    return []

  # ── Exercise gap detection ──────────────────────────────────

  def _exercise_suggestions(self) -> List[Dict]:
    """Check if user hasn't exercised recently."""
    brain_db = self.data_dir / "human_brain.db"
    if not brain_db.exists():
      return []

    try:
      conn = sqlite3.connect(brain_db)
      cursor = conn.cursor()

      # Look for exercise-related experiences in last 3 days
      three_days_ago = (date.today() - timedelta(days=3)).isoformat()
      exercise_words = ['gym', 'exercise', 'workout', 'run', 'jog', 'walk',
                        'yoga', 'swim', 'cycling', 'sports', 'cricket',
                        'football', 'badminton']
      query_parts = " OR ".join(f"text LIKE '%{w}%'" for w in exercise_words)

      cursor.execute(f"""
        SELECT COUNT(*) FROM experiences
        WHERE timestamp >= ? AND ({query_parts})
      """, (three_days_ago,))
      count = cursor.fetchone()[0]
      conn.close()

      if count == 0:
        return [{
          "type": "health",
          "priority": "medium",
          "message": "3+ days since last exercise logged — time for a workout? 💪",
          "action": None
        }]
    except Exception:
      pass

    return []
