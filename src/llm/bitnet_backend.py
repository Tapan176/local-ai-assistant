"""BitNet LLM backend service for local AI inference."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any

import httpx

from src.config.settings import Settings

logger = logging.getLogger(__name__)


class BitNetBackend:
    """BitNet backend with local bitnet.cpp and service fallback support."""

    def __init__(
        self,
        base_url: str = "http://localhost:8001",
        model: str = "bitnet-7b",
        timeout: int = 60,
        mode: str = "auto",
        cpp_executable: str = "",
        cpp_model_path: str = "",
        cpp_max_tokens: int = 256,
        cpp_threads: int = 0,
        cpp_ctx_size: int = 0,
        cpp_extra_args: list[str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.mode = self._normalize_mode(mode)
        self.cpp_executable = cpp_executable
        self.cpp_model_path = cpp_model_path
        self.cpp_max_tokens = cpp_max_tokens
        self.cpp_threads = cpp_threads
        self.cpp_ctx_size = cpp_ctx_size
        self.cpp_extra_args = cpp_extra_args or []
        self._autodetect_cpp_paths_if_missing()
        self._available: bool | None = None

    def _service_base_urls(self) -> list[str]:
        """Try configured URL first, then legacy local default."""
        urls = [self.base_url]
        legacy_default = "http://localhost:11435"
        if legacy_default not in urls:
            urls.append(legacy_default)
        return urls

    async def check_health(self) -> bool:
        """Check if configured BitNet backend is available."""
        if self.mode in {"cpp", "auto"} and self._check_cpp_health():
            self._available = True
            return True
        if self.mode == "cpp":
            self._available = False
            return False

        # Service health check (configured URL + legacy default URL).
        for service_base_url in self._service_base_urls():
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.get(f"{service_base_url}/health")
                    if response.status_code == 200:
                        self._available = True
                        return True
            except Exception:
                continue
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
        """Generate text using bitnet.cpp and/or service backend."""
        # 1) Try local bitnet.cpp first when configured.
        if self.mode in {"cpp", "auto"}:
            cpp_output = await self._generate_cpp(
                system=system,
                context=context,
                user=user,
                temperature=temperature,
                json_mode=json_mode,
            )
            if cpp_output:
                self._available = True
                return cpp_output
            if self.mode == "cpp":
                logger.warning("bitnet.cpp backend unavailable")
                self._available = False
                return None

        # 2) Try service backend.
        for service_base_url in self._service_base_urls():
            service_output = await self._generate_service_openai(
                service_base_url=service_base_url,
                system=system,
                context=context,
                user=user,
                temperature=temperature,
                json_mode=json_mode,
            )
            if service_output:
                self._available = True
                return service_output

            legacy_output = await self._generate_service_legacy(
                service_base_url=service_base_url,
                user=user,
                system=system,
            )
            if legacy_output:
                self._available = True
                return legacy_output

        logger.warning("BitNet service unavailable")
        self._available = False
        return None

    async def stream_generate(
        self,
        system: str,
        context: str,
        user: str,
        temperature: float = 0.5,
    ) -> Any:
        """Stream text generation from backend (single-chunk for bitnet.cpp)."""
        if self.mode in {"cpp", "auto"}:
            text = await self._generate_cpp(system=system, context=context, user=user, temperature=temperature, json_mode=False)
            if text:
                yield text
                return
            if self.mode == "cpp":
                return

        if not await self.check_health():
            return

        service_base_url = self._service_base_urls()[0]
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
                    f"{service_base_url}/v1/chat/completions",
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

    @staticmethod
    def _normalize_mode(mode: str) -> str:
        value = (mode or "auto").lower().strip()
        if value == "local":
            return "cpp"
        if value == "http":
            return "service"
        if value not in {"auto", "cpp", "service"}:
            return "auto"
        return value

    def _autodetect_cpp_paths_if_missing(self) -> None:
        """Restore legacy behavior: detect bitnet/bin and bitnet/models automatically."""
        if self.cpp_executable and self.cpp_model_path:
            return

        project_root = Path(__file__).resolve().parents[2]
        bitnet_dir = project_root / "bitnet"
        bin_dir = bitnet_dir / "bin"
        models_dir = bitnet_dir / "models"
        model_search_roots = [models_dir, bitnet_dir]
        binary_search_roots = [bin_dir, bitnet_dir]

        if not self.cpp_executable:
            candidates = [
                "llama-cli.exe",
                "main.exe",
                "llama-server.exe",
                "llama-cli",
                "main",
                "llama-server",
            ]
            for root in binary_search_roots:
                if not root.exists():
                    continue
                for name in candidates:
                    candidate = root / name
                    if candidate.exists():
                        self.cpp_executable = str(candidate)
                        break
                if self.cpp_executable:
                    break
            if not self.cpp_executable and bitnet_dir.exists():
                for candidate in bitnet_dir.rglob("*"):
                    if candidate.is_file() and candidate.name in candidates:
                        self.cpp_executable = str(candidate)
                        break

        if not self.cpp_model_path:
            for root in model_search_roots:
                if not root.exists():
                    continue
                preferred = sorted(root.glob("**/*bitnet*.gguf")) + sorted(root.glob("**/*1.58*.gguf"))
                if preferred:
                    self.cpp_model_path = str(preferred[0])
                    break

                tiny = root / "tinyllama.gguf"
                if tiny.exists():
                    self.cpp_model_path = str(tiny)
                    break

                ggufs = sorted(root.glob("**/*.gguf"))
                if ggufs:
                    self.cpp_model_path = str(ggufs[0])
                    break

    def _check_cpp_health(self) -> bool:
        if not self.cpp_executable or not self.cpp_model_path:
            return False
        exe = Path(self.cpp_executable)
        model = Path(self.cpp_model_path)
        return exe.exists() and model.exists()

    async def _generate_service_openai(
        self,
        *,
        service_base_url: str,
        system: str,
        context: str,
        user: str,
        temperature: float,
        json_mode: bool,
    ) -> str | None:
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
                    f"{service_base_url}/v1/chat/completions",
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                if content:
                    logger.info("BitNet model %s responded successfully at %s", self.model, service_base_url)
                    return str(content).strip()
        except httpx.TimeoutException:
            logger.warning("BitNet model %s timed out after %ss at %s", self.model, self.timeout, service_base_url)
        except Exception as exc:
            logger.warning("BitNet OpenAI endpoint failed at %s: %s", service_base_url, exc)
            self._available = False
        return None

    async def _generate_service_legacy(self, *, service_base_url: str, user: str, system: str = "") -> str | None:
        """Compatibility with older BitNet service API: POST /generate."""
        payload = {"prompt": user, "system": system, "stream": False}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{service_base_url}/generate", json=payload)
                response.raise_for_status()
                data = response.json()
                text = data.get("response") or data.get("text") or ""
                if text:
                    logger.info("BitNet legacy endpoint responded successfully at %s", service_base_url)
                    return str(text).strip()
        except Exception as exc:
            logger.warning("BitNet legacy endpoint failed at %s: %s", service_base_url, exc)
        return None

    async def _generate_cpp(
        self,
        *,
        system: str,
        context: str,
        user: str,
        temperature: float,
        json_mode: bool,
    ) -> str | None:
        if not self._check_cpp_health():
            return None

        prompt = (
            f"[SYSTEM]\n{system}\n\n"
            f"[CONTEXT]\n{context}\n\n"
            f"[USER]\n{user}\n\n"
            "[ASSISTANT]\n"
        )
        command = [
            self.cpp_executable,
            "-m",
            self.cpp_model_path,
            "-p",
            prompt,
            "-n",
            str(self.cpp_max_tokens),
            "--temp",
            str(temperature),
            "--no-display-prompt",
        ]
        if self.cpp_threads > 0:
            command.extend(["-t", str(self.cpp_threads)])
        if self.cpp_ctx_size > 0:
            command.extend(["-c", str(self.cpp_ctx_size)])
        command.extend(self.cpp_extra_args)

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout)
        except asyncio.TimeoutError:
            logger.warning("bitnet.cpp timed out after %ss", self.timeout)
            return None
        except Exception as exc:
            logger.warning("bitnet.cpp launch failed: %s", exc)
            return None

        if process.returncode != 0:
            err = stderr.decode("utf-8", errors="ignore").strip()
            logger.warning("bitnet.cpp exited with code %s: %s", process.returncode, err)
            return None

        text = stdout.decode("utf-8", errors="ignore").strip()
        if not text:
            return None

        # Remove echoed prompt if backend prints it back.
        if text.startswith(prompt):
            text = text[len(prompt) :].strip()

        if json_mode:
            json_match = re.search(r"\{.*\}", text, flags=re.DOTALL)
            if json_match:
                candidate = json_match.group(0).strip()
                try:
                    json.loads(candidate)
                    return candidate
                except Exception:
                    pass
        return text


def create_bitnet_backend(settings: Settings) -> BitNetBackend:
    """Create BitNet backend from settings."""
    bitnet_url = getattr(settings, "bitnet_url", "http://localhost:8001")
    bitnet_model = getattr(settings, "bitnet_model", "bitnet-7b")
    bitnet_timeout = getattr(settings, "bitnet_timeout", 60)
    bitnet_mode = getattr(settings, "bitnet_mode", "auto")
    cpp_executable = getattr(settings, "bitnet_cpp_executable", "")
    cpp_model_path = getattr(settings, "bitnet_cpp_model_path", "")
    cpp_max_tokens = getattr(settings, "bitnet_cpp_max_tokens", 256)
    cpp_threads = getattr(settings, "bitnet_cpp_threads", 0)
    cpp_ctx_size = getattr(settings, "bitnet_cpp_ctx_size", 0)
    cpp_extra_args = getattr(settings, "bitnet_cpp_extra_args", [])
    return BitNetBackend(
        base_url=bitnet_url,
        model=bitnet_model,
        timeout=bitnet_timeout,
        mode=bitnet_mode,
        cpp_executable=cpp_executable,
        cpp_model_path=cpp_model_path,
        cpp_max_tokens=cpp_max_tokens,
        cpp_threads=cpp_threads,
        cpp_ctx_size=cpp_ctx_size,
        cpp_extra_args=cpp_extra_args,
    )
