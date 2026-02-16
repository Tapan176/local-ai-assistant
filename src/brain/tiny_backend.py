"""
Tiny Backend - Minimal model for instant responses
Rule-based and embedding-based operations
"""
from typing import Dict, List, Optional
import re
from collections import Counter


class TinyBackend:
  """Tiny/instant backend for simple tasks

  Uses rule-based logic and simple algorithms.
  No actual LLM required - instant responses.
  """

  def __init__(self):
    self.name = "tiny"
    self.tier = "tiny"
    self.ready = True  # Always ready - no model needed

    # Pre-defined templates
    self._templates = self._load_templates()

  def _load_templates(self) -> Dict[str, List[str]]:
    """Load response templates"""
    return {
      'greeting': [
        "Namaste! 🙏 Main TAPAN hoon.",
        "Hey! Kya haal hai?",
        "Hello! Ready to help!"
      ],
      'farewell': [
        "Bye! Take care! 👋",
        "Alvida! See you soon!",
        "Goodbye! Yaad rakhna!"
      ],
      'thanks': [
        "Welcome! 😊",
        "Khushi hui help karke!",
        "Anytime, bhai!"
      ],
      'unknown': [
        "Hmm, samjha nahi. Try 'help' for commands.",
        "Ye command nahi pata. Use 'help'.",
        "Kya matlab hai? Type 'help' for options."
      ]
    }

  def generate(self, prompt: str, context: str = "") -> str:
    """Generate instant response

    Args:
      prompt: User prompt
      context: Additional context

    Returns:
      Response text
    """
    prompt_lower = prompt.lower().strip()

    # Quick pattern matching
    if self._is_greeting(prompt_lower):
      return self._random_template('greeting')

    if self._is_farewell(prompt_lower):
      return self._random_template('farewell')

    if self._is_thanks(prompt_lower):
      return self._random_template('thanks')

    # If context provided, use it
    if context:
      return self._context_summary(context, prompt)

    # Suggest relevant commands
    return self._suggest_command(prompt)

  def _is_greeting(self, text: str) -> bool:
    """Check if text is a greeting"""
    greetings = ['hello', 'hi', 'hey', 'namaste', 'namaskar', 
           'good morning', 'good evening', 'kaise ho']
    return any(g in text for g in greetings)

  def _is_farewell(self, text: str) -> bool:
    """Check if text is a farewell"""
    farewells = ['bye', 'goodbye', 'alvida', 'see you', 'later', 
           'take care', 'good night']
    return any(f in text for f in farewells)

  def _is_thanks(self, text: str) -> bool:
    """Check if text is thanks"""
    thanks = ['thanks', 'thank you', 'shukriya', 'dhanyawad', 'thx']
    return any(t in text for t in thanks)

  def _random_template(self, category: str) -> str:
    """Get random template from category"""
    import random
    templates = self._templates.get(category, self._templates['unknown'])
    return random.choice(templates)

  def _context_summary(self, context: str, query: str) -> str:
    """Generate summary from context"""
    # Extract key sentences
    sentences = re.split(r'[.!?\n]', context)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 10]

    if not sentences:
      return "No relevant information found."

    # Return top sentences
    top = sentences[:3]
    summary = "Here's what I found:\n\n"
    for s in top:
      summary += f"• {s[:100]}{'...' if len(s) > 100 else ''}\n"

    return summary

  def _suggest_command(self, prompt: str) -> str:
    """Suggest a command based on prompt"""
    prompt_lower = prompt.lower()

    # Pattern to command mapping
    suggestions = {
      ('money', 'spend', 'expense', 'cost', 'paisa'): 'Try: add <amount> <category>',
      ('earn', 'income', 'salary', 'received'): 'Try: income <amount> <source>',
      ('balance', 'kitna', 'how much'): 'Try: balance',
      ('remind', 'yaad', 'reminder'): 'Try: remind <text> at <time>',
      ('journal', 'diary', 'write', 'log'): 'Try: journal <your thoughts>',
      ('habit', 'daily', 'track'): 'Try: habit add <name> or habits',
      ('search', 'find', 'dhundo', 'where'): 'Try: search <keyword>',
      ('plan', 'today', 'aaj'): 'Try: plan',
      ('report', 'summary', 'overview'): 'Try: report or monthly',
    }

    for keywords, suggestion in suggestions.items():
      if any(kw in prompt_lower for kw in keywords):
        return suggestion

    return "Type 'help' to see all available commands."

  def summarize(self, text: str, max_length: int = 150) -> str:
    """Quick text summarization

    Args:
      text: Text to summarize
      max_length: Maximum length

    Returns:
      Summary
    """
    # Simple extractive summary
    sentences = re.split(r'[.!?]', text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 20]

    if not sentences:
      return text[:max_length] if len(text) > max_length else text

    # Score sentences by position and length
    scored = []
    for i, s in enumerate(sentences):
      score = 0
      # First sentences get higher score
      if i < 2:
        score += 10 - i * 3
      # Length bonus for medium sentences
      if 50 < len(s) < 150:
        score += 5
      scored.append((score, s))

    # Get top sentences
    scored.sort(reverse=True)
    summary_parts = [s for _, s in scored[:2]]

    summary = '. '.join(summary_parts)
    if len(summary) > max_length:
      summary = summary[:max_length-3] + '...'

    return summary

  def classify(self, text: str) -> Dict:
    """Simple text classification

    Args:
      text: Text to classify

    Returns:
      Classification result
    """
    text_lower = text.lower()

    # Intent patterns
    patterns = {
      'expense': ['spend', 'spent', 'cost', 'paid', 'buy', 'bought', 'expense'],
      'income': ['earn', 'earned', 'income', 'salary', 'received', 'got paid'],
      'query': ['what', 'how', 'when', 'where', 'why', 'which', 'kya', 'kaise'],
      'command': ['add', 'remove', 'delete', 'create', 'set', 'show', 'list'],
      'emotional': ['happy', 'sad', 'angry', 'excited', 'worried', 'stressed'],
    }

    scores = {}
    for intent, keywords in patterns.items():
      score = sum(1 for kw in keywords if kw in text_lower)
      if score > 0:
        scores[intent] = score

    if not scores:
      return {'intent': 'general', 'confidence': 0.5}

    best_intent = max(scores.keys(), key=lambda k: scores[k])
    confidence = min(scores[best_intent] / 3, 1.0)

    return {
      'intent': best_intent,
      'confidence': confidence,
      'all_scores': scores
    }

  def extract_keywords(self, text: str, top_n: int = 5) -> List[str]:
    """Extract keywords from text

    Args:
      text: Source text
      top_n: Number of keywords

    Returns:
      List of keywords
    """
    # Simple keyword extraction
    stop_words = {
      'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
      'is', 'are', 'was', 'were', 'i', 'you', 'he', 'she', 'it', 'we', 'they',
      'this', 'that', 'what', 'how', 'when', 'where', 'why', 'my', 'your'
    }

    # Tokenize
    words = re.findall(r'\b[a-z]+\b', text.lower())
    words = [w for w in words if w not in stop_words and len(w) > 2]

    # Count and return top
    counter = Counter(words)
    return [word for word, _ in counter.most_common(top_n)]

  def is_ready(self) -> bool:
    """Always ready"""
    return True

  def get_info(self) -> Dict:
    """Get backend information"""
    return {
      'name': self.name,
      'tier': self.tier,
      'ready': True,
      'description': 'Rule-based instant responses (no model required)'
    }
