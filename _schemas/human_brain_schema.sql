-- ==================================================
-- TAPAN_AI HUMAN BRAIN MODEL - UNIFIED SCHEMA
-- Philosophy: Model a HUMAN, not commands
-- No limits on tables/storage/context
-- ==================================================

-- ==================================================
-- A) PERSONA - Self-identity
-- ==================================================
CREATE TABLE IF NOT EXISTS persona_traits (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    category TEXT DEFAULT 'personality',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS persona_values (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    value TEXT NOT NULL UNIQUE,
    importance INTEGER DEFAULT 5,  -- 1-10
    reason TEXT
);

CREATE TABLE IF NOT EXISTS persona_goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal TEXT NOT NULL,
    status TEXT DEFAULT 'active',  -- active, achieved, abandoned
    deadline DATE,
    progress INTEGER DEFAULT 0,  -- 0-100
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS persona_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    situation TEXT NOT NULL,
    decision TEXT NOT NULL,
    outcome TEXT,
    lesson TEXT,
    decision_date DATE DEFAULT CURRENT_DATE
);

-- ==================================================
-- B) RELATIONS - People graph
-- ==================================================
CREATE TABLE IF NOT EXISTS relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    nickname TEXT,
    relationship TEXT DEFAULT 'acquaintance',
    -- Relationship types: family, friend, colleague, mentor, acquaintance, professional
    trust_level INTEGER DEFAULT 5,  -- 1-10
    phone TEXT,
    email TEXT,
    notes TEXT,
    birthday DATE,
    first_met DATE,
    last_contact DATE,
    how_met TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id INTEGER NOT NULL,
    interaction_date DATE NOT NULL,
    type TEXT DEFAULT 'general',
    -- Types: call, meet, text, gift, event
    summary TEXT,
    sentiment TEXT,  -- positive, neutral, negative
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (person_id) REFERENCES relations(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS person_reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    remind_at TIMESTAMP,
    status TEXT DEFAULT 'pending',
    FOREIGN KEY (person_id) REFERENCES relations(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS shared_memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id INTEGER NOT NULL,
    memory TEXT NOT NULL,
    memory_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (person_id) REFERENCES relations(id) ON DELETE CASCADE
);

-- ==================================================
-- C) MEMORIES (FACTS) - Static knowledge about self
-- ==================================================
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    -- Categories: preference, belief, skill, fact, medical, personal
    tags TEXT,
    source TEXT DEFAULT 'user',  -- user, inferred, imported
    confidence REAL DEFAULT 1.0,  -- 0-1
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS preferences (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    -- Categories: food, drink, color, music, movie, sport, etc.
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS beliefs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    statement TEXT NOT NULL,
    confidence INTEGER DEFAULT 5,  -- 1-10
    source TEXT,
    formed_date DATE DEFAULT CURRENT_DATE
);

CREATE TABLE IF NOT EXISTS skills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill TEXT NOT NULL UNIQUE,
    level TEXT DEFAULT 'beginner',  -- beginner, intermediate, advanced, expert
    notes TEXT,
    last_used DATE
);

-- ==================================================
-- D) EXPERIENCES (LIFE LOG) - Past events
-- ==================================================
CREATE TABLE IF NOT EXISTS experiences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    date DATE NOT NULL,
    time TIME,
    category TEXT DEFAULT 'activity',
    -- Categories: activity, meeting, purchase, travel, meal, entertainment, work, health
    place TEXT,
    city TEXT,
    amount REAL DEFAULT 0,
    currency TEXT DEFAULT 'INR',
    people TEXT,  -- Comma-separated names
    sentiment TEXT,  -- happy, sad, neutral, excited, tired
    rating INTEGER,  -- 1-5 stars
    tags TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS places_visited (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    city TEXT,
    type TEXT,  -- restaurant, mall, park, office, etc.
    first_visit DATE,
    last_visit DATE,
    visit_count INTEGER DEFAULT 1,
    total_spent REAL DEFAULT 0
);

-- ==================================================
-- E) HABITS & HEALTH
-- ==================================================
CREATE TABLE IF NOT EXISTS habits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    frequency TEXT DEFAULT 'daily',  -- daily, weekly, monthly
    target_time TIME,
    streak_current INTEGER DEFAULT 0,
    streak_best INTEGER DEFAULT 0,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS habit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    habit_id INTEGER NOT NULL,
    done_date DATE NOT NULL,
    notes TEXT,
    FOREIGN KEY (habit_id) REFERENCES habits(id) ON DELETE CASCADE,
    UNIQUE(habit_id, done_date)
);

CREATE TABLE IF NOT EXISTS health_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date DATE NOT NULL,
    type TEXT NOT NULL,  -- sleep, mood, exercise, weight, bp, sugar
    value TEXT NOT NULL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS routines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    time TIME,
    days TEXT DEFAULT 'daily',  -- daily, weekdays, weekends, or specific days
    tasks TEXT,  -- JSON array of tasks
    active INTEGER DEFAULT 1
);

