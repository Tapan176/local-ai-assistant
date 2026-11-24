"""Tests for BitNet backend local bitnet.cpp integration."""

from __future__ import annotations

import asyncio
import sys

import src.llm.bitnet_backend as bitnet_module
from src.config.settings import Settings
from src.llm.bitnet_backend import BitNetBackend, create_bitnet_backend


class _DummyProcess:
    def __init__(self, stdout: bytes, stderr: bytes = b"", returncode: int = 0) -> None:
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode

    async def communicate(self):
        return self._stdout, self._stderr


def test_create_bitnet_backend_uses_cpp_settings():
    settings = Settings(
        bitnet_mode="cpp",
        bitnet_cpp_executable="C:/bitnet/llama-cli.exe",
        bitnet_cpp_model_path="C:/bitnet/model.gguf",
        bitnet_cpp_max_tokens=128,
        bitnet_cpp_threads=8,
        bitnet_cpp_ctx_size=4096,
    )
    backend = create_bitnet_backend(settings)
    assert backend.mode == "cpp"
    assert backend.cpp_executable.endswith("llama-cli.exe")
    assert backend.cpp_model_path.endswith("model.gguf")
    assert backend.cpp_max_tokens == 128
    assert backend.cpp_threads == 8
    assert backend.cpp_ctx_size == 4096


def test_bitnet_mode_aliases_are_supported():
    assert BitNetBackend(mode="local").mode == "cpp"
    assert BitNetBackend(mode="http").mode == "service"
    assert BitNetBackend(mode="unexpected").mode == "auto"


def test_bitnet_autodetect_cpp_paths(monkeypatch, tmp_path):
    bitnet_root = tmp_path / "bitnet"
    bin_dir = bitnet_root / "bin"
    models_dir = bitnet_root / "models"
    bin_dir.mkdir(parents=True)
    models_dir.mkdir(parents=True)
    executable = bin_dir / "llama-cli.exe"
    model = models_dir / "BitNet-b1.58.gguf"
    executable.write_text("binary")
    model.write_text("model")

    fake_module_path = tmp_path / "src" / "llm" / "bitnet_backend.py"
    fake_module_path.parent.mkdir(parents=True)
    fake_module_path.write_text("# fake")
    monkeypatch.setattr(bitnet_module, "__file__", str(fake_module_path))

    backend = bitnet_module.BitNetBackend(mode="cpp")
    assert backend.cpp_executable == str(executable)
    assert backend.cpp_model_path == str(model)


def test_bitnet_cpp_generate(monkeypatch, tmp_path):
    async def _run() -> None:
        model_path = tmp_path / "bitnet.gguf"
        model_path.write_text("dummy")

        captured: dict[str, object] = {}

        async def fake_exec(*args, **kwargs):  # noqa: ANN002,ANN003
            captured["args"] = args
            captured["kwargs"] = kwargs
            return _DummyProcess(stdout=b"hello from bitnet cpp")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        backend = BitNetBackend(
            mode="cpp",
            cpp_executable=sys.executable,
            cpp_model_path=str(model_path),
            cpp_max_tokens=64,
            timeout=5,
        )

        text = await backend.generate(
            system="system",
            context="context",
            user="user",
            temperature=0.3,
            json_mode=False,
        )
        assert text == "hello from bitnet cpp"
        args = captured.get("args")
        assert isinstance(args, tuple)
        assert "-m" in args
        assert str(model_path) in args
        assert "--no-display-prompt" in args

    asyncio.run(_run())


def test_bitnet_cpp_json_mode_extracts_json(monkeypatch, tmp_path):
    async def _run() -> None:
        model_path = tmp_path / "bitnet.gguf"
        model_path.write_text("dummy")

        async def fake_exec(*args, **kwargs):  # noqa: ANN002,ANN003
            del args, kwargs
            return _DummyProcess(stdout=b"prefix {\"ok\": true, \"value\": 1} suffix")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        backend = BitNetBackend(
            mode="cpp",
            cpp_executable=sys.executable,
            cpp_model_path=str(model_path),
            timeout=5,
        )
        text = await backend.generate(
            system="system",
            context="context",
            user="user",
            temperature=0.1,
            json_mode=True,
        )
        assert text == "{\"ok\": true, \"value\": 1}"

    asyncio.run(_run())


def test_bitnet_service_falls_back_to_legacy_default_url(monkeypatch):
    async def _run() -> None:
        calls: list[tuple[str, str]] = []

        async def fake_openai(
            self,  # noqa: ANN001
            *,
            service_base_url: str,
            system: str,
            context: str,
            user: str,
            temperature: float,
            json_mode: bool,
        ) -> str | None:
            del self, system, context, user, temperature, json_mode
            calls.append(("openai", service_base_url))
            return None

        async def fake_legacy(
            self,  # noqa: ANN001
            *,
            service_base_url: str,
            user: str,
            system: str = "",
        ) -> str | None:
            del self, user, system
            calls.append(("legacy", service_base_url))
            if service_base_url == "http://localhost:11435":
                return "legacy response"
            return None

        monkeypatch.setattr(BitNetBackend, "_generate_service_openai", fake_openai)
        monkeypatch.setattr(BitNetBackend, "_generate_service_legacy", fake_legacy)

        backend = BitNetBackend(mode="service", base_url="http://localhost:8001")
        text = await backend.generate(
            system="system",
            context="context",
            user="user",
            temperature=0.3,
            json_mode=False,
        )
        assert text == "legacy response"
        assert ("openai", "http://localhost:8001") in calls
        assert ("legacy", "http://localhost:11435") in calls

    asyncio.run(_run())
