"""Keep requests to upstream sites slow and few."""

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

DEFAULT_MIN_INTERVAL_S = 1.0
DEFAULT_MAX_CONCURRENT = 2


class RateLimiter:
    """Space out request starts and cap how many run at once.

    Use it around each upstream request:

        async with limiter.slot():
            ...
    """

    def __init__(
        self,
        min_interval_s: float = DEFAULT_MIN_INTERVAL_S,
        max_concurrent: int = DEFAULT_MAX_CONCURRENT,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if min_interval_s < 0:
            raise ValueError("min_interval_s can't be negative")
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be at least 1")
        self._min_interval_s = min_interval_s
        self._clock = clock
        self._sleep = sleep
        self._concurrency = asyncio.Semaphore(max_concurrent)
        self._start_lock = asyncio.Lock()
        self._next_start: float | None = None

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        async with self._concurrency:
            async with self._start_lock:
                if self._next_start is not None:
                    wait = self._next_start - self._clock()
                    if wait > 0:
                        await self._sleep(wait)
                self._next_start = self._clock() + self._min_interval_s
            yield
