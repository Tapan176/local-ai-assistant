"""
Voice Interface - Handles Speech-to-Text and Text-to-Speech
Phase 11: Enhanced with wake word, continuous mode, command routing

Gracefully degrades if audio dependencies are missing.
"""
import sys
import threading
from typing import Optional, Callable, List

# Try importing dependencies
try:
  import speech_recognition as sr
  HAS_SR = True
except ImportError:
  HAS_SR = False

try:
  import pyttsx3
  HAS_TTS = True
except ImportError:
  HAS_TTS = False


class VoiceInterface:
  """
  Voice input/output handler with:
  - Wake word detection ("Hey Tapan", "OK Tapan")
  - Continuous listening mode
  - Text fallback if mic unavailable
  - Command routing callbacks
  """

  WAKE_WORDS = ["tapan", "hey tapan", "ok tapan", "hey assistant"]

  def __init__(self, wake_words: List[str] = None):
    self.has_audio_input = HAS_SR
    self.has_audio_output = HAS_TTS
    self.recognizer = sr.Recognizer() if HAS_SR else None
    self.engine = None

    # Wake word configuration
    self.wake_words = wake_words or self.WAKE_WORDS
    self.require_wake_word = False  # Set True for always-listening mode

    # Continuous mode
    self._listening = False
    self._listen_thread: Optional[threading.Thread] = None
    self._command_callback: Optional[Callable[[str], None]] = None

    # Voice settings
    self.voice_rate = 150  # Words per minute
    self.voice_volume = 0.9

    if HAS_TTS:
      try:
        self.engine = pyttsx3.init()
        self.engine.setProperty('rate', self.voice_rate)
        self.engine.setProperty('volume', self.voice_volume)
      except Exception as e:
        print(f"⚠️ TTS Init failed: {e}")
        self.has_audio_output = False

  def listen(self, timeout: int = 5, phrase_limit: int = 10) -> str:
    """
    Listen for voice input (single utterance).
    Returns text transcription or error message.

    Args:
      timeout: Max seconds to wait for speech to start
      phrase_limit: Max seconds of speech to capture
    """
    if not self.has_audio_input:
      return "❌ Microphone access not available (install SpeechRecognition and PyAudio)"

    try:
      with sr.Microphone() as source:
        print("🎤 Listening...")
        self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
        audio = self.recognizer.listen(
          source, 
          timeout=timeout,
          phrase_time_limit=phrase_limit
        )

      print("⏳ Processing...")
      text = self.recognizer.recognize_google(audio)
      return text

    except sr.WaitTimeoutError:
      return ""
    except sr.UnknownValueError:
      return "🤷 I didn't catch that."
    except sr.RequestError as e:
      return f"❌ STT Service Error: {e}"
    except OSError as e:
      return f"❌ Mic Error: {e}"
    except Exception as e:
      return f"❌ Unexpected Error: {e}"

  def listen_for_wake_word(self, timeout: int = 10) -> bool:
    """
    Listen specifically for wake word activation.
    Returns True if wake word detected.
    """
    if not self.has_audio_input:
      return False

    text = self.listen(timeout=timeout, phrase_limit=3)
    return self._contains_wake_word(text)

  def _contains_wake_word(self, text: str) -> bool:
    """Check if text contains any wake word"""
    text_lower = text.lower()
    return any(wake in text_lower for wake in self.wake_words)

  def _extract_command_after_wake_word(self, text: str) -> str:
    """Extract command text after the wake word"""
    text_lower = text.lower()
    for wake in sorted(self.wake_words, key=len, reverse=True):
      if wake in text_lower:
        idx = text_lower.find(wake) + len(wake)
        return text[idx:].strip()
    return text

  def start_continuous_listening(self, on_command: Callable[[str], None]):
    """
    Start continuous listening mode in background thread.

    Args:
      on_command: Callback function receiving transcribed commands
    """
    if not self.has_audio_input:
      print("❌ Cannot start continuous mode: No microphone")
      return

    self._command_callback = on_command
    self._listening = True
    self._listen_thread = threading.Thread(target=self._continuous_listen_loop, daemon=True)
    self._listen_thread.start()
    print("🎤 Continuous voice mode started. Say 'Hey Tapan' to begin.")

  def stop_continuous_listening(self):
    """Stop continuous listening mode"""
    self._listening = False
    if self._listen_thread:
      self._listen_thread.join(timeout=2)
    print("🎤 Voice listening stopped.")

  def _continuous_listen_loop(self):
    """Background loop for continuous listening"""
    while self._listening:
      try:
        text = self.listen(timeout=5, phrase_limit=15)

        if not text or text.startswith("❌") or text.startswith("🤷"):
          continue

        # Check for wake word if required
        if self.require_wake_word:
          if self._contains_wake_word(text):
            command = self._extract_command_after_wake_word(text)
            if command and self._command_callback:
              self._command_callback(command)
        else:
          # No wake word required, process everything
          if self._command_callback:
            self._command_callback(text)

      except Exception as e:
        print(f"⚠️ Continuous listen error: {e}")
        continue

  def speak(self, text: str, wait: bool = True):
    """
    Speak text using TTS engine.

    Args:
      text: Text to speak
      wait: If True, block until speech completes
    """
    if not self.has_audio_output or not self.engine:
      print(f"🔊 (Simulated): {text}")
      return

    try:
      self.engine.say(text)
      if wait:
        self.engine.runAndWait()
    except Exception as e:
      print(f"❌ TTS Error: {e}")
      print(f"🔊 (Fallback): {text}")

  def speak_async(self, text: str):
    """Speak without blocking"""
    threading.Thread(target=self.speak, args=(text, True), daemon=True).start()

  def set_voice_speed(self, rate: int):
    """Set TTS speed (words per minute, default 150)"""
    self.voice_rate = rate
    if self.engine:
      self.engine.setProperty('rate', rate)

  def set_voice_volume(self, volume: float):
    """Set TTS volume (0.0 to 1.0)"""
    self.voice_volume = max(0.0, min(1.0, volume))
    if self.engine:
      self.engine.setProperty('volume', self.voice_volume)

  def list_voices(self) -> List[str]:
    """List available TTS voices"""
    if not self.engine:
      return []
    voices = self.engine.getProperty('voices')
    return [v.name for v in voices]

  def set_voice(self, voice_index: int):
    """Set TTS voice by index"""
    if not self.engine:
      return
    voices = self.engine.getProperty('voices')
    if 0 <= voice_index < len(voices):
      self.engine.setProperty('voice', voices[voice_index].id)

  def listen_with_text_fallback(self, prompt: str = "") -> str:
    """
    Try voice input, fall back to text if unavailable.
    Best for interactive sessions.
    """
    if prompt:
      self.speak(prompt)

    if self.has_audio_input:
      text = self.listen()
      if text and not text.startswith("❌"):
        return text

    # Fallback to text input
    return input("📝 Type: " if not prompt else f"📝 {prompt}: ")

  def is_available(self) -> bool:
    return self.has_audio_input or self.has_audio_output

  def get_status(self) -> str:
    in_status = "✅ Ready" if self.has_audio_input else "❌ Missing (pip install SpeechRecognition pyaudio)"
    out_status = "✅ Ready" if self.has_audio_output else "❌ Missing (pip install pyttsx3)"
    cont_status = "🟢 Active" if self._listening else "⚪ Inactive"

    return f"""
🎙️ Voice Configuration
---------------------
Input:  {in_status}
Output: {out_status}
Continuous Mode: {cont_status}
Wake Words: {', '.join(self.wake_words[:3])}...
"""


# Singleton instance
_voice_instance: Optional[VoiceInterface] = None

def get_voice() -> VoiceInterface:
  """Get or create the global voice interface"""
  global _voice_instance
  if _voice_instance is None:
    _voice_instance = VoiceInterface()
  return _voice_instance
