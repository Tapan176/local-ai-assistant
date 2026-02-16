"""
Response Personalizer - Mood-aware, context-adaptive response formatting.

Phase 17: Personalizes assistant responses based on:
- Current mood (empathy when stressed/sad)
- Verbosity preference
- Time-of-day greetings
- First-interaction-of-session handling
"""
from typing import Dict, List, Optional
from datetime import datetime


class ResponsePersonalizer:
  """Personalizes responses based on user profile and context."""

  EMPATHY_STARTERS = [
    "I understand things are hectic. ",
    "Samajh sakta hoon, busy ho. ",
    "Take it easy bhai. ",
    "Ek kaam at a time — no rush. ",
    "I know you have a lot going on. ",
  ]

  GREETINGS = {
    "morning": [
      "Good morning! ☀️ ",
      "Subah ho gayi boss! 🌅 ",
      "Rise and shine! ☀️ ",
    ],
    "afternoon": [
      "Good afternoon! ",
      "Dopahar mein kaam? Dedication! 💪 ",
    ],
    "evening": [
      "Good evening! 🌇 ",
      "Shaam ho gayi — kya haal hai? ",
    ],
    "night": [
      "Late night hustle? 🌙 ",
      "Raat ko bhi kaam? Respect! 🫡 ",
    ],
  }

  def __init__(self, user_profile=None):
    self.profile = user_profile
    self._session_greeted = False

  def personalize(self, response: str, context: Dict = None,
                  is_first: bool = False) -> str:
    """Apply personalization to a response.

    Args:
      response: Base response text
      context: Dict with time_of_day, mood, name, etc.
      is_first: Whether this is first interaction in session
    """
    if not response:
      return response

    ctx = context or {}

    # 1. Add session greeting (first interaction only)
    if is_first and not self._session_greeted:
      response = self._add_greeting(response, ctx)
      self._session_greeted = True

    # 2. Add empathy for stressed/sad users
    mood = ctx.get("mood", "neutral")
    if mood in ("stressed", "sad", "angry"):
      response = self._add_empathy(response, mood)

    # 3. Adjust verbosity if user prefers concise
    if self._prefers_concise():
      response = self._make_concise(response)

    return response

  def _add_greeting(self, response: str, context: Dict) -> str:
    """Add time-appropriate greeting."""
    import random
    time_of_day = context.get("time_of_day", "morning")
    greetings = self.GREETINGS.get(time_of_day, self.GREETINGS["morning"])
    greeting = random.choice(greetings)

    name = context.get("name")
    if name:
      greeting = greeting.rstrip() + f" {name}! "

    return greeting + response

  def _add_empathy(self, response: str, mood: str) -> str:
    """Add empathetic prefix for negative moods."""
    import random
    # Only add empathy sometimes (40% chance) to avoid being annoying
    if hash(response) % 10 < 4:
      starter = random.choice(self.EMPATHY_STARTERS)
      return starter + response
    return response

  def _prefers_concise(self) -> bool:
    """Check if user prefers concise responses."""
    if not self.profile:
      return False
    pref = self.profile.get_preference("verbosity")
    return pref == "concise"

  def _make_concise(self, text: str) -> str:
    """Reduce verbose responses."""
    # Remove filler words
    fillers = [' actually ', ' basically ', ' literally ',
               ' essentially ', ' simply ']
    for filler in fillers:
      text = text.replace(filler, ' ')

    # If more than 300 chars, truncate smartly
    if len(text) > 300:
      sentences = text.split('. ')
      if len(sentences) > 2:
        text = '. '.join(sentences[:3]) + '.'

    return text

  def detect_mood(self, text: str) -> str:
    """Detect mood from user text (delegates to profile if available)."""
    if self.profile and hasattr(self.profile, 'detect_mood'):
      return self.profile.detect_mood(text)

    # Fallback simple detection
    text_lower = text.lower()
    mood_signals = {
      'happy': ['happy', 'great', 'awesome', 'amazing', 'khush', 'mast'],
      'sad': ['sad', 'upset', 'down', 'dukhi', 'udaas'],
      'stressed': ['stressed', 'tired', 'busy', 'overwhelmed', 'thak'],
      'angry': ['angry', 'mad', 'irritated', 'gussa'],
    }
    for mood, words in mood_signals.items():
      if any(w in text_lower for w in words):
        return mood
    return 'neutral'

  def reset_session(self):
    """Reset session state (for new conversation)."""
    self._session_greeted = False
