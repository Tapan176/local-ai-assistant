"""
Scheduler Brain - Generates daily agenda and manages time
Integrates habits, reminders, and user profile to create a coherent plan.
"""
from pathlib import Path
from datetime import datetime, time
from typing import Dict, List, Optional

from src.core.habits import HabitTracker
from src.core.reminders import ReminderManager
from src.core.profile import ProfileManager
from src.core.finance import FinanceManager


class Scheduler:
    """Generates daily schedules and agendas"""
    
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        
        # Initialize dependencies
        self.habits = HabitTracker(self.data_dir / "habits.db")
        self.reminders = ReminderManager(self.data_dir / "reminders.db")
        self.profile = ProfileManager(self.data_dir / "profile.db")
        self.finance = FinanceManager(self.data_dir / "finance.db")
        
    def generate_agenda(self) -> str:
        """Generate a complete daily agenda
        
        Returns:
            Formatted agenda string
        """
        now = datetime.now()
        today_date = now.strftime("%Y-%m-%d")
        
        # 1. Get Profile Context (Wake/Sleep/Work times)
        routine = self.profile.get_routine()
        wake_time = routine.get('wake_time', '07:00')
        work_start = routine.get('work_start', '09:00')
        work_end = routine.get('work_end', '18:00')
        sleep_time = routine.get('sleep_time', '23:00')
        
        # 2. Get Habits
        pending_habits = self.habits.get_today_pending()
        
        # 3. Get Reminders (Pending and Overdue)
        overdue = self.reminders.get_overdue_reminders()
        pending_count = self.reminders.get_pending_count()
        
        # 4. Get Finance Status (for daily budget context)
        # We can add a finance snapshot to the agenda
        month_str = now.strftime("%Y-%m")
        # monthly_fin = self.finance.get_monthly_report(month_str) # Does not exist
        total_balance = self.finance.get_total_balance()
        
        # --- Build Output ---
        
        output = f"\n📅 DAILY AGENDA - {now.strftime('%A, %d %B %Y')}\n"
        output += "=" * 50 + "\n"
        
        # Morning Section
        output += f"\n🌅 MORNING ({wake_time} - {work_start})\n"
        output += self._suggest_morning_routine(wake_time, pending_habits)
        
        # Work/Day Section
        output += f"\n☀️ WORK/DAY ({work_start} - {work_end})\n"
        if overdue:
            output += "  ⚠️ OVERDUE TASKS:\n"
            for _, text, dt in overdue:
                output += f"    [ ] {text} (was due {dt})\n"
        else:
            output += "  ✓ No overdue tasks\n"
            
        output += f"  • Focus block 1\n"
        output += f"  • Focus block 2\n"
        
        # Evening Section
        output += f"\n🌙 EVENING ({work_end} - {sleep_time})\n"
        output += self._suggest_evening_routine(pending_habits)
        
        # Pending Habits
        if pending_habits:
            output += "\n🥚 PENDING HABITS\n"
            for habit in pending_habits:
                output += f"  [ ] {habit}\n"
        else:
            output += "\n✨ All daily habits completed!\n"
            
        # Finance Snapshot within Agenda
        balance = total_balance
        output += "\n💰 FINANCE PULSE\n"
        output += f"  Current Balance: ₹{balance}\n"
        if balance < 1000:
            output += "  ⚠️ Low balance warning! Spend wisely.\n"
            
        output += "\n" + "=" * 50 + "\n"
        
        return output

    def _suggest_morning_routine(self, wake_time: str, habits: List[str]) -> str:
        """Suggest morning items based on habits"""
        suggestions = []
        suggestions.append(f"  • Wake up at {wake_time}")
        
        morning_keywords = ['meditate', 'exercise', 'gym', 'workout', 'run', 'walk', 'brush', 'shower', 'breakfast', 'yoga']
        
        for habit in habits:
            if any(kw in habit.lower() for kw in morning_keywords):
                suggestions.append(f"  • Habit: {habit}")
        
        if len(suggestions) == 1:
            suggestions.append("  • Hydrate and stretch")
            suggestions.append("  • Review daily plan")
            
        return "\n".join(suggestions) + "\n"

    def _suggest_evening_routine(self, habits: List[str]) -> str:
        """Suggest evening items"""
        suggestions = []
        
        evening_keywords = ['read', 'journal', 'sleep', 'bed', 'clean', 'prep', 'wind down']
        
        for habit in habits:
            if any(kw in habit.lower() for kw in evening_keywords):
                suggestions.append(f"  • Habit: {habit}")
        
        if not suggestions:
            suggestions.append("  • Read for 20 mins")
            suggestions.append("  • Update journal")
            
        return "\n".join(suggestions) + "\n"
