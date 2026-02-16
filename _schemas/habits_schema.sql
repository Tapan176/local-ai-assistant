-- Habits Schema for TAPAN_AI
-- Track daily habits

CREATE TABLE IF NOT EXISTS habits (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  description TEXT,
  frequency TEXT DEFAULT 'daily',  -- daily, weekly
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS habit_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  habit_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  log_date DATE NOT NULL,
  note TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (habit_id) REFERENCES habits(id)
);

CREATE INDEX IF NOT EXISTS idx_habit_logs_date ON habit_logs(log_date);
CREATE INDEX IF NOT EXISTS idx_habit_logs_name ON habit_logs(name);
