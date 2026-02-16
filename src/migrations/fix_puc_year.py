"""
Migration Script - Fix PUC Year
Fixes "next year" reminders that were incorrectly calculated as 2026 instead of 2027
"""
import sqlite3
import datetime
from pathlib import Path

def migrate_puc_reminders(data_dir: Path):
    db_path = data_dir / "reminders.db"
    if not db_path.exists():
        print("No reminders DB found.")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Find reminders with "PUC" in text and date in 2026
        cursor.execute("SELECT id, text, remind_at FROM reminders WHERE text LIKE '%PUC%' AND remind_at LIKE '2026%'")
        rows = cursor.fetchall()
        
        if not rows:
            print("No incorrect PUC reminders found.")
            return

        print(f"Found {len(rows)} PUC reminders to fix...")
        
        for rid, text, date_str in rows:
            # Move to 2027
            old_date = datetime.datetime.fromisoformat(date_str)
            new_date = old_date.replace(year=2027)
            
            cursor.execute("UPDATE reminders SET remind_at = ? WHERE id = ?", (new_date, rid))
            print(f"  Fixed #{rid}: {text} -> {new_date}")
            
        conn.commit()
        print("Migration complete.")
        
    except Exception as e:
        print(f"Migration error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    # Default to project data dir
    migrate_puc_reminders(Path("D:/practice/J/data"))
