"""
Task Rule Manager - Manages task-specific rule sets for structured reasoning
"""
import json
from pathlib import Path
from typing import Dict, List, Optional, Any


class TaskRuleManager:
    """Manages task rule sets for structured ask flows"""
    
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.rules_file = self.data_dir / "task_rules.json"
        self.rules = self._load_rules()
        
    def _load_rules(self) -> Dict:
        """Load rules from JSON file"""
        if self.rules_file.exists():
            try:
                with open(self.rules_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get('rules', {})
            except (json.JSONDecodeError, IOError):
                return {}
        return {}
    
    def _save_rules(self):
        """Save rules to JSON file"""
        data = {
            "version": "1.0",
            "rules": self.rules
        }
        with open(self.rules_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def list_rules(self) -> str:
        """List all available rules"""
        if not self.rules:
            return "📋 No task rules defined yet.\nUse: rule add <type> <json>"
        
        output = "\n📋 TASK RULES\n"
        output += "=" * 50 + "\n\n"
        
        for name, rule in self.rules.items():
            desc = rule.get('description', 'No description')
            steps = rule.get('steps', [])
            model = rule.get('model', 'default')
            
            output += f"📌 {name}\n"
            output += f"   {desc}\n"
            output += f"   Steps: {', '.join(steps)}\n"
            output += f"   Model: {model}\n\n"
        
        return output
    
    def get_rule(self, rule_type: str) -> Optional[Dict]:
        """Get a specific rule by type"""
        return self.rules.get(rule_type.lower())
    
    def add_rule(self, rule_type: str, rule_data: Dict) -> str:
        """Add or update a rule"""
        try:
            # Validate required fields
            if 'steps' not in rule_data:
                return "❌ Rule must have 'steps' field"
            
            self.rules[rule_type.lower()] = rule_data
            self._save_rules()
            return f"✓ Rule '{rule_type}' added successfully"
        except Exception as e:
            return f"❌ Error adding rule: {e}"
    
    def remove_rule(self, rule_type: str) -> str:
        """Remove a rule"""
        if rule_type.lower() in self.rules:
            del self.rules[rule_type.lower()]
            self._save_rules()
            return f"✓ Rule '{rule_type}' removed"
        return f"❌ Rule '{rule_type}' not found"
    
    def detect_task_type(self, query: str) -> Optional[str]:
        """Detect task type from query keywords"""
        query_lower = query.lower()
        
        # Research patterns
        if any(kw in query_lower for kw in ['research', 'find out', 'learn about', 'what is', 'explain']):
            return 'research'
        
        # Purchase decision patterns
        if any(kw in query_lower for kw in ['should i buy', 'worth buying', 'purchase', 'afford']):
            return 'purchase_decision'
        
        # Planning patterns
        if any(kw in query_lower for kw in ['plan', 'schedule', 'organize', 'agenda']):
            return 'planning'
        
        # Comparison patterns
        if any(kw in query_lower for kw in ['compare', 'vs', 'better', 'which one', 'difference']):
            return 'comparison'
        
        return None
    
    def apply_rule(self, rule_type: str, context: Dict[str, Any] = None) -> Dict:
        """Apply a rule and return structured execution plan"""
        rule = self.get_rule(rule_type)
        if not rule:
            return {'error': f"Rule '{rule_type}' not found"}
        
        execution_plan = {
            'rule_type': rule_type,
            'steps': rule.get('steps', []),
            'model': rule.get('model', 'reasoning'),
            'safety_check': rule.get('safety', False),
            'includes': rule.get('include', []),
            'context': context or {}
        }
        
        return execution_plan
    
    def format_rule_output(self, rule_type: str, results: Dict[str, str]) -> str:
        """Format output according to rule template"""
        rule = self.get_rule(rule_type)
        if not rule:
            return str(results)
        
        template = rule.get('output_template')
        if template:
            try:
                return template.format(**results)
            except KeyError:
                pass
        
        # Default formatting
        output = f"\n📊 {rule_type.upper()} Results\n"
        output += "=" * 40 + "\n"
        for key, value in results.items():
            output += f"\n### {key.replace('_', ' ').title()}\n{value}\n"
        
        return output
