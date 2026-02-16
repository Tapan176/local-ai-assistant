import sqlite3
from pathlib import Path
from datetime import datetime

class FinanceManager:
  def __init__(self, db_path, schema_path=None):
    self.db_path = Path(db_path)
    self.schema_path = Path(schema_path) if schema_path else None
    self._init_db()

  def _init_db(self):
    """Initialize database with schema if needed"""
    if self.schema_path and self.schema_path.exists():
      with open(self.schema_path, 'r', encoding='utf-8') as f:
        schema = f.read()
      conn = sqlite3.connect(self.db_path)
      cursor = conn.cursor()
      cursor.executescript(schema)
      conn.commit()
      conn.close()

    # Ensure default Cash account exists
    self.ensure_account('Cash', 0)

  def format_inr(self, amount):
    """Format amount in INR without decimals if whole number"""
    if amount == int(amount):
      return f"₹{int(amount)}"
    else:
      return f"₹{amount:.2f}"

  def ensure_account(self, account_name, initial_balance=0):
    """Ensure account exists, create if not"""
    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM accounts WHERE name = ?", (account_name,))
    if not cursor.fetchone():
      cursor.execute(
        "INSERT INTO accounts (name, balance) VALUES (?, ?)",
        (account_name, initial_balance)
      )
      conn.commit()
    conn.close()

  def add_expense(self, amount, category, note='', account='Cash', confirm_fn=None):
    # Validation
    if amount <= 0:
      return "❌ Error: Amount must be positive"

    # Ensure account exists
    self.ensure_account(account, 0)

    if confirm_fn:
      confirm_msg = f"Confirm: {self.format_inr(amount)} {category}"
      if note:
        confirm_msg += f" ({note})"
      confirm_msg += "? (yes/no): "
      response = confirm_fn(confirm_msg)
      if response not in ['y', 'yes']:
        return "❌ Transaction cancelled"

    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()
    cursor.execute(
      """INSERT INTO transactions (amount, type, category, account, note)
           VALUES (?, 'expense', ?, ?, ?)""",
      (amount, category, account, note)
    )
    cursor.execute(
      "UPDATE accounts SET balance = balance - ? WHERE name = ?",
      (amount, account)
    )
    conn.commit()
    cursor.execute("SELECT balance FROM accounts WHERE name = ?", (account,))
    balance = cursor.fetchone()[0]
    conn.close()
    return f"✓ Expense added: {self.format_inr(amount)} for {category}\n  Balance: {self.format_inr(balance)}"

  def add_income(self, amount, category, note='', account='Cash'):
    # Validation
    if amount <= 0:
      return "❌ Error: Amount must be positive"

    # Ensure account exists
    self.ensure_account(account, 0)

    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()
    cursor.execute(
      """INSERT INTO transactions (amount, type, category, account, note)
           VALUES (?, 'income', ?, ?, ?)""",
      (amount, category, account, note)
    )
    cursor.execute(
      "UPDATE accounts SET balance = balance + ? WHERE name = ?",
      (amount, account)
    )
    conn.commit()
    cursor.execute("SELECT balance FROM accounts WHERE name = ?", (account,))
    balance = cursor.fetchone()[0]
    conn.close()
    return f"✓ Income added: {self.format_inr(amount)} for {category}\n  Balance: {self.format_inr(balance)}"

  def show_balance(self, account='Cash'):
    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name, balance FROM accounts WHERE name = ?", (account,))
    result = cursor.fetchone()
    if not result:
      cursor.execute("INSERT INTO accounts (name, balance) VALUES (?, 0)", (account,))
      conn.commit()
      result = (account, 0)
    name, balance = result
    cursor.execute("SELECT name, balance FROM accounts ORDER BY name")
    all_accounts = cursor.fetchall()
    cursor.execute(
      """SELECT type, amount, category, note, date 
           FROM transactions 
           WHERE account = ? 
           ORDER BY date DESC LIMIT 5""",
      (account,)
    )
    transactions = cursor.fetchall()
    conn.close()
    output = f"\n💰 Account: {name}\n"
    output += f"   Balance: {self.format_inr(balance)}\n"
    if len(all_accounts) > 1:
      total = sum(acc[1] for acc in all_accounts)
      output += f"\n📊 Total across all accounts: {self.format_inr(total)}\n"
      output += "   Accounts:\n"
      for acc_name, acc_balance in all_accounts:
        marker = "→" if acc_name == name else " "
        output += f"   {marker} {acc_name}: {self.format_inr(acc_balance)}\n"
    if transactions:
      output += "\n📝 Last 5 Transactions:\n"
      for tx in transactions:
        tx_type, amount, category, note, date = tx
        symbol = "➖" if tx_type == "expense" else "➕"
        output += f"   {symbol} {self.format_inr(amount)} - {category}"
        if note:
          output += f" ({note})"
        output += f" [{date[:16]}]\n"
    else:
      output += "\n📝 No transactions yet\n"
    return output

  def list_accounts(self):
    """List all accounts with balances"""
    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name, balance, created_at FROM accounts ORDER BY name")
    accounts = cursor.fetchall()
    conn.close()

    if not accounts:
      return "\n📂 No accounts found\n"

    output = "\n📂 All Accounts:\n\n"
    total = 0
    for name, balance, created in accounts:
      output += f"   {name}: {self.format_inr(balance)}"
      if created:
        output += f" (created: {created[:10]})"
      output += "\n"
      total += balance

    output += f"\n   Total: {self.format_inr(total)}\n"
    return output

  def add_account(self, name, opening_balance=0):
    """Add a new account"""
    # Validation
    if opening_balance < 0:
      return "❌ Error: Opening balance cannot be negative"

    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()

    # Check if account already exists
    cursor.execute("SELECT name FROM accounts WHERE name = ?", (name,))
    if cursor.fetchone():
      conn.close()
      return f"❌ Error: Account '{name}' already exists"

    # Create account
    cursor.execute(
      "INSERT INTO accounts (name, balance) VALUES (?, ?)",
      (name, opening_balance)
    )
    conn.commit()
    conn.close()

    return f"✓ Account '{name}' created with balance {self.format_inr(opening_balance)}"

  def get_monthly_totals(self, account='Cash', year=None, month=None):
    """Get monthly category totals"""
    if year is None or month is None:
      now = datetime.now()
      year = now.year
      month = now.month

    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()

    # Get expenses by category
    cursor.execute(
      """SELECT category, SUM(amount) as total
         FROM transactions
         WHERE account = ?
         AND type = 'expense'
         AND strftime('%Y', date) = ?
         AND strftime('%m', date) = ?
         GROUP BY category
         ORDER BY total DESC""",
      (account, str(year), f"{month:02d}")
    )
    expenses = cursor.fetchall()

    # Get total income
    cursor.execute(
      """SELECT SUM(amount) as total
         FROM transactions
         WHERE account = ?
         AND type = 'income'
         AND strftime('%Y', date) = ?
         AND strftime('%m', date) = ?""",
      (account, str(year), f"{month:02d}")
    )
    income_result = cursor.fetchone()
    total_income = income_result[0] if income_result[0] else 0

    conn.close()

    output = f"\n📊 Monthly Report - {year}-{month:02d} ({account})\n\n"
    output += f"Income: {self.format_inr(total_income)}\n\n"

    if expenses:
      output += "Expenses by Category:\n"
      total_expenses = 0
      for category, amount in expenses:
        output += f"   {category}: {self.format_inr(amount)}\n"
        total_expenses += amount
      output += f"\n   Total Expenses: {self.format_inr(total_expenses)}\n"
      output += f"   Net: {self.format_inr(total_income - total_expenses)}\n"
    else:
      output += "No expenses this month\n"

    return output

  def get_total_balance(self) -> float:
    """Get total balance across all accounts"""
    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT SUM(balance) FROM accounts")
    result = cursor.fetchone()
    conn.close()
    return result[0] if result and result[0] else 0.0
