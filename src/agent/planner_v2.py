"""
PHASE 13: Daily Planner V2 - Context-Aware Scheduling

Considers:
1. Habit streaks (don't break them!)
2. Energy level (match tasks to energy)
3. Pending reminders (time-sensitive first)
4. Work hours (respect work/life balance)
5. Budget limits (daily spending cap)

Features:
- Smart time slot allocation
- Energy-matched task ordering
- Streak protection alerts
- Budget-aware recommendations
"""
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
from datetime import datetime, date, timedelta, time
from dataclasses import dataclass, field
from enum import Enum
import sqlite3
import json


class EnergyLevel(Enum):
    VERY_LOW = 1
    LOW = 3
    MEDIUM = 5
    HIGH = 7
    VERY_HIGH = 9


class TaskPriority(Enum):
    CRITICAL = 1   # Health, streak-at-risk
    HIGH = 2       # Work, bills
    MEDIUM = 3     # Regular habits
    LOW = 4        # Leisure, optional
    OPTIONAL = 5   # Nice to have


@dataclass
class PlannerTask:
    """A task in the daily plan"""
    name: str
    time_slot: str  # morning, afternoon, evening, night
    priority: TaskPriority
    energy_required: int  # 1-10
    duration_mins: int
    category: str
    source: str  # habit, reminder, suggestion
    streak_at_risk: bool = False
    completed: bool = False
    notes: str = ""


@dataclass
class DailyPlan:
    """Complete daily plan"""
    date: str
    energy_level: int
    mood: str
    stress_level: int
    daily_budget: float
    spent_today: float
    
    tasks: List[PlannerTask] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    tips: List[str] = field(default_factory=list)
    
    def add_task(self, task: PlannerTask):
        self.tasks.append(task)
    
    def get_by_slot(self, slot: str) -> List[PlannerTask]:
        return [t for t in self.tasks if t.time_slot == slot]
    
    def pending_count(self) -> int:
        return sum(1 for t in self.tasks if not t.completed)
    
    def completed_count(self) -> int:
        return sum(1 for t in self.tasks if t.completed)


