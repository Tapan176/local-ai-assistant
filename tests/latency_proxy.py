"""A TCP proxy that adds a fixed delay to every network hop, so a local Postgres behaves like one in another region.

Each chunk is stamped on arrival and released ``delay`` seconds later, *without* blocking the chunks behind it: a burst of
pipelined commands therefore costs one round trip, while the same commands sent one at a time cost one round trip each,
exactly as on a real network. Used by the performance tests; not imported by the application."""

from __future__ import annotations

import asyncio
import re
import time
from urllib.parse import urlsplit, urlunsplit


class LatencyProxy:
    def __init__(self, target_dsn: str, one_way_seconds: float = 0.02) -> None:
        parts = urlsplit(target_dsn)
        self._host, self._port = parts.hostname or "127.0.0.1", parts.port or 5432
        self._template = parts
        self.delay = one_way_seconds
        self._server: asyncio.AbstractServer | None = None
        self.port = 0
        self._tasks: set[asyncio.Task] = set()
        self.sends = 0                      # client-to-server chunks seen so far: the number of times the app waited on the network
        self.log: list[str] = []

    @property
    def rtt(self) -> float:
        return self.delay * 2

    @property
    def dsn(self) -> str:
        netloc = self._template.netloc.rsplit("@", 1)[0] + f"@127.0.0.1:{self.port}" if "@" in self._template.netloc else f"127.0.0.1:{self.port}"
        return urlunsplit((self._template.scheme, netloc, self._template.path, self._template.query, ""))

    async def __aenter__(self) -> "LatencyProxy":
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *exc: object) -> None:
        assert self._server is not None
        self._server.close()
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _handle(self, client_r: asyncio.StreamReader, client_w: asyncio.StreamWriter) -> None:
        try:
            up_r, up_w = await asyncio.open_connection(self._host, self._port)
        except OSError:
            client_w.close()
            return
        self._spawn(self._pump(client_r, up_w, True))
        self._spawn(self._pump(up_r, client_w, False))

    def _spawn(self, coro) -> None:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _pump(self, src: asyncio.StreamReader, dst: asyncio.StreamWriter, upstream: bool = False) -> None:
        queue: asyncio.Queue = asyncio.Queue()

        async def reader() -> None:
            try:
                while data := await src.read(65536):
                    if upstream:
                        self.sends += 1
                        if data[:1] in (b"Q", b"P", b"B"):
                            self.log.append(re.sub(r"[^\x20-\x7e]", ".", data[:90].decode("latin1")))
                    queue.put_nowait((time.monotonic() + self.delay, data))
            finally:
                queue.put_nowait((0.0, b""))

        self._spawn(reader())
        try:
            while True:
                ready, data = await queue.get()
                if not data:
                    break
                wait = ready - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
                dst.write(data)
                await dst.drain()
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            dst.close()
