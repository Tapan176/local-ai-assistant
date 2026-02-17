"""
Voice Interface - Speech-to-Text (STT) and Text-to-Speech (TTS).
Uses speech_recognition for input and pyttsx3 for output (offline).
"""
from pathlib import Path
import speech_recognition as sr
import pyttsx3
import threading
import time
from typing import Callable, Dict, Optional, Tuple

from src.io.voice_identity import VoiceIdentityStore


class VoiceInterface:
    """Handles voice input/output with optional speaker registration and verification."""

    def __init__(self, wake_word: str = None, data_dir: Optional[Path] = None, strict_user: bool = False):
        self.recognizer = sr.Recognizer()
        self.microphone = sr.Microphone()
        self.wake_word = wake_word.lower() if wake_word else None
        self.strict_user = strict_user
        self.identity_store = VoiceIdentityStore(data_dir or Path("data"))

        self.pending_registration_user: Optional[str] = None

        try:
            self.engine = pyttsx3.init()
            self.engine.setProperty('rate', 160)
            self.engine.setProperty('volume', 1.0)
            voices = self.engine.getProperty('voices')
            for voice in voices:
                if "david" in voice.name.lower() or "zira" in voice.name.lower():
                    self.engine.setProperty('voice', voice.id)
                    break
        except Exception as e:
            print(f"[VoiceInterface] TTS Init Error: {e}")
            self.engine = None

    def listen(self, timeout: int = 5, phrase_time_limit: int = 10) -> Tuple[str, Optional[sr.AudioData]]:
        """Listen for a single phrase and return (text, audio)."""
        try:
            with self.microphone as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio = self.recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)

            try:
                text = self.recognizer.recognize_google(audio)
                return text, audio
            except sr.UnknownValueError:
                return "", audio
            except sr.RequestError:
                return "[Network Error]", audio

        except Exception as e:
            if "timed out" not in str(e):
                print(f"[VoiceInterface] Listen Error: {e}")
            return "", None

    def speak(self, text: str):
        """Speak text using TTS."""
        if not text or not self.engine:
            return
        try:
            self.engine.say(text)
            self.engine.runAndWait()
        except Exception as e:
            print(f"[VoiceInterface] Speak Error: {e}")

    def _voice_meta(self, audio: Optional[sr.AudioData]) -> Dict:
        if not audio:
            return {"speaker_verified": True}

        raw = audio.get_raw_data(convert_rate=16000, convert_width=2)

        if self.pending_registration_user:
            user_id = self.pending_registration_user
            self.identity_store.register(user_id, raw)
            self.pending_registration_user = None
            return {
                "speaker_verified": True,
                "speaker_id": user_id,
                "voice_event": f"registered:{user_id}",
            }

        verification = self.identity_store.verify(raw)
        return {
            "speaker_verified": bool(verification.get("verified", True)),
            "speaker_id": verification.get("user_id"),
            "speaker_score": verification.get("score"),
        }

    def _handle_voice_admin_command(self, text_lower: str) -> Optional[Dict]:
        if text_lower.startswith("register my voice as "):
            user_id = text_lower.replace("register my voice as ", "", 1).strip()
            if user_id:
                self.pending_registration_user = user_id
                return {"text": f"Voice enrollment armed for {user_id}. Please speak a full sentence now.", "source": "system"}

        if text_lower.startswith("set active voice "):
            user_id = text_lower.replace("set active voice ", "", 1).strip()
            if user_id and self.identity_store.set_active_user(user_id):
                return {"text": f"Active voice set to {user_id}.", "source": "system"}
            return {"text": "Active voice not changed (unknown profile).", "source": "system"}

        return None

    def listen_loop(self, callback: Callable[[dict], None], stop_event: threading.Event):
        """Continuous listening loop producing payloads with speaker verification metadata."""
        print(f"[VoiceInterface] Starting loop. Wake word: {self.wake_word}")
        with self.microphone as source:
            self.recognizer.adjust_for_ambient_noise(source, duration=1.0)

        while not stop_event.is_set():
            text, audio = self.listen()
            if text:
                text_lower = text.lower().strip()

                admin_result = self._handle_voice_admin_command(text_lower)
                if admin_result:
                    callback(admin_result)
                    time.sleep(0.1)
                    continue

                metadata = self._voice_meta(audio)
                if self.strict_user and not metadata.get("speaker_verified", True):
                    callback({"text": "Ignored non-owner voice input.", "source": "system", **metadata})
                    time.sleep(0.1)
                    continue

                if self.wake_word and self.wake_word in text_lower:
                    command = text_lower.split(self.wake_word, 1)[1].strip()
                    if command:
                        callback({"text": command, "source": "voice", **metadata})
                    else:
                        self.speak("Yes?")
                        cmd, cmd_audio = self.listen()
                        if cmd:
                            callback({"text": cmd, "source": "voice", **self._voice_meta(cmd_audio)})
                elif not self.wake_word:
                    callback({"text": text, "source": "voice", **metadata})

            time.sleep(0.1)
