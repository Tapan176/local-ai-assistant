-- Reminders Schema for TAPAN_AI
-- Track reminders and tasks

CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    remind_at DATETIME NOT NULL,
    recurring TEXT,  -- NULL, 'daily', 'weekly', 'monthly'
    status TEXT DEFAULT 'pending',  -- 'pending', 'done', 'cancelled'
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME
);

CREATE INDEX IF NOT EXISTS idx_remind_at ON reminders(remind_at);
CREATE INDEX IF NOT EXISTS idx_status ON reminders(status);
