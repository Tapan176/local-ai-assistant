"""Optional voice interface scaffold."""

from __future__ import annotations

import asyncio
import logging

from src.core.orchestrator import Orchestrator
from src.interfaces.voice_identity import VoiceIdentityStore


class VoiceInterface:
    def __init__(self, strict_user: bool = False, data_dir: str = "data") -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self._recognizer = None
        self._engine = None
        self._strict_user = strict_user
        self._pending_registration_user: str | None = None
        self._identity_store = VoiceIdentityStore(data_dir=data_dir)
        self._available = self._try_init()

    def _try_init(self) -> bool:
        try:
            import speech_recognition as sr
            import pyttsx3
        except Exception:
            return False
        self._recognizer = sr.Recognizer()
        self._engine = pyttsx3.init()
        return True

    @property
    def available(self) -> bool:
        return self._available

    async def run_once(self, orchestrator: Orchestrator, session_id: str = "voice-session") -> str:
        if not self._available:
            return "Voice dependencies are not available."

        try:
            import speech_recognition as sr
        except Exception:
            return "Speech recognition backend is unavailable."

        recognizer: sr.Recognizer = self._recognizer
        with sr.Microphone() as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.4)
            audio = await asyncio.to_thread(recognizer.listen, source, 5, 10)
        try:
            text = await asyncio.to_thread(recognizer.recognize_google, audio)
        except Exception:
            return "I could not transcribe that audio."

        admin = self._handle_voice_admin_command(text)
        if admin is not None:
            await self.speak(admin)
            return admin

        verification = self._voice_meta(audio)
        if self._strict_user and not verification.get("speaker_verified", True):
            return "Ignored non-owner voice input."

        reply = await orchestrator.handle_user_input(session_id=session_id, user_text=text)
        await self.speak(reply.text)
        return reply.text

    async def speak(self, text: str) -> None:
        if not self._available or not self._engine:
            return
        await asyncio.to_thread(self._engine.say, text)
        await asyncio.to_thread(self._engine.runAndWait)

    def _voice_meta(self, audio) -> dict[str, object]:
        if audio is None:
            return {"speaker_verified": True}
        raw = audio.get_raw_data(convert_rate=16000, convert_width=2)
        if self._pending_registration_user:
            user = self._pending_registration_user
            self._identity_store.register(user, raw)
            self._pending_registration_user = None
            return {"speaker_verified": True, "speaker_id": user, "voice_event": "registered"}
        verification = self._identity_store.verify(raw)
        return {
            "speaker_verified": bool(verification.get("verified", True)),
            "speaker_id": verification.get("user_id"),
            "speaker_score": verification.get("score"),
        }

    def _handle_voice_admin_command(self, text: str) -> str | None:
        lowered = text.lower().strip()
        if lowered.startswith("register my voice as "):
            user = lowered.replace("register my voice as ", "", 1).strip()
            if user:
                self._pending_registration_user = user
                return f"Voice enrollment armed for {user}. Please speak one full sentence."
        if lowered.startswith("set active voice "):
            user = lowered.replace("set active voice ", "", 1).strip()
            if user and self._identity_store.set_active_user(user):
                return f"Active voice set to {user}."
            return "Active voice not changed because this profile does not exist."
        return None
