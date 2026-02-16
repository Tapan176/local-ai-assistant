-- Memory Database Schema for TAPAN_AI
-- Personal Memory and Preferences Management

-- Memories table: stores user's memories and notes
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    tags TEXT  -- Comma-separated tags for easy searching
);

-- Preferences table: stores user preferences and settings
CREATE TABLE IF NOT EXISTS preferences (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for better search performance
CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category);
CREATE INDEX IF NOT EXISTS idx_memories_timestamp ON memories(timestamp);
