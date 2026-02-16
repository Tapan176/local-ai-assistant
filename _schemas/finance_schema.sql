-- Finance Database Schema for TAPAN_AI
-- Accounts and Transactions Management

-- Accounts table: stores different financial accounts
CREATE TABLE IF NOT EXISTS accounts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  balance REAL NOT NULL DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Transactions table: records all financial transactions
CREATE TABLE IF NOT EXISTS transactions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  amount REAL NOT NULL,
  type TEXT NOT NULL CHECK(type IN ('income', 'expense', 'transfer')),
  category TEXT NOT NULL,
  account TEXT NOT NULL,
  note TEXT,
  date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (account) REFERENCES accounts(name)
);

-- Create default accounts
INSERT OR IGNORE INTO accounts (name, balance) VALUES ('Cash', 0);
INSERT OR IGNORE INTO accounts (name, balance) VALUES ('default', 0);
