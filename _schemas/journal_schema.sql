-- Journal Schema for TAPAN_AI
-- Daily journal entries with tags

CREATE TABLE IF NOT EXISTS journal_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_text TEXT NOT NULL,
    entry_date DATE NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    tags TEXT  -- Comma-separated tags like "gym,work,mood"
);

CREATE INDEX IF NOT EXISTS idx_journal_date ON journal_entries(entry_date);
CREATE INDEX IF NOT EXISTS idx_journal_tags ON journal_entries(tags);