class PlannerV2:
    """
    Context-aware daily planner.
    
    Creates personalized daily schedules based on:
    - Energy levels
    - Habit streaks
    - Pending reminders
    - Budget constraints
    - Work hours
    """
    
    # Default work hours (24h format)
    WORK_HOURS = {"start": 9, "end": 18}
    
    # Energy requirements for different activities
    ENERGY_MAP = {
        "exercise": 7,
        "work": 6,
        "learning": 5,
        "meditation": 3,
        "reading": 4,
        "errands": 4,
        "rest": 1,
        "social": 5
    }
    
    # Time slot energy recommendations
    SLOT_ENERGY = {
        "morning": {"min": 5, "ideal": 7, "label": "High energy work"},
        "afternoon": {"min": 4, "ideal": 6, "label": "Steady tasks"},
        "evening": {"min": 3, "ideal": 5, "label": "Wind down"},
        "night": {"min": 1, "ideal": 3, "label": "Rest & prep"}
    }
    
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.rules = self._load_rules()
    
    def _load_rules(self) -> Dict:
        """Load planning rules"""
        rules_path = self.data_dir / "persona_rules.json"
        if rules_path.exists():
            return json.loads(rules_path.read_text())
        return {}
    
    def _conn(self, db_name: str):
        """Get DB connection"""
        path = self.data_dir / db_name
        if not path.exists():
            return None
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn
    
    # =====================================
    # CONTEXT GATHERING
    # =====================================
    
    def get_current_energy(self) -> Tuple[int, str, int]:
        """Get current energy, mood, stress from persona DB"""
        conn = self._conn("persona.db")
        if not conn:
            return 5, "neutral", 3
        
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT mood, energy_level, stress_level
                FROM emotional_state ORDER BY log_date DESC, log_time DESC LIMIT 1
            """)
            row = cursor.fetchone()
            if row:
                return row['energy_level'], row['mood'], row['stress_level']
            return 5, "neutral", 3
        except:
            return 5, "neutral", 3
        finally:
            conn.close()
    
    def get_habits(self) -> List[Dict]:
        """Get active habits with streak info"""
        conn = self._conn("habits.db")
        if not conn:
            return []
        
        try:
            cursor = conn.cursor()
            today = date.today().isoformat()
            
            cursor.execute("""
                SELECT h.id, h.name, h.frequency, h.streak, h.preferred_time,
                       (SELECT MAX(done_date) FROM habit_logs WHERE habit_id = h.id) as last_done
                FROM habits h WHERE h.status = 'active'
            """)
            
            habits = []
            for r in cursor.fetchall():
                done_today = r['last_done'] == today
                streak = r['streak'] or 0
                at_risk = r['frequency'] == 'daily' and not done_today and streak > 0
                
                habits.append({
                    "id": r['id'],
                    "name": r['name'],
                    "frequency": r['frequency'],
                    "streak": streak,
                    "preferred_time": r['preferred_time'] or "morning",
                    "done_today": done_today,
                    "at_risk": at_risk
                })
            
            return habits
        except:
            return []
        finally:
            conn.close()
    
    def get_reminders_today(self) -> List[Dict]:
        """Get today's reminders"""
        conn = self._conn("reminders.db")
        if not conn:
            return []
        
        try:
            cursor = conn.cursor()
            today = date.today().isoformat()
            
            cursor.execute("""
                SELECT text, remind_time FROM reminders
                WHERE remind_date = ? AND status = 'active'
                ORDER BY remind_time
            """, (today,))
            
            return [dict(r) for r in cursor.fetchall()]
        except:
            return []
        finally:
            conn.close()
    
    def get_budget_status(self) -> Tuple[float, float]:
        """Get daily budget limit and spent today"""
        conn = self._conn("finance.db")
        if not conn:
            return 500, 0  # Default limit
        
        try:
            cursor = conn.cursor()
            
            # Get last 30 days average as daily limit
            cursor.execute("""
                SELECT COALESCE(SUM(ABS(amount)), 0) / 30 as daily_avg
                FROM transactions WHERE type = 'expense'
                AND date >= DATE('now', '-30 days')
            """)
            daily_limit = cursor.fetchone()['daily_avg'] or 500
            
            # Get today's spending
            today = date.today().isoformat()
            cursor.execute("""
                SELECT COALESCE(SUM(ABS(amount)), 0) as spent
                FROM transactions WHERE type = 'expense' AND date = ?
            """, (today,))
            spent_today = cursor.fetchone()['spent'] or 0
            
            return daily_limit, spent_today
        except:
            return 500, 0
        finally:
            conn.close()
    
    # =====================================
    # PLAN GENERATION
    # =====================================
    
    def generate_plan(self, target_date: date = None) -> DailyPlan:
        """Generate a complete daily plan"""
        target_date = target_date or date.today()
        
        # Get current state
        energy, mood, stress = self.get_current_energy()
        daily_limit, spent_today = self.get_budget_status()
        habits = self.get_habits()
        reminders = self.get_reminders_today()
        
        # Create plan
        plan = DailyPlan(
            date=target_date.isoformat(),
            energy_level=energy,
            mood=mood,
            stress_level=stress,
            daily_budget=daily_limit,
            spent_today=spent_today
        )
        
        # Add habits as tasks
        for habit in habits:
            if habit['done_today']:
                continue  # Skip done habits
            
            # Determine time slot based on preference and energy
            slot = habit.get('preferred_time', 'morning')
            
            # Adjust for energy
            energy_needed = self.ENERGY_MAP.get(habit['name'].lower().split()[0], 5)
            if energy < 4 and energy_needed > 5:
                slot = "evening"  # Push high-energy to later
            
            priority = TaskPriority.CRITICAL if habit['at_risk'] else TaskPriority.MEDIUM
            
            task = PlannerTask(
                name=f"🏃 {habit['name']}",
                time_slot=slot,
                priority=priority,
                energy_required=energy_needed,
                duration_mins=30,
                category="habit",
                source="habit",
                streak_at_risk=habit['at_risk'],
                notes=f"Streak: {habit['streak']} days" if habit['streak'] > 0 else ""
            )
            plan.add_task(task)
        
        # Add reminders as tasks
        for rem in reminders:
            time_str = rem.get('remind_time', '')
            slot = self._time_to_slot(time_str)
            
            task = PlannerTask(
                name=f"📌 {rem['text']}",
                time_slot=slot,
                priority=TaskPriority.HIGH,
                energy_required=4,
                duration_mins=15,
                category="reminder",
                source="reminder"
            )
            plan.add_task(task)
        
        # Add warnings
        self._add_warnings(plan, habits, energy, stress, daily_limit, spent_today)
        
        # Add tips
        self._add_tips(plan, energy, mood)
        
        # Sort tasks by priority
        plan.tasks.sort(key=lambda t: (t.priority.value, -t.energy_required))
        
        return plan
    
    def _time_to_slot(self, time_str: str) -> str:
        """Convert time string to slot"""
        if not time_str:
            return "morning"
        
        try:
            hour = int(time_str.split(':')[0])
            if hour < 12:
                return "morning"
            elif hour < 17:
                return "afternoon"
            elif hour < 21:
                return "evening"
            else:
                return "night"
        except:
            return "morning"
    
    def _add_warnings(self, plan: DailyPlan, habits: List[Dict], 
                     energy: int, stress: int, budget: float, spent: float):
        """Add contextual warnings to plan"""
        
        # Streak warnings
        at_risk = [h['name'] for h in habits if h['at_risk']]
        if at_risk:
            plan.warnings.append(f"🔥 STREAK AT RISK: {', '.join(at_risk)}")
        
        # Energy warning
        if energy <= 3:
            plan.warnings.append("⚡ LOW ENERGY: Take it easy today")
        
        # Stress warning
        if stress >= 7:
            plan.warnings.append("😰 HIGH STRESS: Prioritize self-care")
        
        # Budget warning
        if spent >= budget * 0.8:
            remaining = budget - spent
            plan.warnings.append(f"💰 BUDGET TIGHT: Only ₹{remaining:.0f} left today")
        
        # Task overload
        if len(plan.tasks) > 8:
            plan.warnings.append("📋 HEAVY DAY: Consider postponing some tasks")
    
    def _add_tips(self, plan: DailyPlan, energy: int, mood: str):
        """Add helpful tips"""
        
        if energy >= 7:
            plan.tips.append("💪 High energy! Tackle the hard stuff now")
        elif energy <= 3:
            plan.tips.append("🧘 Low energy? Focus on one thing at a time")
        
        if mood in ["stressed", "anxious"]:
            plan.tips.append("😌 Take 5 min breaks every hour")
        elif mood in ["happy", "excited"]:
            plan.tips.append("🌟 Great mood! Perfect for creative work")
        
        if plan.spent_today == 0:
            plan.tips.append("👍 No spending yet - keep it up!")
    
    # =====================================
    # FORMATTING
    # =====================================
    
    def format_plan(self, plan: DailyPlan, ride_mode: bool = False) -> str:
        """Format plan for display"""
        if ride_mode:
            return self._format_ride_mode(plan)
        
        lines = []
        
        # Header
        lines.append(f"📅 **Plan for {plan.date}**\n")
        
        # Status bar
        energy_bar = "⚡" * min(plan.energy_level, 10)
        mood_emoji = {"happy": "😊", "stressed": "😰", "anxious": "😟", 
                     "excited": "🤩", "neutral": "😐", "sad": "😢"}.get(plan.mood, "😐")
        lines.append(f"{mood_emoji} {plan.mood.title()} | Energy: {energy_bar}")
        
        # Budget
        remaining = plan.daily_budget - plan.spent_today
        budget_emoji = "🟢" if remaining > plan.daily_budget * 0.5 else ("🟡" if remaining > 0 else "🔴")
        lines.append(f"{budget_emoji} Budget: ₹{remaining:.0f} remaining (₹{plan.spent_today:.0f} spent)")
        
        # Warnings
        if plan.warnings:
            lines.append("\n**⚠️ Alerts:**")
            for w in plan.warnings:
                lines.append(f"  {w}")
        
        # Tasks by slot
        for slot in ["morning", "afternoon", "evening", "night"]:
            tasks = plan.get_by_slot(slot)
            if tasks:
                lines.append(f"\n**{slot.upper()}:**")
                for task in tasks:
                    check = "✅" if task.completed else "⬜"
                    priority_mark = "❗" if task.priority == TaskPriority.CRITICAL else ""
                    streak_mark = "🔥" if task.streak_at_risk else ""
                    lines.append(f"  {check} {task.name} {priority_mark}{streak_mark}")
                    if task.notes:
                        lines.append(f"      └ {task.notes}")
        
        # Stats
        total = len(plan.tasks)
        done = plan.completed_count()
        pending = plan.pending_count()
        lines.append(f"\n**Progress:** {done}/{total} done, {pending} pending")
        
        # Tips
        if plan.tips:
            lines.append("\n**💡 Tips:**")
            for tip in plan.tips[:2]:
                lines.append(f"  {tip}")
        
        return "\n".join(lines)
    
    def _format_ride_mode(self, plan: DailyPlan) -> str:
        """Ultra-short ride mode format"""
        pending = plan.pending_count()
        
        # Find most critical
        critical = [t for t in plan.tasks if t.priority == TaskPriority.CRITICAL]
        at_risk = [t for t in plan.tasks if t.streak_at_risk]
        
        if at_risk:
            return f"🔥 {at_risk[0].name.replace('🏃 ', '')} streak at risk!"
        elif critical:
            return f"❗ Priority: {critical[0].name}"
        elif pending > 0:
            return f"📋 {pending} tasks pending today"
        else:
            return "✅ All done for today!"
    
    def format_quick_overview(self, plan: DailyPlan) -> str:
        """One-paragraph overview"""
        pending = plan.pending_count()
        at_risk = [t.name for t in plan.tasks if t.streak_at_risk]
        remaining = plan.daily_budget - plan.spent_today
        
        parts = []
        
        if at_risk:
            parts.append(f"🔥 Don't forget {at_risk[0].replace('🏃 ', '')}!")
        
        parts.append(f"{pending} tasks pending, {plan.mood} mood")
        
        if remaining < plan.daily_budget * 0.3:
            parts.append(f"budget tight (₹{remaining:.0f} left)")
        
        return " | ".join(parts)
    
    # =====================================
    # SMART SUGGESTIONS
    # =====================================
    
    def suggest_next_action(self, plan: DailyPlan = None) -> str:
        """Suggest what to do next based on current state"""
        if not plan:
            plan = self.generate_plan()
        
        # Get current hour
        hour = datetime.now().hour
        
        # Determine current slot
        if hour < 12:
            current_slot = "morning"
        elif hour < 17:
            current_slot = "afternoon"
        elif hour < 21:
            current_slot = "evening"
        else:
            current_slot = "night"
        
        # Find highest priority incomplete task for current slot
        slot_tasks = [t for t in plan.get_by_slot(current_slot) if not t.completed]
        
        if not slot_tasks:
            # Check other slots
            all_pending = [t for t in plan.tasks if not t.completed]
            if not all_pending:
                return "✅ Sab ho gaya! Relax karo ya naya goal set karo."
            slot_tasks = all_pending
        
        # Sort by priority
        slot_tasks.sort(key=lambda t: t.priority.value)
        next_task = slot_tasks[0]
        
        if next_task.streak_at_risk:
            return f"🔥 Pehle {next_task.name} karo - streak mat todo!"
        elif next_task.priority == TaskPriority.CRITICAL:
            return f"❗ Critical: {next_task.name}"
        else:
            return f"➡️ Next: {next_task.name}"
    
    def should_allow_leisure(self, plan: DailyPlan = None) -> Tuple[bool, str]:
        """Check if leisure activities are okay right now"""
        if not plan:
            plan = self.generate_plan()
        
        critical = [t for t in plan.tasks if t.priority == TaskPriority.CRITICAL and not t.completed]
        at_risk = [t for t in plan.tasks if t.streak_at_risk and not t.completed]
        
        if at_risk:
            return False, f"Pehle {at_risk[0].name.replace('🏃 ', '')} kar lo - streak!"
        if critical:
            return False, f"Critical task pending: {critical[0].name}"
        if plan.pending_count() > 5:
            return False, "Bahut tasks pending hain - thoda kaam pehle"
        
        return True, "Haan, leisure le sakte ho! ✨"
