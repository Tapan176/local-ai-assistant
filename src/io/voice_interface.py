"""
Voice Interface - Speech-to-Text (STT) and Text-to-Speech (TTS).
Uses speech_recognition for input and pyttsx3 for output (offline).
"""
import speech_recognition as sr
import pyttsx3
import threading
import time
from typing import Optional, Callable

class VoiceInterface:
    """
    Handles voice input/output.
    """
    def __init__(self, wake_word: str = None):
        self.recognizer = sr.Recognizer()
        self.microphone = sr.Microphone()
        self.wake_word = wake_word.lower() if wake_word else None
        
        # TTS Engine
        try:
            self.engine = pyttsx3.init()
            self.engine.setProperty('rate', 160) # Slightly faster than default
            self.engine.setProperty('volume', 1.0)
            
            # Try to select a good voice (optional)
            voices = self.engine.getProperty('voices')
            for voice in voices:
                if "david" in voice.name.lower() or "zira" in voice.name.lower():
                    self.engine.setProperty('voice', voice.id)
                    break
        except Exception as e:
            print(f"[VoiceInterface] TTS Init Error: {e}")
            self.engine = None
            
        self.is_listening = False

    def listen(self, timeout: int = 5, phrase_time_limit: int = 10) -> str:
        """
        Listen for a single phrase.
        Returns text or empty string if failed/timeout.
        """
        try:
            with self.microphone as source:
                # print("Listening...")
                self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio = self.recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
            
            try:
                text = self.recognizer.recognize_google(audio)
                return text
            except sr.UnknownValueError:
                return ""
            except sr.RequestError:
                return "[Network Error]"
                
        except Exception as e:
            # Timeouts are common, don't spam errors
            if "timed out" not in str(e):
                print(f"[VoiceInterface] Listen Error: {e}")
            return ""

    def speak(self, text: str):
        """Speak text using TTS."""
        if not text or not self.engine:
            return

        try:
            # pyttsx3 runAndWait needs to be on main thread or carefully managed
            # Here we just run it directly.
            self.engine.say(text)
            self.engine.runAndWait()
        except Exception as e:
            print(f"[VoiceInterface] Speak Error: {e}")

    def listen_loop(self, callback: Callable[[str], None], stop_event: threading.Event):
        """
        Continuous listening loop.
        Calls callback(text) when speech is detected.
        """
        print(f"[VoiceInterface] Starting loop. Wake word: {self.wake_word}")
        with self.microphone as source:
            self.recognizer.adjust_for_ambient_noise(source, duration=1.0)
            
    while not stop_event.is_set():
      text = self.listen()
      if text:
        text_lower = text.lower()

        if self.wake_word:
          if self.wake_word in text_lower:
            # Strip wake word (simple logic)
            command = text_lower.split(self.wake_word, 1)[1].strip()
            if command:
              # Send with source metadata
              callback({"text": command, "source": "voice"})
            else:
              # Wake word detected but no command, listen again for command
              self.speak("Yes?")
              cmd = self.listen()
              if cmd:
                callback({"text": cmd, "source": "voice"})
        else:
          # No wake word mode - process everything with voice source
          callback({"text": text, "source": "voice"})

      time.sleep(0.1)
