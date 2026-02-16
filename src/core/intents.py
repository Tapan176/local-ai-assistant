"""
Intent Layer - Maps user commands to actions
"""
import re
from src.core.parser import HinglishParser

class IntentRouter:
    """Routes user commands to appropriate handlers"""
    
    def __init__(self):
        self.parser = HinglishParser()
    
    def parse_intent(self, user_input):
        """Parse user input and determine intent
        
        Args:
            user_input: Raw user input string
            
        Returns:
            dict with 'intent', 'params', and other metadata
        """
        user_input = user_input.strip().lower()
        
        # Add expense
        if user_input.startswith('add '):
            return self._parse_add_expense(user_input[4:])
        
        # Add income
        if user_input.startswith('income '):
            return self._parse_income(user_input[7:])
        
        # Account commands
        if user_input.startswith('account add '):
            return self._parse_account_add(user_input[12:])
        
        if user_input in ['accounts', 'list accounts']:
            return {'intent': 'list_accounts', 'params': {}}
        
        # Monthly report
        if user_input in ['monthly', 'monthly report']:
            return {'intent': 'monthly_report', 'params': {}}
        
        # Journal
        if user_input.startswith('journal '):
            return {
                'intent': 'journal',
                'params': {'text': user_input[8:].strip()}
            }
        
        # Reminders
        if user_input.startswith('remind '):
            return self._parse_reminder(user_input[7:])
        
        if user_input in ['reminders', 'list reminders']:
            return {'intent': 'list_reminders', 'params': {}}
        
        if user_input.startswith('done '):
            reminder_id = user_input[5:].strip()
            try:
                return {
                    'intent': 'reminder_done',
                    'params': {'reminder_id': int(reminder_id)}
                }
            except ValueError:
                return {
                    'intent': 'error',
                    'params': {'message': 'Reminder ID must be a number'}
                }
        
        # Report
        if user_input == 'report':
            return {'intent': 'report', 'params': {}}
        
        if user_input == 'weekly':
            return {'intent': 'weekly_report', 'params': {}}
        
        # Export/Backup
        if user_input == 'export':
            return {'intent': 'export', 'params': {}}
        
        if user_input.startswith('backup'):
            # Parse: backup OR backup <note> [password]
            parts = user_input.split()
            params = {}
            if len(parts) > 1:
                # Need to distinguish note vs password if multiple args?
                # Simple convention: backup <note> <password>
                params['note'] = parts[1]
                if len(parts) > 2:
                    params['password'] = parts[2]
            return {'intent': 'backup', 'params': params}
        
        if user_input == 'snapshot':
            return {'intent': 'snapshot', 'params': {}}
        
        if user_input.startswith('restore'):
            # Parse: restore OR restore <backup_name> [password]
            parts = user_input.split()
            params = {}
            if len(parts) > 1:
                params['backup_name'] = parts[1]
                if len(parts) > 2:
                    params['password'] = parts[2]
            return {'intent': 'restore', 'params': params}
        
        if user_input == 'backups':
            return {'intent': 'list_backups', 'params': {}}
        
        # Ingest command
        if user_input.startswith('ingest '):
            return {'intent': 'ingest', 'params': {'file_path': user_input[7:].strip()}}
        
        # Plan command
        if user_input == 'plan':
            return {'intent': 'plan', 'params': {}}
        
        # Agenda command
        if user_input == 'agenda':
            return {'intent': 'agenda', 'params': {}}
        
        # Rule commands
        if user_input == 'rules' or user_input == 'rule list':
            return {'intent': 'rule_list', 'params': {}}
        
        if user_input.startswith('rule add '):
            # Parse: rule add <type> <json>
            rest = user_input[9:].strip()
            parts = rest.split(' ', 1)
            if len(parts) >= 2:
                return {'intent': 'rule_add', 'params': {'rule_type': parts[0], 'rule_json': parts[1]}}
            return {'intent': 'rule_add', 'params': {'error': 'Usage: rule add <type> <json>'}}
        
        if user_input.startswith('rule apply '):
            return {'intent': 'rule_apply', 'params': {'rule_type': user_input[11:].strip()}}
        
        if user_input.startswith('rule remove '):
            return {'intent': 'rule_remove', 'params': {'rule_type': user_input[12:].strip()}}
        
        # Voice commands
        if user_input == 'listen':
            return {'intent': 'listen', 'params': {}}
            
        if user_input.startswith('speak '):
            return {'intent': 'speak', 'params': {'text': user_input[6:].strip()}}
        
        # Habits
        if user_input.startswith('habit add '):
            return {
                'intent': 'habit_add',
                'params': {'name': user_input[10:].strip()}
            }
        
        if user_input.startswith('habit done '):
            text = user_input[11:].strip()
            # First word is habit name, rest is note
            parts = text.split(maxsplit=1)
            name = parts[0] if parts else ''
            note = parts[1] if len(parts) > 1 else ''
            return {
                'intent': 'habit_done',
                'params': {'name': name, 'note': note}
            }
        
        if user_input in ['habits', 'habit', 'habit list']:
            return {'intent': 'habit_list', 'params': {}}
        
        if user_input.startswith('habit remove '):
            return {
                'intent': 'habit_remove',
                'params': {'name': user_input[13:].strip()}
            }
        
        # Ask command (RAG query)
        if user_input.startswith('ask '):
            return {
                'intent': 'ask',
                'params': {'query': user_input[4:].strip()}
            }
        
        # Ingest command
        if user_input == 'ingest':
            return {'intent': 'ingest', 'params': {'filepath': ''}}
        
        if user_input.startswith('ingest '):
            return {
                'intent': 'ingest',
                'params': {'filepath': user_input[7:].strip()}
            }
        
        # Remember
        if user_input.startswith('remember '):
            return {
                'intent': 'remember',
                'params': {'text': user_input[9:].strip()}
            }
        
        # Search
        if user_input.startswith('search '):
            return {
                'intent': 'search',
                'params': {'keyword': user_input[7:].strip()}
            }
        
        # Model commands
        if user_input in ['model list', 'models', 'list models']:
            return {'intent': 'model_list', 'params': {}}
        
        if user_input.startswith('model use '):
            return {
                'intent': 'model_use',
                'params': {'model_name': user_input[10:].strip()}
            }
        
        if user_input in ['model status', 'model']:
            return {'intent': 'model_status', 'params': {}}
        
        if user_input.startswith('model install '):
            return {
                'intent': 'model_install',
                'params': {'model_name': user_input[14:].strip()}
            }
        
        # Profile commands
        if user_input in ['profile', 'profile show', 'show profile']:
            return {'intent': 'show_profile', 'params': {}}
        
        if user_input.startswith('profile set '):
            # Parse: profile set <key> <value>
            parts = user_input[12:].strip().split(maxsplit=1)
            if len(parts) >= 2:
                return {
                    'intent': 'set_profile',
                    'params': {'key': parts[0], 'value': parts[1]}
                }
            else:
                return {
                    'intent': 'error',
                    'params': {'message': 'Usage: profile set <key> <value>'}
                }
        
        # Show balance
        if user_input in ['show balance', 'balance', 'bal']:
            return {
                'intent': 'show_balance',
                'params': {}
            }
        
        # Help
        if user_input in ['help', '?']:
            return {'intent': 'help', 'params': {}}
        
        # Test
        if user_input == 'test':
            return {'intent': 'test', 'params': {}}
        
        # Exit
        if user_input in ['exit', 'quit', 'bye']:
            return {'intent': 'exit', 'params': {}}
        
        # Unknown
        return {'intent': 'unknown', 'params': {}}
    
    def _parse_add_expense(self, text):
        """Parse add expense command"""
        amount, remaining = self.parser.parse_hinglish_amount(text)
        
        if amount and amount > 0:
            parts = remaining.split(maxsplit=1)
            category = parts[0] if parts else 'misc'
            note = parts[1] if len(parts) > 1 else ''
            
            # Validate category is not a number word
            if category.lower() in self.parser.hindi_words:
                return {
                    'intent': 'error',
                    'params': {
                        'message': f"Invalid category: '{category}' is a number word"
                    }
                }
            
            return {
                'intent': 'add_expense',
                'params': {
                    'amount': amount,
                    'category': category,
                    'note': note
                }
            }
        else:
            return {
                'intent': 'error',
                'params': {
                    'message': f"Invalid amount in: '{text}'"
                }
            }
    
    def _parse_income(self, text):
        """Parse income command with Hinglish support"""
        amount, remaining = self.parser.parse_hinglish_amount(text)
        
        if amount and amount > 0:
            parts = remaining.split(maxsplit=1)
            category = parts[0] if parts else 'misc'
            note = parts[1] if len(parts) > 1 else ''
            
            # Validate category is not a number word
            if category.lower() in self.parser.hindi_words:
                return {
                    'intent': 'error',
                    'params': {
                        'message': f"Invalid category: '{category}' is a number word"
                    }
                }
            
            return {
                'intent': 'add_income',
                'params': {
                    'amount': amount,
                    'category': category,
                    'note': note
                }
            }
        else:
            return {
                'intent': 'error',
                'params': {
                    'message': f"Invalid amount in: '{text}'"
                }
            }
    
    def _parse_reminder(self, text):
        """Parse reminder command
        
        Formats:
        - remind <text> at <date>
        - remind <text> tomorrow
        - remind <text> in 2 hours
        """
        # Look for "at" keyword
        if ' at ' in text:
            parts = text.split(' at ', 1)
            reminder_text = parts[0].strip()
            date_str = parts[1].strip()
            
            return {
                'intent': 'add_reminder',
                'params': {
                    'text': reminder_text,
                    'remind_at': date_str
                }
            }
        
        # Look for "tomorrow"
        if 'tomorrow' in text:
            reminder_text = text.replace('tomorrow', '').strip()
            
            return {
                'intent': 'add_reminder',
                'params': {
                    'text': reminder_text,
                    'remind_at': 'tomorrow'
                }
            }
        
        # Look for "in X hours/days"
        match = re.match(r'(.+?)\s+in\s+(\d+\s+(?:hour|hours|day|days))', text)
        if match:
            reminder_text = match.group(1).strip()
            date_str = 'in ' + match.group(2).strip()
            
            return {
                'intent': 'add_reminder',
                'params': {
                    'text': reminder_text,
                    'remind_at': date_str
                }
            }
        
        # No date found
        return {
            'intent': 'error',
            'params': {
                'message': 'Please specify when to remind (e.g., "at 2026-02-10", "tomorrow", "in 2 hours")'
            }
        }
    
    def _parse_account_add(self, text):
        """Parse account add command"""
        amount, remaining = self.parser.parse_hinglish_amount(text)
        
        if amount is not None and amount >= 0:
            account_name = remaining.strip()
            if not account_name:
                return {
                    'intent': 'error',
                    'params': {
                        'message': 'Account name is required'
                    }
                }
            
            return {
                'intent': 'add_account',
                'params': {
                    'name': account_name,
                    'opening_balance': amount
                }
            }
        else:
            # Try parsing as: account add <name> <amount>
            parts = text.split(maxsplit=1)
            if len(parts) >= 1:
                name = parts[0]
                balance = 0
                if len(parts) == 2:
                    amount, _ = self.parser.parse_hinglish_amount(parts[1])
                    if amount is not None and amount >= 0:
                        balance = amount
                
                return {
                    'intent': 'add_account',
                    'params': {
                        'name': name,
                        'opening_balance': balance
                    }
                }
            
            return {
                'intent': 'error',
                'params': {
                    'message': f"Invalid account add command: '{text}'"
                }
            }
