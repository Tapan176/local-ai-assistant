"""Optional voice interface scaffold."""

from __future__ import annotations

import asyncio
import logging

from tapan_ai.core.orchestrator import Orchestrator


class VoiceInterface:
    def __init__(self) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self._recognizer = None
        self._engine = None
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

        reply = await orchestrator.handle_user_input(session_id=session_id, user_text=text)
        await self.speak(reply.text)
        return reply.text

    async def speak(self, text: str) -> None:
        if not self._available or not self._engine:
            return
        await asyncio.to_thread(self._engine.say, text)
        await asyncio.to_thread(self._engine.runAndWait)

