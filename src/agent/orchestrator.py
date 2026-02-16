"""
Orchestrator - Central Intelligence
"""
import json
import re
from pathlib import Path
from typing import Dict, Any, Optional

from src.agent.intent_parser import IntentParser
from src.agent.output_sanitizer import OutputSanitizer
from src.agent.tools.base import BaseTool
from src.agent.tools.finance_tool import FinanceTool
from src.agent.tools.experience_tool import ExperienceTool
from src.agent.tools.memory_tool import MemoryTool
from src.agent.tools.reminder_tool import ReminderTool
from src.agent.tools.relation_tool import RelationTool
from src.agent.tools.cognee_tool import CogneeTool
from src.agent.memory_router import MemoryRouter
# Optional tools (may need refactor or remain disabled)
# from src.agent.tools.habit_tool import HabitTool

class Orchestrator:
  def __init__(self, data_dir: Path):
    self.data_dir = Path(data_dir)
    self.intent_parser = IntentParser()
    self.sanitizer = OutputSanitizer()

    self.tools: Dict[str, BaseTool] = {}
    self._register_tools()

    # Memory Router: wires SQLite (MemoryTool) + Cognee (CogneeTool)
    memory_tool = self.tools.get("memory")
    cognee_tool = self.tools.get("cognee")
    self.memory_router = MemoryRouter(memory_tool, cognee_tool)

  def _register_tools(self):
    self.register(FinanceTool(self.data_dir))
    self.register(ExperienceTool(self.data_dir))
    self.register(MemoryTool(self.data_dir))
    self.register(ReminderTool(self.data_dir))
    self.register(RelationTool(self.data_dir))
    self.register(CogneeTool(self.data_dir))

  def register(self, tool: BaseTool):
    self.tools[tool.name] = tool

  def process(self, text: str) -> str:
    """
    Main Event Loop:
    1. Deterministic Intent
    2. Execute
    3. Sanitize
    """
    text = text.strip()
    if not text: return ""

    # Direct Help fallback
    if text.lower() in ["help", "?"]:
       return self._show_help()

    if text.lower() in ["cls", "clear"]:
       print("\033[H\033[J", end="")
       return ""

    # 1. Deterministic Output
    intent = self.intent_parser.parse(text)
    if intent:
      # Handle System Commands directly in Orchestrator
      if intent["tool"] == "system":
        return self._handle_system_command(intent["method"], intent["params"])

      # Route memory/cognee through the MemoryRouter
      if intent["tool"] in ("memory", "cognee"):
        result = self.memory_router.route(intent["method"], intent["params"])
        return self.sanitizer.sanitize(result.message)

      return self._execute_tool(intent["tool"], intent["method"], intent["params"])

    return "I didn't understand that command. Try 'help' or list commands."

  def _handle_system_command(self, method: str, params: Dict) -> str:
    if method == "help":
      return self._show_help()
    if method == "list_commands":
      return self._list_commands()
    if method == "clear":
      # Start fresh visually
      print("\033[H\033[J", end="") # ANSII clear code
      return "Cleared console."
    if method == "reset":
      return self._system_reset()
    return "Unknown system command."

  def _show_help(self) -> str:
    return """
TAPAN_AI Help:
- Accounts: 'show accounts', 'add account savings 1000'
- Finance: 'expense 500 food', 'transfer 100 from A to B'
- Memory: 'remember I like X', 'show memories'
- Experience: 'log went to gym', 'show experiences'
- System: 'help', 'reset system', 'exit'
"""

  def _list_commands(self) -> str:
    return """
COMMANDS:
- Finance: accounts, add account, expense, income, transfer, delete account
- Memory: remember, list memories
- Experience: log, stats, show experiences
- Reminder: remind, list reminders
- System: help, reset system, clear, exit
"""

  def _system_reset(self) -> str:
    """Factory Reset: Clear all data from all tools."""
    results = []
    for name, tool in self.tools.items():
      # Assuming all tools have a mechanism to clear data.
      # BaseRepository has delete_all, but tools wrap it.
      # Conventions: 'reset_all', 'delete_all'
      if hasattr(tool, 'execute'):
        # Try common reset actions
        res = tool.execute("delete_all", {})
        if not res.success:
           res = tool.execute("reset_all_balances", {}) # Finance specific

        if res.success:
          results.append(f"{name}: {res.message}")
        else:
          results.append(f"{name}: Failed to reset")

    return "FACTORY RESET COMPLETE:\n" + "\n".join(results)

  def _execute_tool(self, tool_name: str, method: str, params: Dict) -> str:
    tool = self.tools.get(tool_name)
    if not tool:
      return f"Tool '{tool_name}' not active."

    result = tool.execute(method, params)
    sanitized = self.sanitizer.sanitize(result.message)

    if result.success:
      return sanitized
    else:
      return f"Error: {sanitized}"

  def run_cli_loop(self):
    print("TAPAN_AI (SQLite-First) Ready. Type 'exit' to quit.")
    while True:
      try:
        user_in = input("You: ")
        if user_in.lower() in ["exit", "quit"]:
          break
        resp = self.process(user_in)
        print(f"TAPAN: {resp}")
      except KeyboardInterrupt:
        break
      except Exception as e:
        print(f"System Error: {e}")
