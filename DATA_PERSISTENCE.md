# TAPAN_AI Data Persistence & Lifelong Learning Guide

## Overview

TAPAN_AI is designed for **lifelong learning** - your companion learns from every interaction, conversation, and experience. Data persists permanently across model updates, ensuring your memory and history are never lost.

---

## Core Principle: SQLite-First Architecture

All data is stored in **SQLite databases** in the `data/` directory. These databases are:
- **ACID-compliant**: Safe from crashes and corruption
- **Portable**: Can be backed up, moved, or shared
- **Queryable**: Can be analyzed with standard SQL tools
- **Versionless**: Work across any future model updates

### Why SQLite?

1. **No vendor lock-in**: Works with any version of TAPAN_AI or compatible systems
2. **Maximum durability**: Transactions ensure data integrity
3. **Zero setup**: No external database server required
4. **Backward compatible**: Old data always readable by new versions

---

## Data Structure

### 1. Financial Data (`data/finances.db`)

Tracks all money-related information:

```
accounts TABLE:
  - id: Unique account identifier
  - name: Account name (e.g., "savings", "checking")
  - balance: Current account balance in rupees
  - type: Account type (asset/liability/investment)
  - note: Optional notes

transactions TABLE:
  - id: Unique transaction identifier
  - amount: Transaction amount in rupees
  - type: "expense" or "income"
  - category: Category (food, rent, salary, etc.)
  - account: Associated account name
  - note: Optional description
  - date: Transaction timestamp
```

**Example Query**:
```sql
SELECT SUM(amount) as total_spent
FROM transactions
WHERE type='expense' AND category='food'
AND date > date('now', '-30 days');
```

### 2. Memories (`data/memories.db`)

Stores facts, preferences, and important information:

```
memories TABLE:
  - id: Unique memory identifier
  - text: Memory content
  - category: Memory category
  - tags: Comma-separated tags for search
  - confidence: Confidence level (0-1)
  - created_at: Creation timestamp
```

**Preserved Across Sessions**:
- "I like pizza" remains accessible forever
- Can be searched and referenced in future conversations
- Forms basis for personalization

### 3. Experiences (`data/experiences.db`)

Tracks life events, activities, and journal entries:

```
experiences TABLE:
  - id: Unique experience identifier
  - text: Experience description
  - category: Activity type
  - mood: Emotional mood at time
  - date: When it happened
  - location: Where it happened (optional)
  - tags: Searchable tags
```

**Example**: "Today went to gym for 1 hour" is permanently logged and can be analyzed for habit patterns.

### 4. Reminders (`data/reminders.db`)

One-time and recurring reminders:

```
reminders TABLE:
  - id: Unique reminder identifier
  - text: Reminder content
  - due_date: When it's due
  - status: "pending" or "completed"
  - recurring: Recurring pattern (once, daily, weekly, etc.)
  - created_at: When reminder was set
```

### 5. Relationships (`data/relations.db`)

Tracks people and their relationships:

```
relations TABLE:
  - id: Unique relation identifier
  - person1: First person name
  - person2: Second person name
  - relationship_type: Relationship (friend, colleague, family, etc.)
  - context: How you know them
  - date: When relationship started
```

### 6. Knowledge Base (`data/knowledge.db`)

Stores learned facts and information:

```
facts TABLE:
  - id: Unique fact identifier
  - subject: Subject entity
  - predicate: Property/relationship
  - object: Value
  - source: How learned (conversation, input, etc.)
  - confidence: How confident (0-1)
```

### 7. User Profile (`data/profile.db`)

Personal preferences and settings:

```
profiles TABLE:
  - id: Unique profile identifier
  - name: Profile attribute name
  - value: Attribute value
  - type: Data type (string, number, boolean)
  - updated_at: Last update timestamp
```

### 8. Conversation History (`data/chat_history.db`)

**NEW**: Complete multi-turn conversation tracking with sentiment:

```
turns TABLE:
  - id: Unique turn identifier
  - timestamp: ISO 8601 timestamp
  - user_input: What you said
  - assistant_response: What companion said
  - intent: Detected intent
  - entities: Extracted parameters (JSON)
  - source: "voice" or "text"
  - topic: Conversation topic
  - sentiment_valence: Emotional valence (-1.0 to 1.0)
  - sentiment_arousal: Emotional intensity (0.0 to 1.0)
  - sentiment_label: Emotion label (happy, sad, angry, etc.)
```

**Importance**: This is the companion's "memory" of interactions. Every conversation is logged, enabling:
- Multi-turn context understanding
- Sentiment-based proactive responses
- Historical analysis of your emotional state
- Continuous learning from your feedback

---

## Data Persistence Guarantees

### ✅ Permanent Storage
```
Data persists until YOU explicitly delete it.
This includes:
  - All financial transactions
  - All memories and experiences
  - All conversations
  - All relationships
  - All reminders
```

### ✅ Model Update Immunity
```
If TAPAN_AI model is updated, upgraded, or changed:
  - All SQLite data remains intact
  - No data loss or reset
  - New model automatically learns from old data
  - Conversations continue seamlessly
```

### ✅ Cross-Session Persistence
```
Between sessions:
  - Returns to same state (memories, accounts, reminders)
  - Continues conversations seamlessly
  - Learns from previous interactions
  - Maintains all relationships and preferences
```

---

## Backup & Recovery

### Automatic Daily Backups

Located in `data/backups/`:

```
data/backups/
  ├── 2024-02-17/
  │   ├── memories.db.backup
  │   ├── finances.db.backup
  │   ├── chat_history.db.backup
  │   └── ...all other DBs
  ├── 2024-02-16/
  │   └── ...
```

**Retention**: Last 30 days of daily backups retained automatically.

### Manual Backup

```bash
# Copy entire data directory
cp -r data/ data_backup_$(date +%Y%m%d)

# Or export as JSON for portable analysis
python export_conversations.py
```

### Recovery from Backup

```bash
# Restore from backup
cp data_backup_20240217/* data/

# Or restore specific database
cp data_backup_20240217/finances.db data/
```

---

## Data Export & Analysis

### Export Conversations to JSON

```python
import sqlite3
import json

conn = sqlite3.connect("data/chat_history.db")
cursor = conn.cursor()
cursor.execute("SELECT * FROM turns")
turns = cursor.fetchall()

with open("conversations.json", "w") as f:
    json.dump(turns, f, indent=2)
```

### Export Finances to CSV

```python
import sqlite3
import csv

conn = sqlite3.connect("data/finances.db")
cursor = conn.cursor()

# Export transactions
cursor.execute("SELECT * FROM transactions")
rows = cursor.fetchall()

with open("transactions.csv", "w", newline='') as f:
    writer = csv.writer(f)
    writer.writerow(["ID", "Amount", "Type", "Category", "Account", "Note", "Date"])
    writer.writerows(rows)
```

### Analyze Sentiment Trends

```python
import sqlite3
import pandas as pd

conn = sqlite3.connect("data/chat_history.db")
df = pd.read_sql_query("SELECT timestamp, sentiment_label, sentiment_valence FROM turns", conn)

# Sentiment over time
print(df.groupby(pd.Grouper(key='timestamp', freq='D'))['sentiment_valence'].mean())
```

---

## Migration Guide: Updating TAPAN_AI

### Scenario: Model Version Update

**Old**: TAPAN_AI v0.1
**New**: TAPAN_AI v0.2

**Process**:
1. Backup `data/` directory (automatic)
2. Update application code
3. Run new version: `python start_agent.py`
4. All existing data automatically accessible

✅ **Result**: Zero data loss, seamless migration

### Scenario: Switching Models (Ollama → Other)

Even if switching to a different LLM system:

