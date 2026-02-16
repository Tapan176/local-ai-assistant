import sqlite3
from pathlib import Path
import re

class MemoryManager:
    def __init__(self, db_path, schema_path=None):
        self.db_path = Path(db_path)
        self.schema_path = Path(schema_path) if schema_path else None
        self._init_db()
    
    def _init_db(self):
        """Initialize database with schema if needed"""
        if self.schema_path and self.schema_path.exists():
            with open(self.schema_path, 'r', encoding='utf-8') as f:
                schema = f.read()
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.executescript(schema)
            conn.commit()
            conn.close()

    def remember(self, text, category='general', tags=''):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO memories (text, category, tags) VALUES (?, ?, ?)",
            (text, category, tags)
        )
        conn.commit()
        memory_id = cursor.lastrowid
        conn.close()
        return f"✓ Remembered: {text} (ID: {memory_id})"

    def search_memory(self, keyword):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id, text, category, timestamp 
                   FROM memories 
                   WHERE text LIKE ? OR category LIKE ? OR tags LIKE ?
                   ORDER BY timestamp DESC""",
            (f'%{keyword}%', f'%{keyword}%', f'%{keyword}%')
        )
        results = cursor.fetchall()
        conn.close()
        if results:
            output = f"\n🔍 Found {len(results)} memories matching '{keyword}':\n\n"
            for memory_id, text, category, timestamp in results:
                highlighted_text = re.sub(
                    f'({re.escape(keyword)})',
                    r'**\1**',
                    text,
                    flags=re.IGNORECASE
                )
                date_str = timestamp[:10]
                time_str = timestamp[11:16]
                output += f"[{memory_id}] {highlighted_text}\n"
                output += f"    📁 {category} | 📅 {date_str} {time_str}\n\n"
            return output
        else:
            return f"❌ No memories found for '{keyword}'"

    def delete_memory(self, memory_id: int) -> str:
        """Delete specific memory by ID"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        rows = cursor.rowcount
        conn.commit()
        conn.close()
        return f"✓ Deleted memory {memory_id}" if rows > 0 else f"❌ Memory {memory_id} not found"

    def delete_memory_by_text(self, text: str) -> str:
        """Delete memories matching text pattern"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # First check what we're deleting
        cursor.execute("SELECT id, text FROM memories WHERE text LIKE ?", (f"%{text}%",))
        results = cursor.fetchall()
        
        if not results:
            conn.close()
            return f"❌ No memories found matching '{text}'"
        
        # If too many matches, ask for specific ID (simulated by returning list)
        if len(results) > 1:
            conn.close()
            output = f"⚠️ Found {len(results)} matches for delete. Please use ID:\n"
            for mid, mtext in results:
                output += f"[{mid}] {mtext[:50]}...\n"
            return output
            
        # Delete the single match
        mid = results[0][0]
        cursor.execute("DELETE FROM memories WHERE id = ?", (mid,))
        conn.commit()
        conn.close()
        return f"✓ Deleted memory [{mid}]: {results[0][1][:50]}..."

