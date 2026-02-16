"""
Habit Tool - Complete habit tracking with streaks
Features: add, mark done, streaks, reminders, stats
"""
from typing import Dict, Any, List, Optional
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta, date
from src.agent.tools.base import BaseTool, ToolResult


class HabitTool(BaseTool):
    """
    Habit tracking with streak management.
    
    Features:
    - Add habits (daily/weekly)
    - Mark done (increments streak)
    - Track longest streak
    - Set reminder times
    - View stats
    """
    
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.db_path = self.data_dir / "habits.db"
        self._ensure_schema()
    
    def _get_existing_columns(self, cursor, table_name: str) -> set:
        """Get set of existing column names from a table"""
        cursor.execute(f"PRAGMA table_info({table_name})")
        return {row[1] for row in cursor.fetchall()}
    
    def _migrate_habits_table(self, cursor, existing_cols: set):
        """Add missing columns to habits table (Phase 11 migration)"""
        new_cols = {
            "reminder_time": "TEXT",
            "target_count": "INTEGER DEFAULT 1",
            "streak_current": "INTEGER DEFAULT 0",
            "streak_best": "INTEGER DEFAULT 0",
            "last_done": "DATE",
            "status": "TEXT DEFAULT 'active'"
        }
        
        for col_name, col_def in new_cols.items():
            if col_name not in existing_cols:
                try:
                    cursor.execute(f"ALTER TABLE habits ADD COLUMN {col_name} {col_def}")
                    print(f"  Habits migrated: Added column '{col_name}'")
                except sqlite3.OperationalError as e:
                    if "duplicate column" not in str(e).lower():
                        raise
    
    def _migrate_habit_logs_table(self, cursor, existing_cols: set):
        """Add missing columns to habit_logs table"""
        new_cols = {
            "name": "TEXT",  # For legacy compatibility
            "done_time": "TIME",
            "count": "INTEGER DEFAULT 1",
            "notes": "TEXT",
            "mood": "TEXT"
        }
        
        for col_name, col_def in new_cols.items():
            if col_name not in existing_cols:
                try:
                    cursor.execute(f"ALTER TABLE habit_logs ADD COLUMN {col_name} {col_def}")
                    print(f"  Habit logs migrated: Added column '{col_name}'")
                except sqlite3.OperationalError as e:
                    if "duplicate column" not in str(e).lower():
                        raise
    
    def _ensure_schema(self):
        """Create habits tables with streak support. Migrates legacy schemas."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Step 1: Create tables if not exist (full schema)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS habits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                frequency TEXT DEFAULT 'daily',
                reminder_time TEXT,
                target_count INTEGER DEFAULT 1,
                streak_current INTEGER DEFAULT 0,
                streak_best INTEGER DEFAULT 0,
                last_done DATE,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS habit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                habit_id INTEGER NOT NULL,
                done_date DATE NOT NULL,
                done_time TIME,
                count INTEGER DEFAULT 1,
                notes TEXT,
                mood TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (habit_id) REFERENCES habits(id) ON DELETE CASCADE,
                UNIQUE(habit_id, done_date)
            )
        """)
        
        # Step 2: Migrate legacy tables (add missing columns)
        habits_cols = self._get_existing_columns(cursor, "habits")
        self._migrate_habits_table(cursor, habits_cols)
        
        logs_cols = self._get_existing_columns(cursor, "habit_logs")
        self._migrate_habit_logs_table(cursor, logs_cols)
        
        # Step 3: Create indexes AFTER migration
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_habit_logs_date ON habit_logs(done_date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_habits_status ON habits(status)")
        
        conn.commit()
        conn.close()
    
    @property
    def name(self) -> str:
        return "habit"
    
    @property
    def description(self) -> str:
        return "Track habits with streaks: add, mark done, view stats"
    
    @property
    def actions(self) -> list:
        return ["add", "done", "list", "streak", "delete", "stats", "history", "set_reminder"]
    
    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _calculate_streak(self, conn, habit_id: int, frequency: str) -> int:
        """Calculate current streak for a habit"""
        cursor = conn.cursor()
        today = date.today()
        
        if frequency == 'daily':
            # Check consecutive days
            streak = 0
            check_date = today
            
            while True:
                cursor.execute(
                    "SELECT 1 FROM habit_logs WHERE habit_id = ? AND done_date = ?",
                    (habit_id, check_date.isoformat())
                )
                if cursor.fetchone():
                    streak += 1
                    check_date -= timedelta(days=1)
                else:
                    # Allow 1 day grace period for today
                    if check_date == today:
                        check_date -= timedelta(days=1)
                        continue
                    break
            
            return streak
        
        elif frequency == 'weekly':
            # Check consecutive weeks
            streak = 0
            cursor.execute("""
                SELECT DISTINCT strftime('%Y-%W', done_date) as week
                FROM habit_logs
                WHERE habit_id = ?
                ORDER BY done_date DESC
            """, (habit_id,))
            
            weeks = [row['week'] for row in cursor.fetchall()]
            
            for i, week in enumerate(weeks):
                if i == 0:
                    streak = 1
                else:
                    streak += 1
            
            return streak
        
        return 0
    
    def _is_done_today(self, conn, habit_id: int) -> bool:
        """Check if habit is done today"""
        cursor = conn.cursor()
        today = date.today().isoformat()
        cursor.execute(
            "SELECT 1 FROM habit_logs WHERE habit_id = ? AND done_date = ?",
            (habit_id, today)
        )
        return cursor.fetchone() is not None

    def execute(self, action: str, params: Dict[str, Any]) -> ToolResult:
        conn = self._get_conn()
        cursor = conn.cursor()
        
        try:
            # ===== ADD =====
            if action == "add":
                name = params.get("name", "").strip()
                if not name:
                    return ToolResult(success=False, message="Habit name required")
                
                description = params.get("description", "")
                frequency = params.get("frequency", "daily")
                reminder_time = params.get("reminder_time")
                target = params.get("target", 1)
                
                try:
                    cursor.execute("""
                        INSERT INTO habits (name, description, frequency, reminder_time, target_count)
                        VALUES (?, ?, ?, ?, ?)
                    """, (name, description, frequency, reminder_time, target))
                    conn.commit()
                    
                    msg = f"✓ Added habit: {name} ({frequency})"
                    if reminder_time:
                        msg += f" - Reminder at {reminder_time}"
                    return ToolResult(success=True, message=msg)
                    
                except sqlite3.IntegrityError:
                    return ToolResult(success=False, message=f"Habit '{name}' already exists")
            
            # ===== DONE / MARK =====
            elif action in ["done", "mark"]:
                name = params.get("name", "").strip()
                notes = params.get("notes", "")
                mood = params.get("mood", "")
                done_date = params.get("date", date.today().isoformat())
                
                if not name:
                    return ToolResult(success=False, message="Habit name required")
                
                # Find habit
                cursor.execute("SELECT * FROM habits WHERE LOWER(name) LIKE ?", (f"%{name.lower()}%",))
                habit = cursor.fetchone()
                
                if not habit:
                    return ToolResult(success=False, message=f"Habit '{name}' not found")
                
                habit_id = habit['id']
                habit_name = habit['name']
                frequency = habit['frequency']
                old_streak = habit['streak_current']
                
                # Check if already done today
                cursor.execute(
                    "SELECT id FROM habit_logs WHERE habit_id = ? AND done_date = ?",
                    (habit_id, done_date)
                )
                existing = cursor.fetchone()
                
                if existing:
                    # Update count
                    cursor.execute("""
                        UPDATE habit_logs SET count = count + 1, notes = COALESCE(?, notes)
                        WHERE id = ?
                    """, (notes, existing['id']))
                else:
                    # Insert new log - include name for legacy schema compatibility  
                    cursor.execute("""
                        INSERT INTO habit_logs (habit_id, name, done_date, done_time, notes, mood)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (habit_id, habit_name, done_date, datetime.now().strftime("%H:%M"), notes, mood))
                
                # Calculate new streak
                new_streak = self._calculate_streak(conn, habit_id, frequency)
                best_streak = max(habit['streak_best'], new_streak)
                
                # Update habit
                cursor.execute("""
                    UPDATE habits SET 
                        streak_current = ?,
                        streak_best = ?,
                        last_done = ?
                    WHERE id = ?
                """, (new_streak, best_streak, done_date, habit_id))
                
                conn.commit()
                
                # Build response
                streak_emoji = "🔥" * min(new_streak, 5)
                msg = f"✓ {habit_name} marked done! {streak_emoji}\n"
                msg += f"   🔄 Current streak: {new_streak} days\n"
                msg += f"   🏆 Best streak: {best_streak} days"
                
                if new_streak > old_streak:
                    msg += "\n   ⬆️ Streak increased!"
                
                return ToolResult(success=True, message=msg)
            
            # ===== LIST =====
            elif action == "list":
                status = params.get("status", "active")
                
                cursor.execute("""
                    SELECT h.*, 
                           (SELECT COUNT(*) FROM habit_logs hl WHERE hl.habit_id = h.id) as total_done,
                           (SELECT done_date FROM habit_logs hl WHERE hl.habit_id = h.id ORDER BY done_date DESC LIMIT 1) as last_log
                    FROM habits h
                    WHERE h.status = ?
                    ORDER BY h.streak_current DESC
                """, (status,))
                
                habits = cursor.fetchall()
                
                if not habits:
                    return ToolResult(success=True, message="No active habits. Use 'add habit' to create one!")
                
                today = date.today().isoformat()
                lines = ["💪 Active Habits:"]
                
                for h in habits:
                    done_today = self._is_done_today(conn, h['id'])
                    status_icon = "✅" if done_today else "⬜"
                    streak_fire = "🔥" * min(h['streak_current'], 3)
                    
                    line = f"  {status_icon} {h['name']} - {h['streak_current']} day streak {streak_fire}"
                    if h['reminder_time']:
                        line += f" (⏰ {h['reminder_time']})"
                    lines.append(line)
                
                # Summary
                done_count = sum(1 for h in habits if self._is_done_today(conn, h['id']))
                lines.append(f"\n📊 {done_count}/{len(habits)} completed today")
                
                return ToolResult(success=True, message="\n".join(lines))
            
            # ===== STREAK =====
            elif action == "streak":
                name = params.get("name", "").strip()
                
                if name:
                    # Specific habit
                    cursor.execute("SELECT * FROM habits WHERE LOWER(name) LIKE ?", (f"%{name.lower()}%",))
                    habit = cursor.fetchone()
                    
                    if not habit:
                        return ToolResult(success=False, message=f"Habit '{name}' not found")
                    
                    lines = [f"🔥 {habit['name']} Streak Stats:"]
                    lines.append(f"   Current: {habit['streak_current']} days")
                    lines.append(f"   Best: {habit['streak_best']} days")
                    lines.append(f"   Last done: {habit['last_done'] or 'Never'}")
                    
                    # Get weekly completion
                    cursor.execute("""
                        SELECT COUNT(DISTINCT done_date) as days
                        FROM habit_logs
                        WHERE habit_id = ? AND done_date >= date('now', '-7 days')
                    """, (habit['id'],))
                    week_count = cursor.fetchone()['days']
                    lines.append(f"   This week: {week_count}/7 days")
                    
                    return ToolResult(success=True, message="\n".join(lines))
                
                else:
                    # All habits
                    cursor.execute("""
                        SELECT name, streak_current, streak_best
                        FROM habits WHERE status = 'active'
                        ORDER BY streak_current DESC
                    """)
                    
                    habits = cursor.fetchall()
                    if not habits:
                        return ToolResult(success=True, message="No habits to show streaks for")
                    
                    lines = ["🔥 All Streaks:"]
                    for h in habits:
                        fire = "🔥" * min(h['streak_current'], 5)
                        lines.append(f"  {h['name']}: {h['streak_current']} days {fire} (best: {h['streak_best']})")
                    
                    return ToolResult(success=True, message="\n".join(lines))
            
            # ===== STATS =====
            elif action == "stats":
                # Overall statistics
                cursor.execute("SELECT COUNT(*) as total FROM habits WHERE status = 'active'")
                total_habits = cursor.fetchone()['total']
                
                cursor.execute("SELECT SUM(streak_current) as sum FROM habits WHERE status = 'active'")
                total_streak = cursor.fetchone()['sum'] or 0
                
                cursor.execute("SELECT MAX(streak_best) as max FROM habits")
                best_ever = cursor.fetchone()['max'] or 0
                
                cursor.execute("SELECT COUNT(*) as count FROM habit_logs WHERE done_date >= date('now', '-30 days')")
                last_30 = cursor.fetchone()['count']
                
                cursor.execute("SELECT COUNT(*) as count FROM habit_logs WHERE done_date >= date('now', '-7 days')")
                last_7 = cursor.fetchone()['count']
                
                lines = ["📊 Habit Statistics:"]
                lines.append(f"   Total habits: {total_habits}")
                lines.append(f"   Combined streak: {total_streak} days")
                lines.append(f"   Best ever streak: {best_ever} days")
                lines.append(f"   Completions (7 days): {last_7}")
                lines.append(f"   Completions (30 days): {last_30}")
                
                # Today's progress
                today = date.today().isoformat()
                cursor.execute("""
                    SELECT COUNT(DISTINCT habit_id) as done
                    FROM habit_logs WHERE done_date = ?
                """, (today,))
                done_today = cursor.fetchone()['done']
                lines.append(f"\n   Today: {done_today}/{total_habits} complete")
                
                return ToolResult(success=True, message="\n".join(lines))
            
            # ===== HISTORY =====
            elif action == "history":
                name = params.get("name", "").strip()
                limit = params.get("limit", 10)
                
                if name:
                    cursor.execute("SELECT id, name FROM habits WHERE LOWER(name) LIKE ?", (f"%{name.lower()}%",))
                    habit = cursor.fetchone()
                    if not habit:
                        return ToolResult(success=False, message=f"Habit '{name}' not found")
                    
                    cursor.execute("""
                        SELECT done_date, done_time, notes, mood
                        FROM habit_logs
                        WHERE habit_id = ?
                        ORDER BY done_date DESC
                        LIMIT ?
                    """, (habit['id'], limit))
                    
                    logs = cursor.fetchall()
                    lines = [f"📅 {habit['name']} History:"]
                    
                    for log in logs:
                        line = f"  [{log['done_date']}]"
                        if log['done_time']:
                            line += f" {log['done_time']}"
                        if log['notes']:
                            line += f" - {log['notes']}"
                        if log['mood']:
                            line += f" ({log['mood']})"
                        lines.append(line)
                    
                    return ToolResult(success=True, message="\n".join(lines))
                
                else:
                    # General history
                    cursor.execute("""
                        SELECT h.name, hl.done_date, hl.notes
                        FROM habit_logs hl
                        JOIN habits h ON hl.habit_id = h.id
                        ORDER BY hl.done_date DESC
                        LIMIT ?
                    """, (limit,))
                    
                    logs = cursor.fetchall()
                    lines = ["📅 Recent Habit Activity:"]
                    
                    for log in logs:
                        lines.append(f"  [{log['done_date']}] {log['name']}")
                    
                    return ToolResult(success=True, message="\n".join(lines))
            
            # ===== SET REMINDER =====
            elif action == "set_reminder":
                name = params.get("name", "").strip()
                time_str = params.get("time", "").strip()
                
                if not name:
                    return ToolResult(success=False, message="Habit name required")
                
                cursor.execute("SELECT id, name FROM habits WHERE LOWER(name) LIKE ?", (f"%{name.lower()}%",))
                habit = cursor.fetchone()
                
                if not habit:
                    return ToolResult(success=False, message=f"Habit '{name}' not found")
                
                cursor.execute("UPDATE habits SET reminder_time = ? WHERE id = ?", (time_str, habit['id']))
                conn.commit()
                
                if time_str:
                    return ToolResult(success=True, message=f"✓ Reminder set for {habit['name']} at {time_str}")
                else:
                    return ToolResult(success=True, message=f"✓ Reminder cleared for {habit['name']}")
            
            # ===== DELETE =====
            elif action in ["delete", "remove"]:
                name = params.get("name", "").strip()
                if not name:
                    return ToolResult(success=False, message="Habit name required")
                
                cursor.execute("SELECT id, name FROM habits WHERE LOWER(name) LIKE ?", (f"%{name.lower()}%",))
                habit = cursor.fetchone()
                
                if not habit:
                    return ToolResult(success=False, message=f"Habit '{name}' not found")
                
                cursor.execute("DELETE FROM habit_logs WHERE habit_id = ?", (habit['id'],))
                cursor.execute("DELETE FROM habits WHERE id = ?", (habit['id'],))
                conn.commit()
                
                return ToolResult(success=True, message=f"✓ Deleted habit: {habit['name']}")
            
            else:
                return ToolResult(success=False, message=f"Unknown action: {action}")
        
        except Exception as e:
            return ToolResult(success=False, message=f"Error: {e}")
        finally:
            conn.close()
