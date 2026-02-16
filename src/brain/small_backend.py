"""
Small Backend - Placeholder for balanced/fast chat model
Targets Phi-2, TinyLlama, or similar small models
"""
from typing import Dict, List, Optional


class SmallBackend:
  """Small model backend for fast chat responses

  Designed for quick responses without heavy computation.
  Placeholder implementation with rule-based responses.
  """

  def __init__(self, model_path: Optional[str] = None):
    self.name = "small"
    self.tier = "small"
    self.model_path = model_path
    self.ready = False
    self._model = None

    self._check_availability()

  def _check_availability(self):
    """Check if small model is available"""
    # Placeholder - would check for model file
    self.ready = False

  def load_model(self, model_path: str) -> bool:
    """Load small model

    Args:
      model_path: Path to model file

    Returns:
      True if loaded successfully
    """
    self.model_path = model_path
    return False

  def generate(self, prompt: str, context: str = "",
         max_tokens: int = 256, temperature: float = 0.8) -> str:
    """Generate quick response

    Args:
      prompt: User prompt
      context: Additional context
      max_tokens: Maximum response length
      temperature: Sampling temperature

    Returns:
      Generated text
    """
    if not self.ready:
      return self._placeholder_chat(prompt, context)

    # Would use actual model
    return self._placeholder_chat(prompt, context)

  def _placeholder_chat(self, prompt: str, context: str) -> str:
    """Generate placeholder chat response"""
    prompt_lower = prompt.lower()

    # Common chat patterns
    if any(greet in prompt_lower for greet in ['hello', 'hi', 'hey', 'namaste']):
      return "Namaste! 🙏 Kaise ho? Main TAPAN hoon, aapka personal assistant."

    if any(word in prompt_lower for word in ['thanks', 'thank you', 'shukriya', 'dhanyawad']):
      return "You're welcome! Aur kuch help chahiye? 😊"

    if 'how are you' in prompt_lower or 'kaise ho' in prompt_lower:
      return "Main theek hoon! 🤖 Aapki kya help kar sakta hoon?"

    if 'what can you do' in prompt_lower or 'help' in prompt_lower:
      return """Main TAPAN hoon, aapka personal assistant! 

Yeh kar sakta hoon:
• 💰 Finance tracking (add/income/balance)
• 📔 Journal entries (journal <text>)
• ⏰ Reminders (remind <text> at <time>)
• ✅ Habit tracking (habit add/done/list)
• 🔍 Memory search (search <keyword>)
• 📊 Reports (report/monthly)

Type 'help' for full command list!"""

    # Context-aware response
    if context:
      # Extract relevant info from context
      return self._context_response(prompt, context)

    # Default response
    return f"""Hmm, let me help you with that!

Query: {prompt[:50]}...

Available options:
• search <keyword> - Find in memories
• report - See overview
• help - All commands

Configure a local model for AI responses."""

  def _context_response(self, prompt: str, context: str) -> str:
    """Generate response using context"""
    # Simple context extraction
    lines = [l.strip() for l in context.split('\n') if l.strip()][:5]

    if not lines:
      return "I couldn't find relevant information. Try 'search <keyword>'."

    response = "Based on your data:\n\n"
    for line in lines:
      if len(line) > 100:
        line = line[:100] + "..."
      response += f"• {line}\n"

    response += "\nWant more details? Use 'search' or 'report'."
    return response

  def chat(self, messages: List[Dict]) -> str:
    """Multi-turn chat

    Args:
      messages: List of {'role': str, 'content': str}

    Returns:
      Response text
    """
    if not messages:
      return "Hello! How can I help?"

    # Get last user message
    last_msg = messages[-1].get('content', '')

    # Simple history-aware response
    history_context = ""
    for msg in messages[:-1]:
      if msg.get('role') == 'user':
        history_context += f"User asked: {msg.get('content', '')[:50]}...\n"

    return self.generate(last_msg, history_context)

  def extract_info(self, text: str, info_type: str) -> List[str]:
    """Extract specific information from text

    Args:
      text: Source text
      info_type: Type of info to extract (dates, amounts, names)

    Returns:
      List of extracted items
    """
    import re

    results = []

    if info_type == 'dates':
      # Simple date pattern
      date_patterns = [
        r'\d{4}-\d{2}-\d{2}',
        r'\d{1,2}/\d{1,2}/\d{4}',
        r'today|tomorrow|yesterday'
      ]
      for pattern in date_patterns:
        results.extend(re.findall(pattern, text.lower()))

    elif info_type == 'amounts':
      # Amount patterns (with ₹ or numbers)
      amount_pattern = r'₹?\d+(?:,\d{3})*(?:\.\d{2})?'
      results = re.findall(amount_pattern, text)

    elif info_type == 'names':
      # Capitalized words (basic name detection)
      name_pattern = r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b'
      results = re.findall(name_pattern, text)

    return results

  def summarize(self, text: str, max_length: int = 200) -> str:
    """Summarize text

    Args:
      text: Text to summarize
      max_length: Maximum summary length

    Returns:
      Summary
    """
    if not self.ready:
      # Simple extractive summary
      sentences = text.replace('\n', ' ').split('. ')
      if len(sentences) <= 2:
        return text[:max_length]

      # Take first and last sentence
      summary = f"{sentences[0]}. {sentences[-1]}"
      return summary[:max_length]

    return text[:max_length]

  def is_ready(self) -> bool:
    """Check if backend is ready"""
    return self.ready

  def get_info(self) -> Dict:
    """Get backend information"""
    return {
      'name': self.name,
      'tier': self.tier,
      'ready': self.ready,
      'model_path': self.model_path,
      'description': 'Small model for fast chat (Phi-2, TinyLlama)'
    }
