"""
Intent Parser - Deterministic Routing & Hindi Handling
Phase 15: Full Regex Support
"""
import re
from typing import Optional, Dict, Any, List

class IntentParser:
  """
  Deterministic Intent Parser.
  Extracts intent before LLM.
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
    Returns tool call dict or None.
    """
    text_lower = text.lower().strip()

    # 0. Pre-process Hindi
    for hindi, eng in self.HINDI_MAP.items():
      if hindi in text_lower:
        text_lower = text_lower.replace(hindi, eng)

    # === FINANCE ===

    # Add Account: "add account savings 1000"
    match = re.search(r'add\s+account\s+(\w+)\s+(\d+(?:\.\d+)?)', text_lower)
    if match:
      return {"tool": "finance", "method": "add_account", "params": {"name": match.group(1), "opening_balance": float(match.group(2))}}

    # Add Expense: "expense 500 food [lunch]" or "add 500 food" (risky, keep strict)
    # Strict: "expense <amount> <category> [note]"
    match = re.search(r'expense\s+(\d+(?:\.\d+)?)\s+(\w+)(?:\s+(.*))?', text_lower)
    if match:
      return {
        "tool": "finance", 
        "method": "expense", 
        "params": {"amount": float(match.group(1)), "category": match.group(2), "note": match.group(3) or ""}
      }

    # Add Income: "income 1000 salary"
    match = re.search(r'income\s+(\d+(?:\.\d+)?)\s+(\w+)(?:\s+(.*))?', text_lower)
    if match:
      return {
        "tool": "finance", 
        "method": "income", 
        "params": {"amount": float(match.group(1)), "category": match.group(2), "note": match.group(3) or ""}
      }

    # Transfer: "transfer 500 from A to B"
    match = re.search(r'transfer\s+(\d+(?:\.\d+)?)\s+from\s+(\w+)\s+to\s+(\w+)', text_lower)
    if match:
      return {
        "tool": "finance", 
        "method": "transfer", 
        "params": {"amount": float(match.group(1)), "from_account": match.group(2), "to_account": match.group(3)}
      }

    # List/Balance
    if "balance" in text_lower or (("list" in text_lower or "show" in text_lower) and "account" in text_lower):
      return {"tool": "finance", "method": "accounts", "params": {}}

    # Delete Account
    match = re.search(r'(?:delete|remove)\s+account\s+(\w+)', text_lower)
    if match:
       return {"tool": "finance", "method": "delete_account", "params": {"name": match.group(1)}}

    # === MEMORY ===

    # Remember: "remember I like pizza"
    match = re.search(r'^remember\s+(.+)', text_lower)
    if match:
       return {"tool": "memory", "method": "remember", "params": {"text": match.group(1)}}

    # List Memories
    if ("list" in text_lower or "show" in text_lower) and "memor" in text_lower:
       return {"tool": "memory", "method": "list", "params": {}}

    # === COGNEE (Semantic Memory) ===

    # Recall / Deep Recall: "recall what I said about X", "deep recall X"
    match = re.search(r'^(?:deep\s+)?recall\s+(.+)', text_lower)
    if match:
      return {"tool": "cognee", "method": "recall", "params": {"query": match.group(1)}}

    # Search memory: "search memory pizza"
    match = re.search(r'^search\s+memor\w*\s+(.+)', text_lower)
    if match:
      return {"tool": "cognee", "method": "search", "params": {"query": match.group(1)}}

    # Multi-hop: "how does X relate to Y"
    match = re.search(r'^(?:how\s+(?:does|do|did)|what\s+connects?)\s+(.+)', text_lower)
    if match:
      return {"tool": "cognee", "method": "multi_hop", "params": {"query": match.group(1)}}

    # Cognee health check
    if text_lower in ["cognee health", "cognee status", "memory health"]:
      return {"tool": "cognee", "method": "health", "params": {}}

    # === REMINDERS ===

    # Remind: "remind me to buy milk" or "remind buy milk"
    match = re.search(r'^remind\s+(?:me\s+to\s+)?(.+)', text_lower)
    if match:
       return {"tool": "reminder", "method": "add", "params": {"text": match.group(1)}}

    # List
    if ("list" in text_lower or "show" in text_lower) and "reminder" in text_lower:
       return {"tool": "reminder", "method": "list", "params": {}}

    # === EXPERIENCE ===

    # Log: "log went to gym"
    match = re.search(r'^log\s+(.+)', text_lower)
    if match:
       return {"tool": "experience", "method": "log", "params": {"text": match.group(1)}}

    # Stats
    if "stats" in text_lower:
       return {"tool": "experience", "method": "stats", "params": {}}

    # List Experiences
    if "experience" in text_lower and ("list" in text_lower or "show" in text_lower):
       # For now, base tool doesn't have "list", but we can map to stats or a new list method if tool supports it.
       # ExperienceTool actions: ["add", "log", "stats", "delete_all", "delete_by_category", "delete_by_text", "on_date"]
       # It doesn't have a plain "list". Let's map to "stats" for now or use "on_date" -> "today" if we want list?
       # BaseTool usually maps "list" if the tool implements it? NO, FinanceTool implements specific methods.
       # ExperienceTool needs a "list" method or we map to "stats". 
       # Let's map to "stats" as it lists categories, OR we add "list" to ExperienceTool.
       # User asked for "show experiences". 
       # Let's map to "stats" for now, or "on_date" today? 
       # Better: Update ExperienceTool to have a "list" action.
       return {"tool": "experience", "method": "list", "params": {}}

    # === RELATION ===

    # Add: "add relation john"
    match = re.search(r'add\s+relation\s+(\w+)', text_lower)
    if match:
       return {"tool": "relation", "method": "add", "params": {"name": match.group(1)}}

    # === SYSTEM: HELP / LIST / CLEAR ===
    if text_lower in ["help", "man", "?"]:
       return {"tool": "system", "method": "help", "params": {}}

    if text_lower in ["list", "li", "ls"]:
       return {"tool": "system", "method": "list_commands", "params": {}}

    if text_lower in ["cls", "clear"]:
       return {"tool": "system", "method": "clear", "params": {}}

    # === SYSTEM: RESET ===
    if "reset" in text_lower and "system" in text_lower:
      return {"tool": "system", "method": "reset", "params": {}}

    return None
