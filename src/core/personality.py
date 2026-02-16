"""
Personality Layer - Casual Hinglish responses
Mix of English 70% and Hindi 30%
"""
import random


class PersonalityLayer:
  """Add personality to TAPAN_AI responses"""

  def __init__(self):
    # Response templates for different actions
    self.templates = {
      'expense_added': [
        "Done bro, ₹{amount} {category} add kar diya",
        "Ho gaya, ₹{amount} {category} ka kharcha noted",
        "✓ Expense logged: ₹{amount} on {category}",
        "Achha, ₹{amount} {category} pe spend kiya",
      ],
      'income_added': [
        "Nice! ₹{amount} {category} se income add ho gaya",
        "Badiya, ₹{amount} ka paisa aa gaya from {category}",
        "✓ Income added: ₹{amount} from {category}",
        "Mast, ₹{amount} {category} se kamaya",
      ],
      'memory_saved': [
        "Yaad rakh liya 👍",
        "Got it, memory saved",
        "Ho gaya bhai, yaad rakhunga",
        "✓ Remembered that",
      ],
      'journal_saved': [
        "Journal entry save ho gaya 📔",
        "Likh diya bhai, yaad rahega",
        "✓ Journal updated",
        "Noted in your journal 📝",
      ],
      'reminder_set': [
        "Reminder set kar diya ⏰",
        "Yaad dilaunga time pe 👍",
        "✓ Reminder created",
        "Done, I'll remind you",
      ],
      'reminder_done': [
        "Mark kar diya done ✓",
        "Ho gaya complete 👍",
        "✓ Reminder completed",
        "Great, marked as done",
      ],
      'account_created': [
        "New account ban gaya: {name}",
        "✓ Account '{name}' created",
        "Done bro, {name} account ready hai",
        "Account {name} set ho gaya",
      ],
      'balance_check': [
        "Dekh le tera balance:",
        "Here's your balance:",
        "Yeh raha tera paisa:",
        "Balance check kar le:",
      ],
      'error': [
        "Oops, kuch gadbad hai: {message}",
        "Error bro: {message}",
        "❌ Issue: {message}",
        "Problem hai: {message}",
      ],
      'greeting': [
        "Namaste! Kya help chahiye?",
        "Hey! What's up?",
        "Bol bhai, kya kaam hai?",
        "Hi! How can I help?",
      ],
      'goodbye': [
        "Bye! Milte hain 👋",
        "See you later!",
        "Chalo phir, bye bye",
        "Take care! 👍",
      ],
      'unknown': [
        "Samajh nahi aaya bro, 'help' type kar",
        "Not sure what you mean, try 'help'",
        "Ye command nahi pata, check 'help'",
        "Try typing 'help' for commands",
      ],
    }

  def get_response(self, response_type, **kwargs):
    """Get a personalized response

    Args:
      response_type: Type of response (expense_added, memory_saved, etc.)
      **kwargs: Variables to fill in the template

    Returns:
      Formatted response string
    """
    if response_type not in self.templates:
      return kwargs.get('default', "Done")

    template = random.choice(self.templates[response_type])

    try:
      return template.format(**kwargs)
    except KeyError:
      return template

  def format_expense_response(self, amount, category, balance):
    """Format expense response with balance

    Args:
      amount: Amount spent
      category: Expense category
      balance: New balance

    Returns:
      Formatted response
    """
    response = self.get_response('expense_added', amount=amount, category=category)
    response += f"\n  Balance: ₹{int(balance) if balance == int(balance) else balance:.2f}"
    return response

  def format_income_response(self, amount, category, balance):
    """Format income response with balance

    Args:
      amount: Amount earned
      category: Income category
      balance: New balance

    Returns:
      Formatted response
    """
    response = self.get_response('income_added', amount=amount, category=category)
    response += f"\n  Balance: ₹{int(balance) if balance == int(balance) else balance:.2f}"
    return response

  def format_account_response(self, name, balance):
    """Format account creation response

    Args:
      name: Account name
      balance: Opening balance

    Returns:
      Formatted response
    """
    response = self.get_response('account_created', name=name)
    if balance > 0:
      response += f" with ₹{int(balance) if balance == int(balance) else balance:.2f}"
    return response

  def casual_affirmative(self):
    """Get a casual affirmative response"""
    responses = [
      "Haan bhai",
      "Sure thing",
      "Ho gaya",
      "Done ✓",
      "Theek hai",
      "Okay boss",
    ]
    return random.choice(responses)

  def casual_confirmation(self):
    """Get a casual confirmation phrase"""
    responses = [
      "Pakka?",
      "Confirm?",
      "Sure?",
      "Haan?",
    ]
    return random.choice(responses)
