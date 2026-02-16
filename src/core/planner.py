"""
Daily Planner - Plan command for daily assistance
"""
import sqlite3
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import List, Dict


class DailyPlanner:
    """Generate daily plans and suggestions"""
    
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
    
    def generate_plan(self) -> str:
        """Generate a daily plan based on available data
        
        Returns:
            Formatted daily plan
        """
        today = date.today()
        now = datetime.now()
        
        output = "\n" + "="*60 + "\n"
        output += f"   📅 DAILY PLAN - {today.strftime('%A, %B %d, %Y')}\n"
        output += "="*60 + "\n"
        
        # 1. Today's reminders
        output += self._get_reminders_section()
        
        # 2. Pending habits
        output += self._get_habits_section()
        
        # 3. Recent context (journal/memories)
        output += self._get_context_section()
        
        # 4. Financial snapshot
        output += self._get_finance_snapshot()
        
        # 5. Suggested actions
        output += self._get_suggestions()
        
        output += "="*60 + "\n"
        output += "Have a productive day! 🚀\n"
        
        return output
    
    def _get_reminders_section(self) -> str:
        """Get today's reminders"""
        output = "\n⏰ TODAY'S REMINDERS\n"
        output += "-" * 50 + "\n"
        
        reminders_db = self.data_dir / "reminders.db"
        if not reminders_db.exists():
            return output + "No reminders\n"
        
        conn = sqlite3.connect(reminders_db)
        cursor = conn.cursor()
        
        today = date.today()
        tomorrow = today + timedelta(days=1)
        now = datetime.now()
        
        # Get today's reminders
        cursor.execute(
            """SELECT id, text, remind_at FROM reminders
               WHERE status = 'pending'
               AND remind_at >= ?
               AND remind_at < ?
               ORDER BY remind_at""",
            (today.strftime('%Y-%m-%d'), tomorrow.strftime('%Y-%m-%d'))
        )
        today_reminders = cursor.fetchall()
        
        # Get overdue
        cursor.execute(
            """SELECT id, text, remind_at FROM reminders
               WHERE status = 'pending'
               AND remind_at < ?
               ORDER BY remind_at""",
            (now.strftime('%Y-%m-%d %H:%M:%S'),)
        )
        overdue = cursor.fetchall()
        
        conn.close()
        
        if overdue:
            output += "\n🔴 OVERDUE:\n"
            for rid, text, remind_at in overdue[:3]:
                output += f"  [{rid}] {text}\n"
        
        if today_reminders:
            output += "\nToday:\n"
            for rid, text, remind_at in today_reminders:
                time_str = remind_at[11:16] if len(remind_at) > 10 else ""
                output += f"  [{time_str}] {text}\n"
        
        if not overdue and not today_reminders:
            output += "No reminders for today ✓\n"
        
        return output
    
    def _get_habits_section(self) -> str:
        """Get pending habits for today"""
        output = "\n✓ HABITS TO COMPLETE\n"
        output += "-" * 50 + "\n"
        
        habits_db = self.data_dir / "habits.db"
        if not habits_db.exists():
            return output + "No habits tracked\n"
        
        conn = sqlite3.connect(habits_db)
        cursor = conn.cursor()
        
        today = date.today()
        
        # Get pending habits
        cursor.execute(
            """SELECT h.name FROM habits h
               WHERE h.id NOT IN (
                   SELECT habit_id FROM habit_logs WHERE log_date = ?
               )""",
            (today,)
        )
        pending = cursor.fetchall()
        
        # Get completed
        cursor.execute(
            """SELECT h.name FROM habits h
               WHERE h.id IN (
                   SELECT habit_id FROM habit_logs WHERE log_date = ?
               )""",
            (today,)
        )
        completed = cursor.fetchall()
        
        conn.close()
        
        if pending:
            output += "Pending:\n"
            for (name,) in pending:
                output += f"  ⬜ {name}\n"
        
        if completed:
            output += "\nCompleted:\n"
            for (name,) in completed:
                output += f"  ✅ {name}\n"
        
        if not pending and not completed:
            output += "No habits tracked yet\n"
        
        return output
    
    def _get_context_section(self) -> str:
        """Get recent context from journal/memories"""
        output = "\n📝 RECENT NOTES\n"
        output += "-" * 50 + "\n"
        
        items = []
        
        # Recent journal entries
        journal_db = self.data_dir / "journal.db"
        if journal_db.exists():
            conn = sqlite3.connect(journal_db)
            cursor = conn.cursor()
            cursor.execute(
                """SELECT entry_text, entry_date FROM journal_entries
                   ORDER BY entry_date DESC, created_at DESC LIMIT 3"""
            )
            for text, entry_date in cursor.fetchall():
                preview = text[:60] + "..." if len(text) > 60 else text
                items.append(f"[{entry_date}] {preview}")
            conn.close()
        
        if items:
            for item in items:
                output += f"  {item}\n"
        else:
            output += "No recent entries\n"
        
        return output
    
    def _get_finance_snapshot(self) -> str:
        """Get quick finance snapshot"""
        output = "\n💰 FINANCE SNAPSHOT\n"
        output += "-" * 50 + "\n"
        
        finance_db = self.data_dir / "finance.db"
        if not finance_db.exists():
            return output + "No finance data\n"
        
        conn = sqlite3.connect(finance_db)
        cursor = conn.cursor()
        
        # Get total balance
        cursor.execute("SELECT SUM(balance) FROM accounts")
        total = cursor.fetchone()[0] or 0
        
        # Today's spending
        today = date.today()
        cursor.execute(
            """SELECT SUM(amount) FROM transactions
               WHERE type = 'expense'
               AND date(date) = ?""",
            (today.strftime('%Y-%m-%d'),)
        )
        today_spent = cursor.fetchone()[0] or 0
        
        # This month's spending
        cursor.execute(
            """SELECT SUM(amount) FROM transactions
               WHERE type = 'expense'
               AND strftime('%Y-%m', date) = ?""",
            (today.strftime('%Y-%m'),)
        )
        month_spent = cursor.fetchone()[0] or 0
        
        conn.close()
        
        def fmt(amount):
            return f"₹{int(amount)}" if amount == int(amount) else f"₹{amount:.2f}"
        
        output += f"Balance: {fmt(total)}\n"
        output += f"Spent Today: {fmt(today_spent)}\n"
        output += f"Spent This Month: {fmt(month_spent)}\n"
        
        return output
    
    def _get_suggestions(self) -> str:
        """Generate actionable suggestions"""
        output = "\n💡 SUGGESTIONS\n"
        output += "-" * 50 + "\n"
        
        suggestions = []
        
        # Check for pending habits
        habits_db = self.data_dir / "habits.db"
        if habits_db.exists():
            conn = sqlite3.connect(habits_db)
            cursor = conn.cursor()
            today = date.today()
            
            cursor.execute(
                """SELECT COUNT(*) FROM habits h
                   WHERE h.id NOT IN (
                       SELECT habit_id FROM habit_logs WHERE log_date = ?
                   )""",
                (today,)
            )
            pending = cursor.fetchone()[0]
            conn.close()
            
            if pending > 0:
                suggestions.append(f"Complete {pending} pending habit(s)")
        
        # Check for overdue reminders
        reminders_db = self.data_dir / "reminders.db"
        if reminders_db.exists():
            conn = sqlite3.connect(reminders_db)
            cursor = conn.cursor()
            
            cursor.execute(
                """SELECT COUNT(*) FROM reminders
                   WHERE status = 'pending'
                   AND remind_at < datetime('now')"""
            )
            overdue = cursor.fetchone()[0]
            conn.close()
            
            if overdue > 0:
                suggestions.append(f"Handle {overdue} overdue reminder(s)")
        
        # Check if no journal entry today
        journal_db = self.data_dir / "journal.db"
        if journal_db.exists():
            conn = sqlite3.connect(journal_db)
            cursor = conn.cursor()
            today = date.today()
            
            cursor.execute(
                "SELECT COUNT(*) FROM journal_entries WHERE entry_date = ?",
                (today,)
            )
            entries_today = cursor.fetchone()[0]
            conn.close()
            
            if entries_today == 0:
                suggestions.append("Write a journal entry")
        
        if suggestions:
            for i, suggestion in enumerate(suggestions, 1):
                output += f"  {i}. {suggestion}\n"
        else:
            output += "  All caught up! Great job! 🎉\n"
        
        return output
