"""
BaseRepository - Universal SQLite Operations
Implements the mandatory "Universal Operation Set" for all TAPAN_AI tools.
"""
import sqlite3
import csv
import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union, TypeVar, Generic
from datetime import datetime

T = TypeVar('T', bound=Dict[str, Any])

class BaseRepository(Generic[T]):
    """
    Universal SQLite Repository implementing full CRUD + Safety + Text Ops.
    All domain repositories MUST inherit from this.
    """
    
    def __init__(self, db_path: Path, table_name: str, schema: str = ""):
        self.db_path = Path(db_path)
        self.table_name = table_name
        self._ensure_db()
        if schema:
            self._init_table(schema)

    def _ensure_db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_table(self, schema: str):
        with self._get_connection() as conn:
            # Ensure table exists
            conn.execute(schema)
            # Ensure standard columns if not present (id is auto)
            # We assume schema handles creation. 
            pass

    # =========================================================================
    # A. CORE CRUD
    # =========================================================================

    def create(self, record: Dict[str, Any]) -> int:
        """Create a single record. Returns ID."""
        columns = list(record.keys())
        placeholders = ", ".join(["?"] * len(columns))
        sql = f"INSERT INTO {self.table_name} ({', '.join(columns)}) VALUES ({placeholders})"
        values = list(record.values())
        
        with self._get_connection() as conn:
            cursor = conn.execute(sql, values)
            conn.commit()
            return cursor.lastrowid

    def read(self, id: int) -> Optional[Dict[str, Any]]:
        """Read a single record by ID."""
        with self._get_connection() as conn:
            cursor = conn.execute(f"SELECT * FROM {self.table_name} WHERE id = ?", (id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def list(self, filters: Dict[str, Any] = None, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """List records with optional exact match filters."""
        sql = f"SELECT * FROM {self.table_name}"
        params = []
        
        if filters:
            conditions = []
            for k, v in filters.items():
                conditions.append(f"{k} = ?")
                params.append(v)
            sql += " WHERE " + " AND ".join(conditions)
        
        sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        with self._get_connection() as conn:
            cursor = conn.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]

    def update(self, id: int, fields: Dict[str, Any]) -> bool:
        """Update specific fields of a record by ID."""
        if not fields:
            return False
            
        set_clauses = [f"{k} = ?" for k in fields.keys()]
        values = list(fields.values())
        values.append(id)
        
        sql = f"UPDATE {self.table_name} SET {', '.join(set_clauses)} WHERE id = ?"
        
        with self._get_connection() as conn:
            cursor = conn.execute(sql, values)
            conn.commit()
            return cursor.rowcount > 0

    def delete(self, id: int) -> bool:
        """Delete a record by ID."""
        with self._get_connection() as conn:
            cursor = conn.execute(f"DELETE FROM {self.table_name} WHERE id = ?", (id,))
            conn.commit()
            return cursor.rowcount > 0

    # =========================================================================
    # B. TEXT BASED OPS
    # =========================================================================

    def search_by_text(self, text: str, columns: List[str] = None) -> List[Dict[str, Any]]:
        """Search for text LIKE %text% in specified columns."""
        if not columns:
            # Try to infer text columns or use default if known, otherwise need explicit cols
            # For robustness, we'll try to get all columns and search text ones
            with self._get_connection() as conn:
                cursor = conn.execute(f"PRAGMA table_info({self.table_name})")
                all_cols = [row['name'] for row in cursor.fetchall()]
                # Heuristic: search all columns
                columns = all_cols

        conditions = []
        params = []
        for col in columns:
            conditions.append(f"{col} LIKE ?")
            params.append(f"%{text}%")
        
        if not conditions:
            return []
            
        sql = f"SELECT * FROM {self.table_name} WHERE " + " OR ".join(conditions)
        sql += " ORDER BY id DESC LIMIT 20"
        
        with self._get_connection() as conn:
            cursor = conn.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]

    def delete_by_text(self, text: str, column: str = "text") -> int:
        """Delete records where column matches text exactly or contains it."""
        # This is destructive, so we should be careful. 
        # Requirement says "delete_by_text", usually implies strict or loose match.
        # We will assume LIKE match for broad power, but tooling might restrict.
        
        sql = f"DELETE FROM {self.table_name} WHERE {column} LIKE ?"
        
        with self._get_connection() as conn:
            cursor = conn.execute(sql, (f"%{text}%",))
            conn.commit()
            return cursor.rowcount

    def update_by_text(self, search_text: str, updates: Dict[str, Any], search_column: str = "text") -> int:
        """Update records matching text search."""
        if not updates:
            return 0
            
        set_clauses = [f"{k} = ?" for k in updates.keys()]
        values = list(updates.values())
        values.append(f"%{search_text}%")
        
        sql = f"UPDATE {self.table_name} SET {', '.join(set_clauses)} WHERE {search_column} LIKE ?"
        
        with self._get_connection() as conn:
            cursor = conn.execute(sql, values)
            conn.commit()
            return cursor.rowcount

    # =========================================================================
    # C. BULK OPS
    # =========================================================================

    def bulk_create(self, records: List[Dict[str, Any]]) -> int:
        """Create multiple records in one transaction."""
        if not records:
            return 0
        
        columns = list(records[0].keys())
        placeholders = ", ".join(["?"] * len(columns))
        sql = f"INSERT INTO {self.table_name} ({', '.join(columns)}) VALUES ({placeholders})"
        
        data = []
        for r in records:
            # Ensure order matches columns
            data.append([r.get(c) for c in columns])
            
        with self._get_connection() as conn:
            cursor = conn.executemany(sql, data)
            conn.commit()
            return cursor.rowcount

    def bulk_delete(self, ids: List[int]) -> int:
        """Delete multiple records by ID."""
        if not ids:
            return 0
            
        placeholders = ", ".join(["?"] * len(ids))
        sql = f"DELETE FROM {self.table_name} WHERE id IN ({placeholders})"
        
        with self._get_connection() as conn:
            cursor = conn.execute(sql, ids)
            conn.commit()
            return cursor.rowcount

    def delete_all(self) -> int:
        """Clear the entire table."""
        with self._get_connection() as conn:
            cursor = conn.execute(f"DELETE FROM {self.table_name}")
            conn.commit()
            return cursor.rowcount

    def export_csv(self, file_path: str) -> bool:
        """Export table to CSV."""
        rows = self.list(limit=1000000)
        if not rows:
            return False
            
        try:
            with open(file_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)
            return True
        except Exception:
            return False

    def import_csv(self, file_path: str, replace: bool = False) -> int:
        """Import from CSV."""
        if replace:
            self.delete_all()
            
        count = 0
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                records = [row for row in reader]
                count = self.bulk_create(records)
        except Exception:
            pass
        return count

    # =========================================================================
    # D. ROW MANAGEMENT
    # =========================================================================

    def rename_field(self, old_name: str, new_name: str) -> bool:
        """Rename a column (SQLite requires table recreation or ALTER based on version)."""
        # SQLite 3.25+ supports RENAME COLUMN
        try:
            with self._get_connection() as conn:
                conn.execute(f"ALTER TABLE {self.table_name} RENAME COLUMN {old_name} TO {new_name}")
                conn.commit()
            return True
        except Exception:
            return False

    def merge_duplicates(self, match_column: str, keep: str = "newest") -> int:
        """Merge duplicates based on a column value."""
        # Simplified strategy: remove older/newer duplicates keeping one.
        # Does not merge data content, just deduplicates rows.
        
        sql = f"""
        DELETE FROM {self.table_name}
        WHERE id NOT IN (
            SELECT { 'MAX(id)' if keep == 'newest' else 'MIN(id)' }
            FROM {self.table_name}
            GROUP BY {match_column}
        )
        """
        with self._get_connection() as conn:
            cursor = conn.execute(sql)
            conn.commit()
            return cursor.rowcount

    # =========================================================================
    # E. SAFETY OPS
    # =========================================================================

    def backup_table(self, backup_dir: Path) -> str:
        """Backup simple table dump to JSON or CSV."""
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = backup_dir / f"{self.table_name}_backup_{timestamp}.json"
        
        rows = self.list(limit=1000000)
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(rows, f, default=str, indent=2)
            
        return str(filename)

    def restore_table(self, backup_file: str) -> bool:
        """Restore from JSON backup (wipes current data)."""
        try:
            with open(backup_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self.delete_all()
            self.bulk_create(data)
            return True
        except Exception:
            return False
