"""
Scheduler Service - Background reminder monitoring with desktop popups
Runs every 60 seconds to check for due reminders and habits.
"""
import threading
import time
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Callable, List, Dict
import queue

# Try to import notification libraries
try:
    from plyer import notification
    HAS_PLYER = True
except ImportError:
    HAS_PLYER = False

try:
    import win10toast
    HAS_WIN10TOAST = True
except ImportError:
    HAS_WIN10TOAST = False


class SchedulerService:
    """
    Background scheduler for:
    - Reminder checking and popups
    - Habit reminders
    - Recurring tasks
    """
    
    def __init__(self, data_dir: Path, check_interval: int = 60):
        self.data_dir = Path(data_dir)
        self.check_interval = check_interval  # seconds
        self.running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        # Callbacks
        self.on_reminder_due: Optional[Callable[[Dict], None]] = None
        self.on_habit_due: Optional[Callable[[Dict], None]] = None
        
        # Queue for pending notifications
        self.notification_queue = queue.Queue()
        
        # Track fired reminders to avoid duplicates
        self._fired_reminders: set = set()
        
        # Toaster for Windows notifications
        self._toaster = None
        if HAS_WIN10TOAST:
            try:
                self._toaster = win10toast.ToastNotifier()
            except Exception:
                pass
    
    def start(self):
        """Start the background scheduler"""
        if self.running:
            return
        
        self.running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        print(f"⏰ Scheduler started (checking every {self.check_interval}s)")
    
    def stop(self):
        """Stop the background scheduler"""
        self.running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        print("⏰ Scheduler stopped")
    
    def _run_loop(self):
        """Main scheduler loop"""
        while not self._stop_event.is_set():
            try:
                self._check_reminders()
                self._check_habits()
                self._process_notifications()
            except Exception as e:
                print(f"⚠️ Scheduler error: {e}")
            
            # Wait for interval or stop event
            self._stop_event.wait(timeout=self.check_interval)
    
    def _check_reminders(self):
        """Check for due reminders"""
        db_path = self.data_dir / "reminders.db"
        if not db_path.exists():
            return
        
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        now = datetime.now()
        
        # Get pending reminders that are due
        cursor.execute("""
            SELECT id, text, remind_at 
            FROM reminders 
            WHERE status = 'pending' AND remind_at <= ?
        """, (now,))
        
        for row in cursor.fetchall():
            reminder_id = row['id']
            
            # Skip if already fired this session
            if reminder_id in self._fired_reminders:
                continue
            
            reminder = {
                'id': reminder_id,
                'text': row['text'],
                'remind_at': row['remind_at'],
                'type': 'reminder'
            }
            
            # Queue notification
            self.notification_queue.put(reminder)
            self._fired_reminders.add(reminder_id)
            
            # Call callback if set
            if self.on_reminder_due:
                self.on_reminder_due(reminder)
            
            # Mark as fired in DB
            cursor.execute("UPDATE reminders SET status = 'fired' WHERE id = ?", (reminder_id,))
        
        conn.commit()
        conn.close()
    
    def _check_habits(self):
        """Check for habits that need reminding"""
        db_path = self.data_dir / "habits.db"
        if not db_path.exists():
            return
        
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        today = datetime.now().date().isoformat()
        now_time = datetime.now().strftime("%H:%M")
        
        # Get habits with reminder times that haven't been done today
        cursor.execute("""
            SELECT h.id, h.name, h.reminder_time, h.frequency
            FROM habits h
            WHERE h.status = 'active'
            AND h.reminder_time IS NOT NULL
            AND h.reminder_time <= ?
            AND NOT EXISTS (
                SELECT 1 FROM habit_logs hl 
                WHERE hl.habit_id = h.id AND hl.done_date = ?
            )
        """, (now_time, today))
        
        for row in cursor.fetchall():
            habit_key = f"habit_{row['id']}_{today}"
            
            if habit_key in self._fired_reminders:
                continue
            
            habit = {
                'id': row['id'],
                'name': row['name'],
                'reminder_time': row['reminder_time'],
                'type': 'habit'
            }
            
            self.notification_queue.put(habit)
            self._fired_reminders.add(habit_key)
            
            if self.on_habit_due:
                self.on_habit_due(habit)
        
        conn.close()
    
    def _process_notifications(self):
        """Process queued notifications"""
        while not self.notification_queue.empty():
            try:
                item = self.notification_queue.get_nowait()
                self._show_notification(item)
            except queue.Empty:
                break
    
    def _show_notification(self, item: Dict):
        """Show desktop notification"""
        title = "⏰ TAPAN Reminder" if item['type'] == 'reminder' else "💪 Habit Reminder"
        message = item.get('text') or item.get('name', 'Time for action!')
        
        # Try different notification methods
        if self._show_plyer_notification(title, message):
            return
        if self._show_win10toast_notification(title, message):
            return
        
        # Fallback to console
        print(f"\n{'='*50}")
        print(f"🔔 {title}")
        print(f"   {message}")
        print(f"{'='*50}\n")
    
    def _show_plyer_notification(self, title: str, message: str) -> bool:
        """Show notification using plyer"""
        if not HAS_PLYER:
            return False
        try:
            notification.notify(
                title=title,
                message=message,
                app_name="TAPAN_AI",
                timeout=10
            )
            return True
        except Exception:
            return False
    
    def _show_win10toast_notification(self, title: str, message: str) -> bool:
        """Show Windows 10 toast notification"""
        if not self._toaster:
            return False
        try:
            self._toaster.show_toast(
                title,
                message,
                duration=5,
                threaded=True
            )
            return True
        except Exception:
            return False
    
    def trigger_now(self, text: str):
        """Manually trigger a notification"""
        self.notification_queue.put({
            'type': 'manual',
            'text': text
        })
        self._process_notifications()
    
    def get_pending_count(self) -> Dict[str, int]:
        """Get count of pending items"""
        result = {'reminders': 0, 'habits': 0}
        
        # Count reminders
        reminder_db = self.data_dir / "reminders.db"
        if reminder_db.exists():
            conn = sqlite3.connect(reminder_db)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM reminders WHERE status = 'pending'")
            result['reminders'] = cursor.fetchone()[0]
            conn.close()
        
        # Count habits not done today
        habit_db = self.data_dir / "habits.db"
        if habit_db.exists():
            today = datetime.now().date().isoformat()
            conn = sqlite3.connect(habit_db)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM habits h
                WHERE h.status = 'active'
                AND NOT EXISTS (
                    SELECT 1 FROM habit_logs hl 
                    WHERE hl.habit_id = h.id AND hl.done_date = ?
                )
            """, (today,))
            result['habits'] = cursor.fetchone()[0]
            conn.close()
        
        return result
    
    def is_running(self) -> bool:
        return self.running


# Global scheduler instance
_scheduler: Optional[SchedulerService] = None


def get_scheduler(data_dir: Path = None) -> SchedulerService:
    """Get or create global scheduler instance"""
    global _scheduler
    if _scheduler is None:
        _scheduler = SchedulerService(data_dir or Path("data"))
    return _scheduler


def start_scheduler(data_dir: Path = None):
    """Start the global scheduler"""
    scheduler = get_scheduler(data_dir)
    scheduler.start()
    return scheduler


def stop_scheduler():
    """Stop the global scheduler"""
    global _scheduler
    if _scheduler:
        _scheduler.stop()
