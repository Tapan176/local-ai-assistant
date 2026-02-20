"""Retry logic with exponential backoff for resilient operations."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def retry_with_backoff(
    func: Callable[[], Any],
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> T:
    """Retry function with exponential backoff.

    Args:
        func: Async function to retry
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        exponential_base: Base for exponential backoff
        exceptions: Tuple of exceptions to catch and retry on

    Returns:
        Result of the function call

    Raises:
        Last exception if all retries fail
    """
    delay = initial_delay
    last_exception: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            if asyncio.iscoroutinefunction(func):
                return await func()
            return func()
        except exceptions as e:
            last_exception = e
            if attempt < max_retries:
                logger.warning(
                    "Attempt %d/%d failed: %s. Retrying in %.2fs...",
                    attempt + 1,
                    max_retries + 1,
                    str(e),
                    delay,
                )
                await asyncio.sleep(delay)
                delay = min(delay * exponential_base, max_delay)
            else:
                logger.error("All %d retry attempts failed", max_retries + 1)

    if last_exception:
        raise last_exception
    raise RuntimeError("Retry failed without exception")


async def with_timeout(
    coro: Any,
    timeout: float,
    timeout_error: type[Exception] = TimeoutError,
) -> Any:
    """Execute coroutine with timeout.

    Args:
        coro: Coroutine to execute
        timeout: Timeout in seconds
        timeout_error: Exception to raise on timeout

    Returns:
        Result of coroutine

    Raises:
        timeout_error if timeout exceeded
    """
    try:
        # Use asyncio.wait_for for timeout handling
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError as e:
        raise timeout_error(f"Operation timed out after {timeout}s") from e
