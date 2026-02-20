"""Streaming helpers for incremental response delivery."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator


async def stream_text(text: str, chunk_size: int = 18, delay_seconds: float = 0.0) -> AsyncIterator[str]:
    if chunk_size <= 0:
        chunk_size = 18
    for idx in range(0, len(text), chunk_size):
        chunk = text[idx : idx + chunk_size]
        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)
        yield chunk

