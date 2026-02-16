"""
Context Builder - Gathers all context for LLM calls
Collects: profile, memories, finance snapshot, habits, today's chat
"""
import json
from pathlib import Path
from datetime import datetime, date
from typing import Dict, Any, List, Optional
import sqlite3


class ContextBuilder:
  """Builds full context for LLM from all data sources"""

  def __init__(self, data_dir: Path):
    self.data_dir = Path(data_dir)
    self.chats_dir = self.data_dir / "chats"
    self.chats_dir.mkdir(exist_ok=True)

  def get_today_chat_path(self) -> Path:
    """Get path for today's chat log"""
    today = datetime.now().strftime("%Y-%m-%d")
    return self.chats_dir / f"{today}.json"

  def load_today_chat(self) -> List[Dict]:
    """Load today's conversation"""
    path = self.get_today_chat_path()
    if path.exists():
      with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)
    return []

  def save_chat_turn(self, user_msg: str, assistant_msg: str):
    """Save a conversation turn to today's log"""
    path = self.get_today_chat_path()
    chat = self.load_today_chat()

    chat.append({
      "timestamp": datetime.now().isoformat(),
      "user": user_msg,
      "assistant": assistant_msg
    })

    with open(path, 'w', encoding='utf-8') as f:
      json.dump(chat, f, indent=2, ensure_ascii=False)

  def get_finance_snapshot(self) -> Dict:
    """Get current finance state"""
    finance_db = self.data_dir / "finance.db"
    if not finance_db.exists():
      return {"balance": 0, "accounts": [], "recent_transactions": []}

    try:
      conn = sqlite3.connect(finance_db)
      cursor = conn.cursor()

      # Get accounts
      cursor.execute("SELECT name, balance FROM accounts")
      accounts = [{"name": r[0], "balance": r[1]} for r in cursor.fetchall()]

      # Get recent transactions
      cursor.execute("""
        SELECT type, amount, category, note, date 
        FROM transactions 
        ORDER BY date DESC LIMIT 5
      """)
      transactions = [
        {"type": r[0], "amount": r[1], "category": r[2], "note": r[3], "date": r[4]}
        for r in cursor.fetchall()
      ]

      # Total balance
      cursor.execute("SELECT COALESCE(SUM(balance), 0) FROM accounts")
      total = cursor.fetchone()[0]

      conn.close()

      return {
        "balance": total,
        "accounts": accounts,
        "recent_transactions": transactions
      }
    except Exception as e:
      return {"error": str(e)}

  def get_habits_snapshot(self) -> Dict:
    """Get current habits state"""
    habits_db = self.data_dir / "habits.db"
    if not habits_db.exists():
      return {"habits": [], "pending_today": []}

    try:
      conn = sqlite3.connect(habits_db)
      cursor = conn.cursor()

      # Get all habits
      cursor.execute("SELECT name, description, frequency FROM habits")
      habits = [{"name": r[0], "description": r[1], "frequency": r[2]} for r in cursor.fetchall()]

      # Get today's completions
      today = date.today().isoformat()
      cursor.execute("""
        SELECT DISTINCT name FROM habit_logs WHERE log_date = ?
      """, (today,))
      done_today = [r[0] for r in cursor.fetchall()]

      conn.close()

      pending = [h["name"] for h in habits if h["name"] not in done_today]

      return {
        "habits": habits,
        "done_today": done_today,
        "pending_today": pending
      }
    except Exception as e:
      return {"error": str(e)}

  def get_memories_snapshot(self, query: str = "") -> List[Dict]:
    """Get relevant memories"""
    memory_db = self.data_dir / "memory.db"
    if not memory_db.exists():
      return []

    try:
      conn = sqlite3.connect(memory_db)
      cursor = conn.cursor()

      if query:
        cursor.execute("""
          SELECT text, category, timestamp FROM memories
          WHERE text LIKE ? OR category LIKE ?
          ORDER BY timestamp DESC LIMIT 10
        """, (f"%{query}%", f"%{query}%"))
      else:
        cursor.execute("""
          SELECT text, category, timestamp FROM memories
          ORDER BY timestamp DESC LIMIT 10
        """)

      memories = [
        {"text": r[0], "category": r[1], "timestamp": r[2]}
        for r in cursor.fetchall()
      ]

      conn.close()
      return memories
    except Exception as e:
      return []

  def get_reminders_snapshot(self) -> List[Dict]:
    """Get pending reminders from reminders.db"""
    reminders_db = self.data_dir / "reminders.db"
    if not reminders_db.exists():
      return []

    try:
      conn = sqlite3.connect(reminders_db)
      cursor = conn.cursor()
      cursor.execute("SELECT text, remind_at FROM reminders WHERE status = 'pending' ORDER BY remind_at ASC LIMIT 5")
      rows = cursor.fetchall()
      conn.close()

      return [{"text": r[0], "time": r[1]} for r in rows]
    except:
      return []

  def search_chat_logs(self, query: str) -> List[Dict]:
    """Search across all chat logs"""
    results = []
    query_lower = query.lower()

    for chat_file in self.chats_dir.glob("*.json"):
      try:
        with open(chat_file, 'r', encoding='utf-8') as f:
          chats = json.load(f)

        for chat in chats:
          if query_lower in chat.get("user", "").lower() or \
             query_lower in chat.get("assistant", "").lower():
            results.append({
              "date": chat_file.stem,
              "timestamp": chat.get("timestamp"),
              "user": chat.get("user"),
              "assistant": chat.get("assistant")
            })
      except:
        continue

    return results[:10]  # Limit results

  def build_full_context(self, profile_data: Dict = None) -> str:
    """Build full context string for LLM"""
    parts = []

    # Profile
    if profile_data:
      name = profile_data.get("name")
      if name:
        parts.append(f"USER PROFILE:\nName: {name}")
        if profile_data.get("occupation"):
          parts.append(f"Occupation: {profile_data['occupation']}")
        if profile_data.get("location"):
          parts.append(f"Location: {profile_data['location']}")

    # Finance snapshot
    finance = self.get_finance_snapshot()
    if finance.get("balance") is not None:
      parts.append(f"\nFINANCE:\nTotal Balance: ₹{finance['balance']}")
      if finance.get("accounts"):
        accts = ", ".join([f"{a['name']}: ₹{a['balance']}" for a in finance['accounts'][:3]])
        parts.append(f"Accounts: {accts}")

    # Habits
    habits = self.get_habits_snapshot()
    if habits.get("pending_today"):
      parts.append(f"\nHABITS PENDING TODAY: {', '.join(habits['pending_today'])}")

    # Reminders
    reminders = self.get_reminders_snapshot()
    if reminders:
      rem_list = [f"- {r['text']} (at {r['time']})" for r in reminders]
      parts.append(f"\nUPCOMING REMINDERS:\n" + "\n".join(rem_list))

    # Recent memories
    memories = self.get_memories_snapshot()
    if memories:
      mem_texts = [m['text'][:50] for m in memories[:3]]
      parts.append(f"\nRECENT MEMORIES: {'; '.join(mem_texts)}")

    # Today's conversation (last 3 turns)
    today_chat = self.load_today_chat()
    if today_chat:
      parts.append("\nRECENT CONVERSATION:")
      for turn in today_chat[-3:]:
        user_msg = str(turn.get('user', ''))
        asst_msg = str(turn.get('assistant', ''))
        parts.append(f"User: {user_msg[:80]}")
        parts.append(f"You: {asst_msg[:80]}")

    return "\n".join(parts)
