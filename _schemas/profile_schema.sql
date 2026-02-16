-- Profile table for storing user preferences and settings
CREATE TABLE IF NOT EXISTS profile (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Default profile values
INSERT OR IGNORE INTO profile (key, value, category) VALUES 
    ('risk_level', 'moderate', 'finance'),
    ('daily_routine', 'balanced', 'lifestyle'),
    ('wake_time', '07:00', 'routine'),
    ('sleep_time', '23:00', 'routine'),
    ('work_start', '09:00', 'routine'),
    ('work_end', '18:00', 'routine'),
    ('language_preference', 'hinglish', 'general'),
    ('currency', 'INR', 'finance');
