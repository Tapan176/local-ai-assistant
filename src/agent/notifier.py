"""Fan a fired reminder out to every notification channel; one failing channel never blocks the others."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class Notifier:
    def __init__(self, **channels: Any) -> None:
        self.channels = {name: ch for name, ch in channels.items() if ch is not None}

    async def notify_reminders(self, rows: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
        names = list(self.channels)
        outcomes = await asyncio.gather(*(self.channels[n].notify_reminders(rows, now) for n in names), return_exceptions=True)
        result: dict[str, Any] = {}
        for name, outcome in zip(names, outcomes):
            if isinstance(outcome, Exception):
                logger.error("Notification channel %s failed: %s", name, type(outcome).__name__)
                result[name] = {"sent": 0, "removed": 0, "failed": 1, "error": type(outcome).__name__}
            else:
                result[name] = outcome
        return result
