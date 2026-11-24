"""Lightweight performance monitor for production latency visibility."""

from __future__ import annotations

import time
from collections import deque


class PerformanceMonitor:
    def __init__(self) -> None:
        self._metrics: dict[str, deque[float]] = {}

    def record(self, operation: str, duration_seconds: float) -> None:
        if operation not in self._metrics:
            self._metrics[operation] = deque(maxlen=200)
        self._metrics[operation].append(duration_seconds)

    def wrap_start(self) -> float:
        return time.perf_counter()

    def wrap_end(self, operation: str, started_at: float) -> None:
        self.record(operation, time.perf_counter() - started_at)

    def stats(self, operation: str) -> dict[str, float] | None:
        values = list(self._metrics.get(operation, []))
        if not values:
            return None
        sorted_values = sorted(values)
        idx = int(0.95 * (len(sorted_values) - 1))
        return {
            "count": float(len(values)),
            "mean": sum(values) / len(values),
            "p95": sorted_values[idx],
            "max": max(values),
        }

