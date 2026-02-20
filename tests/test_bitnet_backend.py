"""Tests for BitNet backend local bitnet.cpp integration."""

from __future__ import annotations

import asyncio
import sys

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
