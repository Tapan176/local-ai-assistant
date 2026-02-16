"""
Backup Manager - Daily backups and JSON export
"""
import json
import shutil
import sqlite3
from itertools import chain
from pathlib import Path
from datetime import datetime
from typing import Optional
from src.core.security import SecurityManager


class BackupManager:
  """Handle backups and data export"""

  def __init__(self, data_dir, backup_dir):
    self.data_dir = Path(data_dir)
    self.backup_dir = Path(backup_dir)
    self.backup_dir.mkdir(parents=True, exist_ok=True)
    self.security = SecurityManager()

  def create_backup(self, password: Optional[str] = None):
    """Create a backup of all databases

    Args:
      password: Optional password for encryption

    Returns:
      Success message with backup location
    """
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    folder_name = f"backup_{timestamp}"
    backup_folder = self.backup_dir / folder_name
    backup_folder.mkdir(parents=True, exist_ok=True)

    # List of databases to backup
    db_files = [
      'finance.db',
      'memory.db',
      'journal.db',
      'reminders.db',
      'habits.db',
      'knowledge.db',
      'profile.db'
    ]

    backed_up = []
    for db_file in db_files:
      src = self.data_dir / db_file
      if src.exists():
        dst = backup_folder / db_file
        shutil.copy2(src, dst)
        backed_up.append(db_file)

    # Also backup activity log
    log_file = self.data_dir / "activity.log"
    if log_file.exists():
      shutil.copy2(log_file, backup_folder / "activity.log")
      backed_up.append("activity.log")

    # Encrypt if password provided
    if password:
      # 1. Zip the folder
      zip_path = shutil.make_archive(
        str(self.backup_dir / folder_name),
        'zip',
        root_dir=str(backup_folder)
      )

      # 2. Encrypt the zip
      encrypted_path = self.security.encrypt_file(zip_path, password)

      # 3. Cleanup: Remove raw folder and plain zip
      shutil.rmtree(backup_folder)
      Path(zip_path).unlink()

      return f"🔒 Encrypted Backup created: {Path(encrypted_path).name}"

    return f"✓ Backup created: {backup_folder}\n  Files: {', '.join(backed_up)}"

  def export_to_json(self):
    """Export all data to a single JSON file

    Returns:
      Success message with export file location
    """
    export_data = {
      'export_date': datetime.now().isoformat(),
      'version': '2.0',
      'data': {}
    }

    # Export finance
    finance_db = self.data_dir / "finance.db"
    if finance_db.exists():
      conn = sqlite3.connect(finance_db)
      conn.row_factory = sqlite3.Row
      cursor = conn.cursor()

      cursor.execute("SELECT * FROM accounts")
      export_data['data']['accounts'] = [dict(row) for row in cursor.fetchall()]

      cursor.execute("SELECT * FROM transactions")
      export_data['data']['transactions'] = [dict(row) for row in cursor.fetchall()]
      conn.close()

    # Export memories
    memory_db = self.data_dir / "memory.db"
    if memory_db.exists():
      conn = sqlite3.connect(memory_db)
      conn.row_factory = sqlite3.Row
      cursor = conn.cursor()

      cursor.execute("SELECT * FROM memories")
      export_data['data']['memories'] = [dict(row) for row in cursor.fetchall()]
      conn.close()

    # Export journal
    journal_db = self.data_dir / "journal.db"
    if journal_db.exists():
      conn = sqlite3.connect(journal_db)
      conn.row_factory = sqlite3.Row
      cursor = conn.cursor()

      cursor.execute("SELECT * FROM journal_entries")
      export_data['data']['journal'] = [dict(row) for row in cursor.fetchall()]
      conn.close()

    # Export reminders
    reminders_db = self.data_dir / "reminders.db"
    if reminders_db.exists():
      conn = sqlite3.connect(reminders_db)
      conn.row_factory = sqlite3.Row
      cursor = conn.cursor()

      cursor.execute("SELECT * FROM reminders")
      export_data['data']['reminders'] = [dict(row) for row in cursor.fetchall()]
      conn.close()

    # Export habits
    habits_db = self.data_dir / "habits.db"
    if habits_db.exists():
      conn = sqlite3.connect(habits_db)
      conn.row_factory = sqlite3.Row
      cursor = conn.cursor()

      cursor.execute("SELECT * FROM habits")
      export_data['data']['habits'] = [dict(row) for row in cursor.fetchall()]

      cursor.execute("SELECT * FROM habit_logs")
      export_data['data']['habit_logs'] = [dict(row) for row in cursor.fetchall()]
      conn.close()

    # Save JSON
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    export_file = self.backup_dir / f"tapan_export_{timestamp}.json"

    with open(export_file, 'w', encoding='utf-8') as f:
      json.dump(export_data, f, indent=2, ensure_ascii=False, default=str)

    # Count items
    total_items = sum(
      len(items) for items in export_data['data'].values()
    )

    return f"✓ Data exported to: {export_file}\n  Total items: {total_items}"

  def list_backups(self):
    """List available backups

    Returns:
      Formatted list of backups
    """
    backups = sorted(self.backup_dir.glob("backup_*"), reverse=True)
    json_exports = sorted(self.backup_dir.glob("tapan_export_*.json"), reverse=True)

    output = "\n📦 BACKUPS\n"
    output += "-" * 50 + "\n"

    if backups:
      output += "\nFolder Backups:\n"
      for backup in backups[:5]:
        # Count files
        files = list(backup.glob("*"))
        size = sum(f.stat().st_size for f in files if f.is_file())
        output += f"  {backup.name} ({len(files)} files, {size/1024:.1f} KB)\n"

    if json_exports:
      output += "\nJSON Exports:\n"
      for export in json_exports[:5]:
        size = export.stat().st_size
        output += f"  {export.name} ({size/1024:.1f} KB)\n"

    if not backups and not json_exports:
      output += "No backups found\n"

    return output

  def cleanup_old_backups(self, keep_count=7):
    """Remove old backups, keeping the most recent ones

    Args:
      keep_count: Number of backups to keep

    Returns:
      Number of backups removed
    """
    backups = sorted(self.backup_dir.glob("backup_*"), reverse=True)

    removed = 0
    for backup in backups[keep_count:]:
      shutil.rmtree(backup)
      removed += 1

    # Also cleanup old JSON exports
    exports = sorted(self.backup_dir.glob("tapan_export_*.json"), reverse=True)
    for export in exports[keep_count:]:
      export.unlink()
      removed += 1

    return removed

  def snapshot(self):
    """Create a full snapshot (alias for create_backup + export_to_json)

    Returns:
      Success message
    """
    backup_msg = self.create_backup()
    export_msg = self.export_to_json()

    return f"📸 SNAPSHOT CREATED\n\n{backup_msg}\n\n{export_msg}"

  def restore_backup(self, backup_name: Optional[str] = None, password: Optional[str] = None):
    """Restore from a backup

    Args:
      backup_name: Name of backup folder/file
      password: Password for encrypted backups

    Returns:
      Success or error message
    """
    # Find backup to restore
    if backup_name:
      backup_path = self.backup_dir / backup_name
      if not backup_path.exists():
        return f"❌ Backup not found: {backup_name}"
    else:
      # Use most recent (folder or zip or enc)
      # Prioritize folders first, then files
      backups = sorted(
        chain(
          self.backup_dir.glob("backup_*"),
          self.backup_dir.glob("backup_*.enc"),
          self.backup_dir.glob("backup_*.zip")
        ),
        key=lambda p: p.stat().st_mtime,
        reverse=True
      )
      if not backups:
        return "❌ No backups found"
      backup_path = backups[0]

    temp_extract_dir = None
    restore_source_dir = None
    decrypted_temp = None

    try:
      # Handle Encrypted
      if backup_path.suffix == '.enc':
        if not password:
          return "❌ Password required for encrypted backup"

        decrypted_zip = self.security.decrypt_file(str(backup_path), password)
        decrypted_temp = Path(decrypted_zip)

        # Unzip to temp
        temp_extract_dir = self.backup_dir / "temp_restore"
        if temp_extract_dir.exists():
          shutil.rmtree(temp_extract_dir)

        shutil.unpack_archive(decrypted_zip, str(temp_extract_dir), 'zip')
        restore_source_dir = temp_extract_dir

      # Handle Zip
      elif backup_path.suffix == '.zip':
        temp_extract_dir = self.backup_dir / "temp_restore"
        if temp_extract_dir.exists():
          shutil.rmtree(temp_extract_dir)

        shutil.unpack_archive(str(backup_path), str(temp_extract_dir), 'zip')
        restore_source_dir = temp_extract_dir

      # Handle Folder
      elif backup_path.is_dir():
        restore_source_dir = backup_path

      else:
        return f"❌ Unknown backup format: {backup_path}"

      # Perform Restore
      db_files = list(restore_source_dir.glob("*.db"))
      if not db_files:
        return f"❌ No database files in backup"

      restored = []
      for db_file in db_files:
        dst = self.data_dir / db_file.name
        shutil.copy2(db_file, dst)
        restored.append(db_file.name)

      # Restore log
      log_file = restore_source_dir / "activity.log"
      if log_file.exists():
        shutil.copy2(log_file, self.data_dir / "activity.log")
        restored.append("activity.log")

      return f"✓ Restored from: {backup_path.name}\n  Files: {', '.join(restored)}"

    except Exception as e:
      return f"❌ Restore failed: {e}"

    finally:
      # Cleanup
      if decrypted_temp and decrypted_temp.exists():
        decrypted_temp.unlink()
      if temp_extract_dir and temp_extract_dir.exists():
        shutil.rmtree(temp_extract_dir)

