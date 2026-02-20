"""BitNet LLM backend service for local AI inference."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

from src.config.settings import Settings

logger = logging.getLogger(__name__)


class BitNetBackend:
    """BitNet service backend for local LLM inference."""

    def __init__(
        self,
        base_url: str = "http://localhost:8001",
        model: str = "bitnet-7b",
        timeout: int = 60,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._available: bool | None = None

    async def check_health(self) -> bool:
        """Check if BitNet service is available."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/health")
                if response.status_code == 200:
                    self._available = True
                    return True
        except Exception:
            pass
        self._available = False
        return False

    async def generate(
        self,
        system: str,
        context: str,
        user: str,
        temperature: float = 0.5,
        json_mode: bool = False,
    ) -> str | None:
        """Generate text using BitNet service."""
        if not await self.check_health():
            logger.warning("BitNet service unavailable")
            return None

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "system", "content": context},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/v1/chat/completions",
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                if content:
                    logger.info("BitNet model %s responded successfully", self.model)
                    return str(content).strip()
        except httpx.TimeoutException:
            logger.warning("BitNet model %s timed out after %ss", self.model, self.timeout)
        except Exception as exc:
            logger.warning("BitNet model %s failed: %s", self.model, exc)
            self._available = False
        return None

    async def stream_generate(
        self,
        system: str,
        context: str,
        user: str,
        temperature: float = 0.5,
    ) -> Any:
        """Stream text generation from BitNet service."""
        if not await self.check_health():
            return

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "system", "content": context},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "stream": True,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/v1/chat/completions",
                    json=payload,
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.strip() or line.startswith("data: [DONE]"):
                            continue
                        if line.startswith("data: "):
                            try:
                                data = json.loads(line[6:])
                                delta = data.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield content
                            except json.JSONDecodeError:
                                continue
        except Exception as exc:
            logger.warning("BitNet streaming failed: %s", exc)
            self._available = False

    @property
    def is_available(self) -> bool:
        """Check if backend is available (cached)."""
        return self._available is True


def create_bitnet_backend(settings: Settings) -> BitNetBackend:
    """Create BitNet backend from settings."""
    bitnet_url = getattr(settings, "bitnet_url", "http://localhost:8001")
    bitnet_model = getattr(settings, "bitnet_model", "bitnet-7b")
    bitnet_timeout = getattr(settings, "bitnet_timeout", 60)
    return BitNetBackend(
        base_url=bitnet_url,
        model=bitnet_model,
        timeout=bitnet_timeout,
    )