-- ==================================================
-- F) FINANCE
-- ==================================================
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    type TEXT DEFAULT 'cash',  -- cash, bank, wallet, credit
    balance REAL NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    amount REAL NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('income', 'expense', 'transfer')),
    category TEXT NOT NULL,
    subcategory TEXT,
    account TEXT NOT NULL,
    to_account TEXT,  -- For transfers
    note TEXT,
    date DATE DEFAULT CURRENT_DATE,
    time TIME,
    place TEXT,
    recurring TEXT,  -- NULL, monthly, weekly
    FOREIGN KEY (account) REFERENCES accounts(name)
);

CREATE TABLE IF NOT EXISTS budgets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL UNIQUE,
    monthly_limit REAL NOT NULL,
    alert_at REAL DEFAULT 0.8,  -- Alert at 80%
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ==================================================
-- G) KNOWLEDGE VAULT
-- ==================================================
CREATE TABLE IF NOT EXISTS vault_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    filepath TEXT NOT NULL,
    filetype TEXT,  -- pdf, txt, md, doc, etc.
    size_bytes INTEGER,
    content_text TEXT,  -- Extracted text
    summary TEXT,
    tags TEXT,
    indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS vault_embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER,
    chunk_text TEXT NOT NULL,
    embedding BLOB,  -- Vector embedding
    chunk_index INTEGER,
    FOREIGN KEY (document_id) REFERENCES vault_documents(id) ON DELETE CASCADE
);

-- ==================================================
-- H) REMINDERS - Future actions
-- ==================================================
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    remind_at TIMESTAMP NOT NULL,
    original_text TEXT,  -- Raw input for reference
    recurring TEXT,  -- NULL, daily, weekly, monthly, yearly
    person_id INTEGER,  -- Optional link to relation
    status TEXT DEFAULT 'pending',  -- pending, done, snoozed, cancelled
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    FOREIGN KEY (person_id) REFERENCES relations(id)
);

-- ==================================================
-- INDEXES for fast retrieval
-- ==================================================
CREATE INDEX IF NOT EXISTS idx_exp_date ON experiences(date);
CREATE INDEX IF NOT EXISTS idx_exp_place ON experiences(place);
CREATE INDEX IF NOT EXISTS idx_exp_category ON experiences(category);
CREATE INDEX IF NOT EXISTS idx_exp_people ON experiences(people);

CREATE INDEX IF NOT EXISTS idx_mem_category ON memories(category);
CREATE INDEX IF NOT EXISTS idx_mem_tags ON memories(tags);

CREATE INDEX IF NOT EXISTS idx_rel_name ON relations(name);
CREATE INDEX IF NOT EXISTS idx_inter_person ON interactions(person_id);
CREATE INDEX IF NOT EXISTS idx_inter_date ON interactions(interaction_date);

CREATE INDEX IF NOT EXISTS idx_txn_date ON transactions(date);
CREATE INDEX IF NOT EXISTS idx_txn_category ON transactions(category);
CREATE INDEX IF NOT EXISTS idx_txn_account ON transactions(account);

CREATE INDEX IF NOT EXISTS idx_remind_at ON reminders(remind_at);
CREATE INDEX IF NOT EXISTS idx_remind_status ON reminders(status);

CREATE INDEX IF NOT EXISTS idx_health_date ON health_logs(date);
CREATE INDEX IF NOT EXISTS idx_health_type ON health_logs(type);

-- ==================================================
-- VIEWS for common queries
-- ==================================================
CREATE VIEW IF NOT EXISTS v_recent_experiences AS
SELECT * FROM experiences ORDER BY date DESC LIMIT 50;

CREATE VIEW IF NOT EXISTS v_upcoming_reminders AS
SELECT * FROM reminders 
WHERE status = 'pending' AND remind_at >= DATE('now')
ORDER BY remind_at ASC;

CREATE VIEW IF NOT EXISTS v_spending_by_place AS
SELECT place, SUM(amount) as total, COUNT(*) as visits
FROM experiences 
WHERE amount > 0 
GROUP BY place ORDER BY total DESC;

CREATE VIEW IF NOT EXISTS v_people_by_trust AS
SELECT name, relationship, trust_level 
FROM relations ORDER BY trust_level DESC;

-- ==================================================
-- DOMAIN SEPARATION RULES (Schema Comment)
-- ==================================================
-- REMINDER = future action with time → reminders table
-- MEMORY = fact about self → memories/preferences table  
-- EXPERIENCE = past event → experiences table
-- RELATION = person model → relations table
-- HABIT = recurring behavior → habits table
-- ==================================================
