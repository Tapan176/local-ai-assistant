"""
Report Generator - Comprehensive life reports
"""
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta


class ReportGenerator:
    """Generate comprehensive reports for TAPAN_AI"""
    
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
    
    def _format_inr(self, amount):
        """Format amount in INR"""
        if amount == int(amount):
            return f"₹{int(amount)}"
        return f"₹{amount:.2f}"
    
    def generate_full_report(self):
        """Generate comprehensive life report"""
        output = "\n" + "="*60 + "\n"
        output += "   📊 TAPAN_AI LIFE REPORT\n"
        output += f"   Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        output += "="*60 + "\n"
        
        output += self._finance_section()
        output += self._life_section()
        output += self._stats_section()
        
        output += "="*60 + "\n"
        return output
    
    def _finance_section(self):
        """Generate finance section of report"""
        output = "\n💰 FINANCE SUMMARY\n"
        output += "-" * 60 + "\n"
        
        finance_db = self.data_dir / "finance.db"
        if not finance_db.exists():
            return output + "No finance data yet\n"
        
        conn = sqlite3.connect(finance_db)
        cursor = conn.cursor()
        
        # Current balances
        cursor.execute("SELECT name, balance FROM accounts ORDER BY name")
        accounts = cursor.fetchall()
        
        if accounts:
            output += "\nAccount Balances:\n"
            total = 0
            for name, balance in accounts:
                output += f"  {name}: {self._format_inr(balance)}\n"
                total += balance
            output += f"  Total: {self._format_inr(total)}\n"
        
        # Monthly spend by category
        now = datetime.now()
        cursor.execute(
            """SELECT category, SUM(amount) as total
               FROM transactions
               WHERE type = 'expense'
               AND strftime('%Y-%m', date) = ?
               GROUP BY category
               ORDER BY total DESC""",
            (now.strftime('%Y-%m'),)
        )
        categories = cursor.fetchall()
        
        if categories:
            output += f"\nMonthly Expenses ({now.strftime('%B %Y')}):\n"
            total_expense = 0
            for category, amount in categories:
                output += f"  {category}: {self._format_inr(amount)}\n"
                total_expense += amount
            output += f"  Total: {self._format_inr(total_expense)}\n"
            
            # Top 3 categories
            output += "\nTop 3 Categories:\n"
            for i, (category, amount) in enumerate(categories[:3], 1):
                pct = (amount / total_expense * 100) if total_expense > 0 else 0
                output += f"  {i}. {category}: {self._format_inr(amount)} ({pct:.1f}%)\n"
        else:
            output += "\nNo expenses this month\n"
        
        # Monthly income
        cursor.execute(
            """SELECT SUM(amount) FROM transactions
               WHERE type = 'income'
               AND strftime('%Y-%m', date) = ?""",
            (now.strftime('%Y-%m'),)
        )
        income = cursor.fetchone()[0] or 0
        output += f"\nMonthly Income: {self._format_inr(income)}\n"
        
        if categories:
            net = income - total_expense
            output += f"Net: {self._format_inr(net)}\n"
        
        conn.close()
        return output
    
    def _life_section(self):
        """Generate life section of report"""
        output = "\n📔 LIFE SUMMARY\n"
        output += "-" * 60 + "\n"
        
        # Last 5 memories
        memory_db = self.data_dir / "memory.db"
        if memory_db.exists():
            conn = sqlite3.connect(memory_db)
            cursor = conn.cursor()
            cursor.execute(
                """SELECT text, timestamp FROM memories
                   ORDER BY timestamp DESC LIMIT 5"""
            )
            memories = cursor.fetchall()
            conn.close()
            
            if memories:
                output += "\nRecent Memories:\n"
                for text, ts in memories:
                    date_str = ts[:10] if ts else "?"
                    text_preview = text[:50] + "..." if len(text) > 50 else text
                    output += f"  [{date_str}] {text_preview}\n"
        
        # Last 5 journal entries
        journal_db = self.data_dir / "journal.db"
        if journal_db.exists():
            conn = sqlite3.connect(journal_db)
            cursor = conn.cursor()
            cursor.execute(
                """SELECT entry_text, entry_date, tags FROM journal_entries
                   ORDER BY entry_date DESC, created_at DESC LIMIT 5"""
            )
            entries = cursor.fetchall()
            conn.close()
            
            if entries:
                output += "\nRecent Journal Entries:\n"
                for text, date, tags in entries:
                    text_preview = text[:45] + "..." if len(text) > 45 else text
                    output += f"  [{date}] {text_preview}\n"
                    if tags:
                        output += f"          Tags: {tags}\n"
        
        # Pending reminders
        reminders_db = self.data_dir / "reminders.db"
        if reminders_db.exists():
            conn = sqlite3.connect(reminders_db)
            cursor = conn.cursor()
            cursor.execute(
                """SELECT id, text, remind_at FROM reminders
                   WHERE status = 'pending'
                   ORDER BY remind_at LIMIT 5"""
            )
            reminders = cursor.fetchall()
            conn.close()
            
            if reminders:
                output += "\nPending Reminders:\n"
                now = datetime.now()
                for rid, text, remind_at in reminders:
                    remind_dt = datetime.strptime(remind_at, '%Y-%m-%d %H:%M:%S')
                    indicator = "🔴" if remind_dt < now else "⏳"
                    output += f"  {indicator} [{rid}] {text}\n"
                    output += f"      Due: {remind_at[:16]}\n"
        
        return output
    
    def _stats_section(self):
        """Generate stats section"""
        output = "\n📈 ACTIVITY STATS\n"
        output += "-" * 60 + "\n"
        
        stats = {}
        
        # Memory count
        memory_db = self.data_dir / "memory.db"
        if memory_db.exists():
            conn = sqlite3.connect(memory_db)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM memories")
            stats['memories'] = cursor.fetchone()[0]
            conn.close()
        
        # Journal count
        journal_db = self.data_dir / "journal.db"
        if journal_db.exists():
            conn = sqlite3.connect(journal_db)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM journal_entries")
            stats['journal_entries'] = cursor.fetchone()[0]
            cursor.execute(
                """SELECT COUNT(*) FROM journal_entries
                   WHERE strftime('%Y-%m', entry_date) = strftime('%Y-%m', 'now')"""
            )
            stats['journal_this_month'] = cursor.fetchone()[0]
            conn.close()
        
        # Transaction count this month
        finance_db = self.data_dir / "finance.db"
        if finance_db.exists():
            conn = sqlite3.connect(finance_db)
            cursor = conn.cursor()
            cursor.execute(
                """SELECT COUNT(*) FROM transactions
                   WHERE strftime('%Y-%m', date) = strftime('%Y-%m', 'now')"""
            )
            stats['transactions_this_month'] = cursor.fetchone()[0]
            conn.close()
        
        # Reminder count
        reminders_db = self.data_dir / "reminders.db"
        if reminders_db.exists():
            conn = sqlite3.connect(reminders_db)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM reminders WHERE status = 'pending'")
            stats['pending_reminders'] = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM reminders WHERE status = 'done'")
            stats['completed_reminders'] = cursor.fetchone()[0]
            conn.close()
        
        # Habits
        habits_db = self.data_dir / "habits.db"
        if habits_db.exists():
            conn = sqlite3.connect(habits_db)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM habits")
            stats['habits'] = cursor.fetchone()[0]
            conn.close()
        
        output += f"\nMemories Stored: {stats.get('memories', 0)}\n"
        output += f"Journal Entries: {stats.get('journal_entries', 0)} ({stats.get('journal_this_month', 0)} this month)\n"
        output += f"Transactions This Month: {stats.get('transactions_this_month', 0)}\n"
        output += f"Reminders: {stats.get('pending_reminders', 0)} pending, {stats.get('completed_reminders', 0)} done\n"
        
        if 'habits' in stats:
            output += f"Habits Tracked: {stats['habits']}\n"
        
        return output
    
    def generate_weekly_report(self):
        """Generate weekly summary report"""
        output = "\n" + "="*60 + "\n"
        output += "   📅 WEEKLY SUMMARY\n"
        output += f"   Week ending: {datetime.now().strftime('%Y-%m-%d')}\n"
        output += "="*60 + "\n"
        
        # Calculate week range
        today = datetime.now()
        week_start = today - timedelta(days=7)
        
        finance_db = self.data_dir / "finance.db"
        if finance_db.exists():
            conn = sqlite3.connect(finance_db)
            cursor = conn.cursor()
            
            # Weekly expenses
            cursor.execute(
                """SELECT SUM(amount) FROM transactions
                   WHERE type = 'expense'
                   AND date >= ?""",
                (week_start.strftime('%Y-%m-%d'),)
            )
            weekly_expense = cursor.fetchone()[0] or 0
            
            # Weekly income
            cursor.execute(
                """SELECT SUM(amount) FROM transactions
                   WHERE type = 'income'
                   AND date >= ?""",
                (week_start.strftime('%Y-%m-%d'),)
            )
            weekly_income = cursor.fetchone()[0] or 0
            
            conn.close()
            
            output += f"\n💰 Weekly Finance:\n"
            output += f"  Income: {self._format_inr(weekly_income)}\n"
            output += f"  Expenses: {self._format_inr(weekly_expense)}\n"
            output += f"  Net: {self._format_inr(weekly_income - weekly_expense)}\n"
        
        # Journal entries this week
        journal_db = self.data_dir / "journal.db"
        if journal_db.exists():
            conn = sqlite3.connect(journal_db)
            cursor = conn.cursor()
            cursor.execute(
                """SELECT COUNT(*) FROM journal_entries
                   WHERE entry_date >= ?""",
                (week_start.strftime('%Y-%m-%d'),)
            )
            journal_count = cursor.fetchone()[0]
            conn.close()
            output += f"\n📔 Journal entries this week: {journal_count}\n"
        
        # Habits this week
        habits_db = self.data_dir / "habits.db"
        if habits_db.exists():
            conn = sqlite3.connect(habits_db)
            cursor = conn.cursor()
            cursor.execute(
                """SELECT name, COUNT(*) FROM habit_logs
                   WHERE log_date >= ?
                   GROUP BY name""",
                (week_start.strftime('%Y-%m-%d'),)
            )
            habit_logs = cursor.fetchall()
            conn.close()
            
            if habit_logs:
                output += f"\n✓ Habits Completed:\n"
                for name, count in habit_logs:
                    output += f"  {name}: {count}x\n"
        
        output += "\n" + "="*60 + "\n"
        return output
