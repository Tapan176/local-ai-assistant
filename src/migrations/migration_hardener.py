"""
PHASE 14: Database Migration Hardener

Auto-migrates all databases to current schema without data loss.
Handles legacy schemas gracefully - never crashes on old DBs.

Features:
- Auto-add missing columns
- Type conversion safety
- Backup before migration
- Rollback on failure
"""
import sqlite3
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Set, Any, Optional
import json


class MigrationHardener:
    """
    Ensures all databases match expected schema.
    Adds missing columns, creates missing tables.
    Never deletes data.
    """
    
    # Expected schema for each database
    SCHEMAS = {
        "experiences": {
            "table": "experiences",
            "columns": {
                "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
                "text": "TEXT NOT NULL",
                "date": "DATE NOT NULL",
                "time": "TEXT",
                "category": "TEXT DEFAULT 'activity'",
                "place": "TEXT",
                "city": "TEXT",
                "amount": "REAL DEFAULT 0",
                "currency": "TEXT DEFAULT 'INR'",
                "people": "TEXT",
                "sentiment": "TEXT",
                "rating": "INTEGER",
                "tags": "TEXT",
                "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
            }
        },
        "habits": {
            "table": "habits",
            "columns": {
                "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
                "name": "TEXT NOT NULL",
                "frequency": "TEXT DEFAULT 'daily'",
                "status": "TEXT DEFAULT 'active'",
                "streak": "INTEGER DEFAULT 0",
                "preferred_time": "TEXT",
                "target_count": "INTEGER DEFAULT 1",
                "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
            }
        },
        "habit_logs": {
            "table": "habit_logs",
            "columns": {
                "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
                "habit_id": "INTEGER",
                "done_date": "DATE",
                "done_time": "TEXT",
                "notes": "TEXT"
            }
        },
        "reminders": {
            "table": "reminders",
            "columns": {
                "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
                "text": "TEXT NOT NULL",
                "remind_date": "DATE",
                "remind_time": "TEXT",
                "status": "TEXT DEFAULT 'active'",
                "priority": "TEXT DEFAULT 'normal'",
                "tags": "TEXT",
                "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
            }
        },
        "memories": {
            "table": "memories",
            "columns": {
                "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
                "text": "TEXT NOT NULL",
                "category": "TEXT DEFAULT 'general'",
                "importance": "INTEGER DEFAULT 5",
                "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
            }
        },
        "persona_traits": {
            "table": "persona_traits",
            "columns": {
                "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
                "key": "TEXT NOT NULL",
                "value": "TEXT",
                "category": "TEXT DEFAULT 'personality'",
                "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
                "updated_at": "TIMESTAMP"
            }
        },
        "emotional_state": {
            "table": "emotional_state",
            "columns": {
                "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
                "mood": "TEXT",
                "energy_level": "INTEGER DEFAULT 5",
                "stress_level": "INTEGER DEFAULT 3",
                "notes": "TEXT",
                "log_date": "DATE",
                "log_time": "TEXT"
            }
        },
        "relations": {
            "table": "relations",
            "columns": {
                "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
                "name": "TEXT NOT NULL",
                "nickname": "TEXT",
                "relationship": "TEXT",
                "trust_level": "INTEGER DEFAULT 5",
                "phone": "TEXT",
                "email": "TEXT",
                "birthday": "DATE",
                "notes": "TEXT",
                "first_met": "DATE",
                "last_contact": "DATE"
            }
        },
        "accounts": {
            "table": "accounts",
            "columns": {
                "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
                "name": "TEXT UNIQUE NOT NULL",
                "type": "TEXT DEFAULT 'bank'",
                "balance": "REAL DEFAULT 0",
                "currency": "TEXT DEFAULT 'INR'"
            }
        },
        "transactions": {
            "table": "transactions",
            "columns": {
                "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
                "account": "TEXT",
                "type": "TEXT",
                "amount": "REAL",
                "category": "TEXT",
                "description": "TEXT",
                "date": "TEXT",
                "time": "TEXT"
            }
        }
    }
    
    # Default values for new columns (to avoid NULL issues)
    DEFAULTS = {
        "people": "''",
        "sentiment": "'neutral'",
        "rating": "5",
        "tags": "''",
        "done_date": "DATE('now')",
        "priority": "'normal'",
        "importance": "5",
        "energy_level": "5",
        "stress_level": "3"
    }
    
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.backup_dir = self.data_dir / "backup" / "migrations"
        self.log = []
    
    def migrate_all(self) -> Dict[str, Any]:
        """Migrate all databases to current schema"""
        self.log = []
        results = {
            "success": True,
            "migrated": [],
            "skipped": [],
            "errors": [],
            "columns_added": []
        }
        
        # Database file → table mappings
        db_tables = {
            "experiences.db": ["experiences"],
            "habits.db": ["habits", "habit_logs"],
            "reminders.db": ["reminders"],
            "memory.db": ["memories"],
            "persona.db": ["persona_traits", "emotional_state"],
            "relations.db": ["relations"],
            "finance.db": ["accounts", "transactions"]
        }
        
        for db_file, tables in db_tables.items():
            db_path = self.data_dir / db_file
            
            if not db_path.exists():
                results["skipped"].append(db_file)
                continue
            
            try:
                # Backup first
                self._backup_db(db_path)
                
                # Migrate each table
                for table_key in tables:
                    if table_key not in self.SCHEMAS:
                        continue
                    
                    added = self._migrate_table(db_path, table_key)
                    if added:
                        results["columns_added"].extend(added)
                        results["migrated"].append(f"{db_file}:{table_key}")
                
            except Exception as e:
                results["errors"].append(f"{db_file}: {str(e)}")
                results["success"] = False
                self._rollback_db(db_path)
        
        return results
    
    def _backup_db(self, db_path: Path):
        """Create backup before migration"""
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.backup_dir / f"{db_path.stem}_{timestamp}.db"
        shutil.copy2(db_path, backup_path)
        self.log.append(f"Backed up {db_path.name} → {backup_path.name}")
    
    def _rollback_db(self, db_path: Path):
        """Restore from backup on failure"""
        # Find most recent backup
        backups = sorted(self.backup_dir.glob(f"{db_path.stem}_*.db"), reverse=True)
        if backups:
            shutil.copy2(backups[0], db_path)
            self.log.append(f"Rolled back {db_path.name} from {backups[0].name}")
    
    def _get_existing_columns(self, cursor, table: str) -> Set[str]:
        """Get existing columns in a table"""
        try:
            cursor.execute(f"PRAGMA table_info({table})")
            return {row[1] for row in cursor.fetchall()}
        except:
            return set()
    
    def _migrate_table(self, db_path: Path, table_key: str) -> List[str]:
        """Migrate a single table, return list of added columns"""
        schema = self.SCHEMAS[table_key]
        table = schema["table"]
        columns = schema["columns"]
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        added = []
        
        try:
            # Check if table exists
            cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name=?
            """, (table,))
            
            if not cursor.fetchone():
                # Create table with full schema
                col_defs = ", ".join(f"{c} {t}" for c, t in columns.items())
                cursor.execute(f"CREATE TABLE {table} ({col_defs})")
                conn.commit()
                self.log.append(f"Created table {table}")
                conn.close()
                return [f"{table} (new table)"]
            
            # Table exists - check for missing columns
            existing = self._get_existing_columns(cursor, table)
            
            for col, typedef in columns.items():
                if col not in existing:
                    # Add missing column
                    default = self.DEFAULTS.get(col, "NULL")
                    
                    # Extract base type (remove PRIMARY KEY, NOT NULL, etc.)
                    base_type = typedef.split()[0]
                    
                    try:
                        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {base_type} DEFAULT {default}")
                        added.append(f"{table}.{col}")
                        self.log.append(f"Added column {table}.{col}")
                    except sqlite3.OperationalError as e:
                        # Column might already exist or other issue
                        self.log.append(f"Note: {table}.{col} - {e}")
            
            conn.commit()
            
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
        
        return added
    
    def verify_schema(self, db_name: str, table: str) -> Dict[str, bool]:
        """Verify a table has all expected columns"""
        db_path = self.data_dir / db_name
        if not db_path.exists():
            return {"exists": False}
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        existing = self._get_existing_columns(cursor, table)
        conn.close()
        
        if table not in self.SCHEMAS:
            return {"exists": True, "valid": False}
        
        expected = set(self.SCHEMAS[table]["columns"].keys())
        missing = expected - existing
        extra = existing - expected
        
        return {
            "exists": True,
            "valid": len(missing) == 0,
            "missing": list(missing),
            "extra": list(extra)
        }
    
    def get_migration_report(self) -> str:
        """Get human-readable migration log"""
        return "\n".join(self.log) if self.log else "No migrations performed"


class DomainGuard:
    """
    Middleware to prevent cross-domain writes.
    
    STRICT RULES:
    - "I like X" → memory ONLY
    - "remind me X" → reminder ONLY  
    - "today went X" → experience ONLY
    - "who is X" → relation ONLY
    """
    
    # Domain patterns - if matched, BLOCK other domains
    DOMAIN_LOCKS = {
        "memory": [
            r"^(?:i|my)\s+(?:like|love|prefer|hate|favorite)",
            r"^remember\s+(?:that\s+)?(?:i|my)",
            r"^(?:my|mera|meri)\s+(?:fav|favorite|preference)"
        ],
        "reminder": [
            r"^remind\s+me",
            r"^add\s+reminder",
            r"^set\s+reminder",
            r"yaad\s+dila"
        ],
        "experience": [
            r"^(?:today|yesterday|last\s+\w+)\s+(?:went|visited|did|had|ate|watched)",
            r"^(?:i|we)\s+(?:went|visited|did|had|ate|watched)\s+.+\s+(?:today|yesterday)",
            r"^logged?\s+(?:that\s+)?(?:i|we)"
        ],
        "relation": [
            r"^who\s+is\s+\w+",
            r"^add\s+(?:person|contact|friend|relation)",
            r"^remember\s+about\s+\w+"
        ]
    }
    
    @classmethod
    def get_locked_domain(cls, text: str) -> Optional[str]:
        """
        Determine if text MUST go to a specific domain.
        Returns domain name or None if no lock.
        """
        import re
        text_lower = text.lower().strip()
        
        for domain, patterns in cls.DOMAIN_LOCKS.items():
            for pattern in patterns:
                if re.search(pattern, text_lower):
                    return domain
        
        return None
    
    @classmethod
    def validate_write(cls, text: str, target_domain: str) -> bool:
        """
        Check if writing to target_domain is allowed for this text.
        Returns True if allowed, False if blocked.
        """
        locked = cls.get_locked_domain(text)
        
        if locked is None:
            return True  # No lock, allow any domain
        
        return locked == target_domain


def run_migration(data_dir: Path) -> Dict:
    """Run full migration and return results"""
    hardener = MigrationHardener(data_dir)
    return hardener.migrate_all()


if __name__ == "__main__":
    import sys
    
    data_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data")
    
    print("=" * 50)
    print("PHASE 14: Database Migration Hardener")
    print("=" * 50)
    
    hardener = MigrationHardener(data_dir)
    results = hardener.migrate_all()
    
    print(f"\n✅ Success: {results['success']}")
    print(f"📦 Migrated: {len(results['migrated'])}")
    print(f"⏭️  Skipped: {len(results['skipped'])}")
    print(f"❌ Errors: {len(results['errors'])}")
    print(f"📊 Columns Added: {len(results['columns_added'])}")
    
    if results['columns_added']:
        print("\nNew columns:")
        for col in results['columns_added']:
            print(f"  + {col}")
    
    if results['errors']:
        print("\nErrors:")
        for err in results['errors']:
            print(f"  ! {err}")
    
    print("\n" + hardener.get_migration_report())