```bash
# Export all data from TAPAN_AI
python export_all_data.py
# Returns: data_export_20240217.json

# Import into new system
# (Any compatible system can read SQLite files)
```

---

## Data Safety Best Practices

### ✅ DO:
- ✅ Backup `data/` directory monthly
- ✅ Monitor `data/` size (grows ~1MB per 10k conversations)
- ✅ Export conversations as JSON periodically
- ✅ Keep `data/` on reliable storage
- ✅ Review memories periodically (delete irrelevant ones)

### ❌ DON'T:
- ❌ Delete `data/` directory (unless intentional factory reset)
- ❌ Move `.db` files individually (they may have dependencies)
- ❌ Open `.db` files while application is running
- ❌ Assume cloud backup happens (it doesn't, you must backup)

---

## Data Privacy

### Local Storage Only
```
All data stored locally in data/ directory
  ✅ No cloud upload
  ✅ No external servers
  ✅ Complete privacy
  ✅ You own all your data
```

### Clear Before Sharing Device
```bash
# Completely wipe all data
rm -rf data/

# Or selectively delete sensitive data
rm data/finances.db
rm data/chat_history.db
```

---

## Troubleshooting Data Issues

### Issue: Chat history not appearing

**Check**:
```bash
# Verify DB exists and has tables
sqlite3 data/chat_history.db ".tables"

# Count turns
sqlite3 data/chat_history.db "SELECT COUNT(*) FROM turns;"
```

**Fix**:
- Restart application: `python start_agent.py`
- ConversationManager will auto-load recent turns on startup

### Issue: Memory/experience not being recalled

**Check**:
```bash
# List all memories
sqlite3 data/memories.db "SELECT id, text FROM memories LIMIT 10;"

# Search for specific text
sqlite3 data/memories.db "SELECT * FROM memories WHERE text LIKE '%pizza%';"
```

### Issue: Database is corrupted

**Recovery**:
```bash
# Use latest backup
cp data_backup_20240217/memories.db data/

# If no backup, SQLite can usually recover most data
sqlite3 data/memories.db "PRAGMA integrity_check;"
```

---

## Data Size Management

### Typical Growth
```
1,000 conversations  ≈ 100 KB
10,000 conversations ≈ 1 MB
100,000 conversations ≈ 10 MB
```

### Archive Old Data
```python
import sqlite3
from datetime import datetime, timedelta

conn = sqlite3.connect("data/chat_history.db")
cursor = conn.cursor()

# Archive conversations older than 1 year
one_year_ago = (datetime.now() - timedelta(days=365)).isoformat()

cursor.execute("SELECT * FROM turns WHERE timestamp < ?", (one_year_ago,))
old_turns = cursor.fetchall()

# Export to archive
import json
with open(f"archive_{one_year_ago[:4]}.json", "w") as f:
    json.dump(old_turns, f)

# Delete old turns
cursor.execute("DELETE FROM turns WHERE timestamp < ?", (one_year_ago,))
conn.commit()
```

---

## Future Updates

### Planned Enhancements
- [ ] Cloud backup option (optional)
- [ ] Encrypted local storage
- [ ] Data compression for archival
- [ ] Analytics dashboard for sentiment trends
- [ ] Graph database for relationship visualization
- [ ] Full-text search across all conversations

### Backward Compatibility
All future updates will maintain compatibility with current SQLite structure. New features will add new fields/tables, never breaking old ones.

---

## Summary

**TAPAN_AI guarantees**:
- ✅ Your data lives forever (until you delete it)
- ✅ Model updates never erase your history
- ✅ Conversations are fully recoverable
- ✅ Complete local privacy
- ✅ Portable data (can export anytime)

**You're in control** of:
- Where data is stored (`data/` directory)
- What data is kept (can delete anytime)
- When backups happen (automatic daily)
- How data is used (only locally)

---

**Last Updated**: February 2024
**Version**: TAPAN_AI v0.1+
**Status**: ✅ Production-Ready

