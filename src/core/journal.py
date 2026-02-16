"""
Journal Manager - Daily journal entries with tags
"""
import sqlite3
import re
from pathlib import Path
from datetime import datetime, date


class JournalManager:
    """Manage daily journal entries"""
    
    def __init__(self, db_path, schema_path=None):
        self.db_path = Path(db_path)
        self.schema_path = Path(schema_path) if schema_path else None
        self._init_db()
    
    def _init_db(self):
        """Initialize database with schema"""
        if self.schema_path and self.schema_path.exists():
            with open(self.schema_path, 'r', encoding='utf-8') as f:
                schema = f.read()
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.executescript(schema)
            conn.commit()
            conn.close()
    
    def _extract_tags(self, text):
        """Extract tags from text (words starting with #)"""
        tags = re.findall(r'#(\w+)', text)
        return ','.join(tags) if tags else ''
    
    def add_entry(self, text, entry_date=None):
        """Add a journal entry
        
        Args:
            text: Journal entry text
            entry_date: Date for the entry (default: today)
        
        Returns:
            Success message
        """
        if entry_date is None:
            entry_date = date.today()
        
        # Extract tags
        tags = self._extract_tags(text)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO journal_entries (entry_text, entry_date, tags)
               VALUES (?, ?, ?)""",
            (text, entry_date, tags)
        )
        entry_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        tag_info = f" (tags: {tags})" if tags else ""
        return f"✓ Journal entry saved{tag_info}"
    
    def search_entries(self, keyword=None, tag=None, date_from=None, date_to=None):
        """Search journal entries
        
        Args:
            keyword: Text to search for
            tag: Tag to filter by
            date_from: Start date
            date_to: End date
        
        Returns:
            Formatted search results
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        query = "SELECT id, entry_text, entry_date, tags FROM journal_entries WHERE 1=1"
        params = []
        
        if keyword:
            query += " AND entry_text LIKE ?"
            params.append(f"%{keyword}%")
        
        if tag:
            query += " AND tags LIKE ?"
            params.append(f"%{tag}%")
        
        if date_from:
            query += " AND entry_date >= ?"
            params.append(date_from)
        
        if date_to:
            query += " AND entry_date <= ?"
            params.append(date_to)
        
        query += " ORDER BY entry_date DESC, created_at DESC"
        
        cursor.execute(query, params)
        entries = cursor.fetchall()
        conn.close()
        
        if not entries:
            return "\n📔 No journal entries found\n"
        
        output = f"\n📔 Found {len(entries)} journal entries:\n\n"
        
        for entry_id, text, entry_date, tags in entries:
            # Highlight keyword
            display_text = text
            if keyword:
                display_text = text.replace(
                    keyword,
                    f"**{keyword}**"
                )
            
            output += f"[{entry_date}] {display_text}\n"
            if tags:
                output += f"   Tags: {tags}\n"
            output += "\n"
        
        return output
    
    def get_recent_entries(self, limit=5):
        """Get recent journal entries
        
        Args:
            limit: Number of entries to retrieve
        
        Returns:
            List of recent entries
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """SELECT entry_text, entry_date, tags FROM journal_entries
               ORDER BY entry_date DESC, created_at DESC
               LIMIT ?""",
            (limit,)
        )
        entries = cursor.fetchall()
        conn.close()
        
        return entries
    
    def get_entries_by_date(self, target_date):
        """Get all entries for a specific date
        
        Args:
            target_date: Date to retrieve entries for
        
        Returns:
            List of entries for that date
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id, entry_text, tags FROM journal_entries
               WHERE entry_date = ?
               ORDER BY created_at""",
            (target_date,)
        )
        entries = cursor.fetchall()
        conn.close()
        
        return entries
    
    def get_stats(self):
        """Get journal statistics
        
        Returns:
            Dictionary with stats
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Total entries
        cursor.execute("SELECT COUNT(*) FROM journal_entries")
        total = cursor.fetchone()[0]
        
        # Entries this month
        cursor.execute(
            """SELECT COUNT(*) FROM journal_entries
               WHERE strftime('%Y-%m', entry_date) = strftime('%Y-%m', 'now')"""
        )
        this_month = cursor.fetchone()[0]
        
        # Most used tags
        cursor.execute(
            """SELECT tags FROM journal_entries
               WHERE tags != ''"""
        )
        all_tags = cursor.fetchall()
        conn.close()
        
        # Count tag frequency
        tag_counts = {}
        for (tags,) in all_tags:
            for tag in tags.split(','):
                tag = tag.strip()
                if tag:
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1
        
        top_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        
        return {
            'total': total,
            'this_month': this_month,
            'top_tags': top_tags
        }
