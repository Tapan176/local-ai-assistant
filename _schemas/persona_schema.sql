-- PHASE 12: Enhanced Persona & Self Model Schema
-- Transforms TAPAN_AI from life logger -> personal companion

-- ========================================
-- 1. CORE IDENTITY
-- ========================================
CREATE TABLE IF NOT EXISTS traits (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  category TEXT DEFAULT 'personality',
  confidence REAL DEFAULT 1.0,
  source TEXT DEFAULT 'user',  -- 'user', 'inferred', 'default'
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ========================================
-- 2. VALUES & BELIEFS
-- ========================================
CREATE TABLE IF NOT EXISTS personal_values (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  value TEXT NOT NULL UNIQUE,
  importance INTEGER DEFAULT 5,  -- 1-10
  reason TEXT,
  examples TEXT,  -- JSON array of situations where this applies
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ========================================
-- 3. DECISION STYLE PROFILE
-- ========================================
CREATE TABLE IF NOT EXISTS decision_profile (
  dimension TEXT PRIMARY KEY,
  score REAL DEFAULT 0.5,  -- 0.0 to 1.0
  description TEXT,
  last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Seed decision dimensions
INSERT OR IGNORE INTO decision_profile (dimension, score, description) VALUES
  ('risk_tolerance', 0.5, 'Conservative (0) vs Risk-taking (1)'),
  ('impulsive_vs_deliberate', 0.3, 'Impulsive (0) vs Deliberate (1)'),
  ('data_vs_gut', 0.6, 'Gut-feeling (0) vs Data-driven (1)'),
  ('independent_vs_social', 0.5, 'Solo decisions (0) vs Consults others (1)'),
  ('short_vs_long_term', 0.6, 'Short-term focus (0) vs Long-term planning (1)'),
  ('frugal_vs_spender', 0.4, 'Frugal (0) vs Spender (1)'),
  ('routine_vs_spontaneous', 0.5, 'Routine-lover (0) vs Spontaneous (1)');

-- ========================================
-- 4. COMMUNICATION STYLE
-- ========================================
CREATE TABLE IF NOT EXISTS communication_style (
  context TEXT PRIMARY KEY,
  tone TEXT DEFAULT 'friendly',
  language_mix TEXT DEFAULT 'hinglish_70_30',  -- hinglish_70_30, english_only, etc
  verbosity TEXT DEFAULT 'normal',  -- brief, normal, detailed
  emoji_usage TEXT DEFAULT 'moderate',  -- none, moderate, frequent
  notes TEXT
);

-- Seed default contexts
INSERT OR IGNORE INTO communication_style (context, tone, language_mix, verbosity, emoji_usage) VALUES
  ('default', 'friendly_buddy', 'hinglish_70_30', 'normal', 'moderate'),
  ('riding', 'crisp_concise', 'english_75', 'brief', 'none'),
  ('desktop', 'casual_detailed', 'hinglish_70_30', 'detailed', 'moderate'),
  ('formal', 'professional', 'english_only', 'normal', 'none'),
  ('stressed', 'supportive_calm', 'hinglish_60_40', 'brief', 'few'),
  ('happy', 'enthusiastic', 'hinglish_70_30', 'normal', 'frequent');

-- ========================================
-- 5. EMOTIONAL STATE LOG
-- ========================================
CREATE TABLE IF NOT EXISTS emotional_state (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  log_date DATE NOT NULL,
  log_time TIME,
  mood TEXT NOT NULL,  -- happy, neutral, stressed, sad, excited, anxious
  mood_score INTEGER DEFAULT 5,  -- 1-10
  energy_level INTEGER DEFAULT 5,  -- 1-10
  stress_level INTEGER DEFAULT 3,  -- 1-10
  trigger TEXT,  -- what caused this state
  notes TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_emotion_date ON emotional_state(log_date);

-- ========================================
-- 6. DECISION LOG (Learning from outcomes)
-- ========================================
CREATE TABLE IF NOT EXISTS decision_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  decision_date DATE DEFAULT CURRENT_DATE,
  domain TEXT NOT NULL,  -- finance, career, health, social, personal
  situation TEXT NOT NULL,
  decision_made TEXT NOT NULL,
  alternatives_considered TEXT,  -- JSON array
  reasoning TEXT,
  outcome TEXT,  -- good, bad, neutral, pending
  outcome_notes TEXT,
  lesson_learned TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_decision_domain ON decision_log(domain);
CREATE INDEX IF NOT EXISTS idx_decision_outcome ON decision_log(outcome);

-- ========================================
-- 7. ADVICE MEMORY (What advice was given)
-- ========================================
CREATE TABLE IF NOT EXISTS advice_given (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  advice_date DATE DEFAULT CURRENT_DATE,
  domain TEXT NOT NULL,
  situation TEXT NOT NULL,
  advice TEXT NOT NULL,
  was_followed INTEGER DEFAULT 0,  -- 0=unknown, 1=yes, -1=no
  outcome_if_known TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ========================================
-- VIEW: Current emotional snapshot
-- ========================================
CREATE VIEW IF NOT EXISTS v_current_mood AS
SELECT 
  mood,
  mood_score,
  energy_level,
  stress_level,
  trigger,
  log_date,
  log_time
FROM emotional_state 
ORDER BY log_date DESC, log_time DESC 
LIMIT 1;
