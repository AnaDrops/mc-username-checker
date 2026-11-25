"""Shared request spacing, 429 backoff with jitter, automatic slowdown."""
from __future__ import annotations

import asyncio
import random
import time

from . import config


class Limiter:
    def __init__(self, delay: float = config.DEFAULT_DELAY, min_delay: float = config.MIN_DELAY,
                 base: float = config.BACKOFF_BASE, clock=time.monotonic):
        self.delay = max(delay, min_delay)
        self.base = base
        self.clock = clock
        self.streak = 0
        self.total_429 = 0
        self._next = 0.0
        self._paused_until = 0.0
        self._lock = asyncio.Lock()

    @property
    def backoff_remaining(self) -> float:
        return max(0.0, self._paused_until - self.clock())

    async def acquire(self, stop: asyncio.Event) -> bool:
        """Wait for a request slot. False means a stop was requested."""
        async with self._lock:
            while not stop.is_set():
                wait = max(self._next, self._paused_until) - self.clock()
                if wait <= 0:
                    self._next = self.clock() + self.delay
                    return True
                try:
                    await asyncio.wait_for(stop.wait(), min(wait, 0.5))
                except TimeoutError:
                    pass
            return False

    def limited(self, retry_after: float | None = None) -> float:
        self.total_429 += 1
        # 429s from requests already in flight belong to the same episode.
        if not self.backoff_remaining:
            self.streak += 1
            if self.streak >= config.SLOWDOWN_AFTER_429:
                self.delay = min(config.MAX_DELAY, max(self.delay, 0.1) * 2)
        backoff = min(config.BACKOFF_CAP, self.base * 2 ** min(max(self.streak - 1, 0), 10))
        backoff *= random.uniform(1.0, 1.5)
        wait = max(backoff, retry_after or 0.0)
        self._paused_until = max(self._paused_until, self.clock() + wait)
        return wait

    def succeeded(self) -> None:
        if not self.backoff_remaining:
            self.streak = 0
