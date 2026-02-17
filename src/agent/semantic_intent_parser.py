"""
Semantic Intent Parser (System 2)
Uses LLM to classify user intent when Regex (System 1) fails.
"""
import json
import re
from typing import Optional, Dict, Any, List
from pathlib import Path

class SemanticIntentParser:
    """
    Hybrid Intent Parser:
    1. Fast Regex (System 1) - via existing IntentParser logic (delegated or embedded)
    2. Slow LLM (System 2) - via Prompt Engineering to map text -> tool
    """
    
    def __init__(self, data_dir: Path, llm=None):
        self.data_dir = data_dir
        self.llm = llm  # Injected LLM interface
        
        # Tool Schema Definition for LLM
        self.tool_schema = {
            "finance": {
                "description": "Manage money, tracking expenses, income, transfers, and accounts.",
                "actions": ["expense", "income", "transfer", "balance", "add_account", "delete_account"]
            },
            "memory": {
                "description": "Store personal facts, preferences, and important information.",
                "actions": ["remember", "list", "forget"]
            },
            "reminder": {
                "description": "Set reminders and alerts for future tasks.",
                "actions": ["add", "list", "delete"]
            },
            "experience": {
                "description": "Log daily activities, journals, and life events.",
                "actions": ["log", "list", "stats"]
            },
            "decision": {
                "description": "Evaluate purchases or complex choices.",
                "actions": ["evaluate"]
            },
            "planning": {
                "description": "Plan the day or ask for suggestions.",
                "actions": ["daily_plan"]
            }, 
            "ask": {
                "description": "Answer general questions using knowledge base (RAG).",
                "actions": ["query"]
            },
            "relation": {
                "description": "Retrieve information about people, relationships, and entities.",
                "actions": ["get", "add"]
            }
        }

    def parse(self, text: str, context: str = "") -> Optional[Dict[str, Any]]:
        """
        Parse intent using LLM (System 2).
        Returns tool dict or None.
        """
        if not self.llm:
            return None
            
        # Prompt Engineering for Classification
        prompt = self._build_prompt(text, context)
        
        try:
            # Call LLM (mocked or real)
            # Now safe to pass kwargs due to OllamaBackend fix
            response = self.llm.generate(prompt, max_tokens=200, temperature=0.0)
            
            # Extract JSON
            return self._extract_json(response)
        except Exception as e:
            print(f"Semantic Parse Error: {e}")
            return None

    def _build_prompt(self, text: str, context: str = "") -> str:
        tools_str = json.dumps(self.tool_schema, indent=2)
        
        context_block = ""
        if context:
            context_block = f"Context from previous turn:\n{context}\n\n"
            
        return f"""
You are the Intent Classifier for TAPAN_AI.
Map the user query to the correct tool and action.

Available Tools:
{tools_str}

{context_block}User Query: "{text}"

Output JSON format:
{{
  "tool": "tool_name",
  "method": "action_name",
  "params": {{ "key": "value" }},
  "confidence": 0.0-1.0
}}

If uncertain or no tool fits, return {{ "tool": "unknown" }}.
JSON only:
"""

    def _extract_json(self, text: str) -> Optional[Dict]:
        """Extract JSON from potential Markdown blocks"""
        try:
            # Find first { and last }
            start = text.find('{')
            end = text.rfind('}')
            if start != -1 and end != -1:
                json_str = text[start:end+1]
                data = json.loads(json_str)
                if data.get("tool") == "unknown":
                    return None
                return data
        except:
            pass
        return None
