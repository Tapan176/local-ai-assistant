"""
Phase 18: Enhanced Voice Interface
Adds emotion detection (heuristic) and expressive speech synthesis.
"""
from typing import Dict, Optional
import time
# Assuming VoiceInterface is in src.io.voice
try:
  from src.io.voice import VoiceInterface
except ImportError:
  # Fallback if src.io.voice not found (e.g. strict tests)
  class VoiceInterface:
    def __init__(self, wake_words=None): pass
    def listen(self): return "input"
    def speak(self, text): print(text)
    @property
    def engine(self): 
      class MockEngine:
        def setProperty(self, k, v): pass
      return MockEngine()
    @property
    def voice_rate(self): return 150
    @property
    def voice_volume(self): return 1.0

class EmotionDetector:
  """Simple rule-based emotion detector for text."""
  
  def detect(self, text: str) -> str:
    text_lower = text.lower()
    if any(w in text_lower for w in ['happy', 'great', 'love', 'yay', 'thanks']):
      return 'happy'
    if any(w in text_lower for w in ['sad', 'bad', 'hate', 'terrible', 'sorry']):
      return 'sad'
    if any(w in text_lower for w in ['stress', 'busy', 'tired', 'help']):
      return 'stressed'
    if '?' in text:
      return 'curious'
    return 'neutral'

class EnhancedVoiceInterface(VoiceInterface):
  """
  Voice interface with emotional adaptation.
  """
  
  def __init__(self, wake_words=None):
    super().__init__(wake_words)
    self.detector = EmotionDetector()

  def listen_with_emotion(self) -> Dict:
    """Listen and return text + detected emotion."""
    text = self.listen()
    if not text:
      return {"text": "", "emotion": "neutral"}
      
    emotion = self.detector.detect(text)
    return {
      "text": text,
        "emotion": emotion
    }

  def speak_with_personality(self, text: str, emotion: str = "neutral"):
    """Adjust speech rate/volume based on emotion."""
    try:
      engine = self.engine
      if emotion == 'happy':
        engine.setProperty('rate', self.voice_rate + 20)
        engine.setProperty('volume', 1.0)
      elif emotion == 'sad' or emotion == 'stressed':
        engine.setProperty('rate', max(100, self.voice_rate - 20))
        engine.setProperty('volume', 0.8)
      else:
        # Reset
        engine.setProperty('rate', self.voice_rate)
        engine.setProperty('volume', self.voice_volume)
    except Exception:
      pass
      
    self.speak(text)
