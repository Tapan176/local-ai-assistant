"""
Intent Parser - Deterministic Routing + Fuzzy Scoring
Phase 16: Regex + keyword confidence + decision/planning/chat detection
"""
import re
from typing import Optional, Dict, Any, List

# Keyword groups for fuzzy scoring
DECISION_KEYWORDS = [
  "should i", "kya karu", "can i afford", "worth it", "buy or not",
  "is it safe", "khareedun", "lene chahiye", "invest", "emi",
  "should i spend", "should i buy", "kya ye sahi hai",
]

PLANNING_KEYWORDS = [
  "daily plan", "aaj kya karu", "what should i do", "my plan",
  "schedule", "routine", "next action", "suggest", "what next",
  "aaj ka plan", "morning plan", "today's plan",
]

GREETING_KEYWORDS = [
  "hi", "hello", "hey", "namaste", "kya haal", "kaise ho",
  "good morning", "good evening", "sup", "yo",
]

MEMORY_NARRATIVE_HINTS = [
  "aaj", "kal", "yesterday", "today", "last", "felt", "feeling",
  "i felt", "i went", "i did", "went to", "visited", "met",
  "i was", "i had", "maine", "mujhe", "gaya", "gayi",
]


class IntentParser:
  """
  Deterministic Intent Parser with confidence scoring.
  Returns tool call dict with confidence, or None.
  """

  # Hindi to English mapping
  HINDI_MAP = {
    "hata do": "delete",
    "nikal do": "delete",
    "uda do": "delete",
    "dikhao": "list",
    "batao": "list",
    "kya hai": "list",
    "yaad rakho": "remember",
    "yaad": "remember",
    "bhool jao": "forget",
    "jodo": "add",
    "add karo": "add",
    "likho": "add",
    "note karo": "log",
    "bhejo": "transfer",
  }

  def parse(self, text: str) -> Optional[Dict[str, Any]]:
    """
    Parse text for deterministic intent.
    Returns tool call dict with confidence, or None for LLM fallback.
    """
    text_lower = text.lower().strip()

    # 0. Pre-process Hindi
    for hindi, eng in self.HINDI_MAP.items():
      if hindi in text_lower:
        text_lower = text_lower.replace(hindi, eng)

    # === BACKEND TOGGLE ===
    if "/use_cognee" in text_lower or "use cognee" in text_lower:
      return {"tool": "system", "method": "toggle_backend", "params": {"backend": "cognee"}, "confidence": 1.0}
    if "/use_sqlite" in text_lower or "use sqlite" in text_lower:
      return {"tool": "system", "method": "toggle_backend", "params": {"backend": "sqlite"}, "confidence": 1.0}

    # === FINANCE ===

    # Add Account: "add account savings 1000"
    match = re.search(r'add\s+account\s+(\w+)\s+(\d+(?:\.\d+)?)', text_lower)
    if match:
      return {"tool": "finance", "method": "add_account", "params": {"name": match.group(1), "opening_balance": float(match.group(2))}, "confidence": 1.0}

    # Expense: "expense 500 food [lunch]"
    match = re.search(r'expense\s+(\d+(?:\.\d+)?)\s+(\w+)(?:\s+(.*))?', text_lower)
    if match:
      return {
        "tool": "finance",
        "method": "expense",
        "params": {"amount": float(match.group(1)), "category": match.group(2), "note": match.group(3) or ""},
        "confidence": 1.0
      }

    # Income: "income 1000 salary"
    match = re.search(r'income\s+(\d+(?:\.\d+)?)\s+(\w+)(?:\s+(.*))?', text_lower)
    if match:
      return {
        "tool": "finance",
        "method": "income",
        "params": {"amount": float(match.group(1)), "category": match.group(2), "note": match.group(3) or ""},
        "confidence": 1.0
      }

    # Transfer: "transfer 500 from A to B"
    match = re.search(r'transfer\s+(\d+(?:\.\d+)?)\s+from\s+(\w+)\s+to\s+(\w+)', text_lower)
    if match:
      return {
        "tool": "finance",
        "method": "transfer",
        "params": {"amount": float(match.group(1)), "from_account": match.group(2), "to_account": match.group(3)},
        "confidence": 1.0
      }

    # Balance / Show Accounts
    if "balance" in text_lower or (("list" in text_lower or "show" in text_lower) and "account" in text_lower):
      return {"tool": "finance", "method": "accounts", "params": {}, "confidence": 1.0}

    # Delete Account
    match = re.search(r'(?:delete|remove)\s+account\s+(\w+)', text_lower)
    if match:
      return {"tool": "finance", "method": "delete_account", "params": {"name": match.group(1)}, "confidence": 1.0}

    # === PHASE 17: ADAPTIVE COMMANDS (High Priority) ===
    if text_lower in ["suggestions", "suggest", "tips", "proactive"]:
      return {"tool": "system", "method": "suggestions", "params": {}, "confidence": 1.0}

    if text_lower in ["profile", "profile show", "show profile", "my profile"]:
      return {"tool": "system", "method": "profile_show", "params": {}, "confidence": 1.0}

    if text_lower in ["profile stats", "profile summary"]:
      return {"tool": "system", "method": "profile_stats", "params": {}, "confidence": 1.0}

    if text_lower in ["perf", "perf report", "performance", "performance report"]:
      return {"tool": "system", "method": "perf_report", "params": {}, "confidence": 1.0}

    if text_lower in ["session", "session summary"]:
      return {"tool": "system", "method": "session_summary", "params": {}, "confidence": 1.0}

    if text_lower in ["end session", "new session"]:
      return {"tool": "system", "method": "end_session", "params": {}, "confidence": 1.0}

    # === DECISION (should I buy X?) ===
    for kw in DECISION_KEYWORDS:
      if re.search(r'\b' + re.escape(kw) + r'\b', text_lower):
        # Extract amount if present
        amt_match = re.search(r'(\d{3,})', text_lower)
        amount = float(amt_match.group(1)) if amt_match else None
        return {
          "tool": "decision", "method": "evaluate",
          "params": {"query": text, "amount": amount},
          "confidence": 0.9
        }

    # === PLANNING ===
    for kw in PLANNING_KEYWORDS:
      if re.search(r'\b' + re.escape(kw) + r'\b', text_lower):
        return {"tool": "planning", "method": "daily_plan", "params": {"query": text}, "confidence": 0.9}

    # === MEMORY ===

    # Remember: "remember I like pizza"
    match = re.search(r'^remember\s+(.+)', text_lower)
    if match:
      return {"tool": "memory", "method": "remember", "params": {"text": match.group(1)}, "confidence": 1.0}

    # List Memories
    if ("list" in text_lower or "show" in text_lower) and "memor" in text_lower:
      return {"tool": "memory", "method": "list", "params": {}, "confidence": 1.0}

    # === COGNEE (Semantic Memory) ===

    # Recall / Deep Recall
    match = re.search(r'^(?:deep\s+)?recall\s+(.+)', text_lower)
    if match:
      return {"tool": "cognee", "method": "recall", "params": {"query": match.group(1)}, "confidence": 0.95}

    # Search memory
    match = re.search(r'^search\s+memor\w*\s+(.+)', text_lower)
    if match:
      return {"tool": "cognee", "method": "search", "params": {"query": match.group(1)}, "confidence": 0.95}

    # Multi-hop: "how does X relate to Y"
    match = re.search(r'^(?:how\s+(?:does|do|did)|what\s+connects?)\s+(.+)', text_lower)
    if match:
      return {"tool": "cognee", "method": "multi_hop", "params": {"query": match.group(1)}, "confidence": 0.9}

    # Cognee health
    if text_lower in ["cognee health", "cognee status", "memory health"]:
      return {"tool": "cognee", "method": "health", "params": {}, "confidence": 1.0}

    # === REMINDERS ===

    match = re.search(r'^remind\s+(?:me\s+to\s+)?(.+)', text_lower)
    if match:
      return {"tool": "reminder", "method": "add", "params": {"text": match.group(1)}, "confidence": 1.0}

    if ("list" in text_lower or "show" in text_lower) and "reminder" in text_lower:
      return {"tool": "reminder", "method": "list", "params": {}, "confidence": 1.0}

    # === EXPERIENCE ===

    match = re.search(r'^log\s+(.+)', text_lower)
    if match:
      return {"tool": "experience", "method": "log", "params": {"text": match.group(1)}, "confidence": 1.0}

    # Natural language: "today went bowling 800"
    match = re.search(r'^(?:today\s+)?went\s+(.+)', text_lower)
    if match:
      return {"tool": "experience", "method": "log", "params": {"text": match.group(1)}, "confidence": 0.9}

    if "stats" in text_lower:
      return {"tool": "experience", "method": "stats", "params": {}, "confidence": 1.0}

    if "experience" in text_lower and ("list" in text_lower or "show" in text_lower):
      return {"tool": "experience", "method": "list", "params": {}, "confidence": 1.0}

    # === RELATION ===
    
    match = re.search(r'who\s+is\s+(.+)', text_lower)
    if match:
      return {"tool": "relation", "method": "get", "params": {"name": match.group(1).rstrip("?")}, "confidence": 1.0}

    match = re.search(r'how\s+much\s+(?:did\s+i\s+|was\s+)?spent\s+(?:at|on)\s+(.+)', text_lower)
    if match:
      return {"tool": "experience", "method": "sum", "params": {"place": match.group(1).rstrip("?")}, "confidence": 1.0}

    match = re.search(r'when\s+last\s+(?:did\s+i\s+)?(.+)', text_lower)
    if match:
       # Extract activity
       activity = match.group(1).rstrip("?")
       # remove "go" or "went"
       activity = re.sub(r'^(go\s+|went\s+to\s+|went\s+)', '', activity)
       return {"tool": "experience", "method": "list", "params": {"text": activity, "limit": 1}, "confidence": 1.0}

    match = re.search(r'add\s+relation\s+(\w+)', text_lower)

    match = re.search(r'add\s+relation\s+(\w+)', text_lower)
    if match:
      return {"tool": "relation", "method": "add", "params": {"name": match.group(1)}, "confidence": 1.0}

    # === ASK (RAG query) ===
    match = re.search(r'^ask\s+(.+)', text_lower)
    if match:
      return {"tool": "ask", "method": "query", "params": {"query": match.group(1)}, "confidence": 0.95}

    # === LLM COMMANDS ===
    if text_lower in ["llm status", "model status"]:
      return {"tool": "system", "method": "llm_status", "params": {}, "confidence": 1.0}

    if text_lower in ["llm models", "list models", "show models"]:
      return {"tool": "system", "method": "llm_models", "params": {}, "confidence": 1.0}

    match = re.search(r'^llm\s+switch\s+(.+)', text_lower)
    if match:
      return {"tool": "system", "method": "llm_switch", "params": {"model": match.group(1).strip()}, "confidence": 1.0}


    # === SYSTEM ===
    if text_lower in ["help", "man", "?"]:
      return {"tool": "system", "method": "help", "params": {}, "confidence": 1.0}

    if text_lower in ["list", "li", "ls"]:
      return {"tool": "system", "method": "list_commands", "params": {}, "confidence": 1.0}

    if text_lower in ["cls", "clear"]:
      return {"tool": "system", "method": "clear", "params": {}, "confidence": 1.0}

    if "reset" in text_lower and ("system" in text_lower or "factory" in text_lower):
      return {"tool": "system", "method": "reset", "params": {}, "confidence": 1.0}

    # === FUZZY FALLBACK: GREETING / NARRATIVE ===

    # Short greeting → free_chat
    words = text_lower.split()
    if len(words) <= 3 and any(g in text_lower for g in GREETING_KEYWORDS):
      return {"tool": "free_chat", "method": "greet", "params": {"text": text}, "confidence": 0.85}

    # Narrative heuristic: if text has memory hints and is sentence-like → save as memory
    hint_count = sum(1 for h in MEMORY_NARRATIVE_HINTS if h in text_lower)
    if hint_count >= 1 and len(words) >= 4:
      return {"tool": "memory", "method": "remember", "params": {"text": text}, "confidence": 0.6}

    # Long sentence with no match → return None for LLM fallback
    return None
