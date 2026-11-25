"""Drives a Plan through a backend. UI-agnostic: front ends read snapshot()."""
from __future__ import annotations

import asyncio
import time
from collections import deque

from . import config
from .backend import BLOCKED, ERROR, HITS, NOT_FOUND, TAKEN, VERIFIED, \
    AvailabilityBackend, RateLimited, Result, Transient
from .generators import Plan
from .ratelimit import Limiter


class Runner:
    def __init__(self, plan: Plan, backend: AvailabilityBackend, store, writer, limiter: Limiter,
                 *, concurrency: int = config.DEFAULT_CONCURRENCY, verify: bool = False,
                 max_age_hours: float = config.HISTORY_MAX_AGE_HOURS,
                 ignore_history: bool = False, retries: int = config.NETWORK_RETRIES,
                 webhook=None):
        self.plan, self.backend, self.store, self.writer = plan, backend, store, writer
        self.limiter, self.concurrency = limiter, max(1, concurrency)
        self.verify = verify and backend.can_verify
        self.max_age, self.ignore_history = max_age_hours, ignore_history
        self.retries, self.webhook = retries, webhook
        self.stop = asyncio.Event()
        self.counts = dict.fromkeys((TAKEN, NOT_FOUND, VERIFIED, BLOCKED, ERROR), 0)
        self.checked = self.skipped = self.requests = self.retried = 0
        self.hits: deque = deque(maxlen=10)
        self.current = ""
        self.state = "ready"
        self._started = self._ended = 0.0
        self._retry_queue: list[str] = []
        self._finished: set[int] = set()
        self._position = 0
        self._taken_from_plan = 0

    async def _request(self, call, name: str) -> Result | None:
        """One logical request with retries. None means stopped before an answer."""
        failures = 0
        while await self.limiter.acquire(self.stop):
            self.requests += 1
            try:
                result = await call(name)
            except RateLimited as exc:
                self.limiter.limited(exc.retry_after)
                self.retried += 1
            except Transient as exc:
                failures += 1
                if failures > self.retries:
                    return Result(ERROR, f"network: {exc}")
                self.retried += 1
                try:
                    await asyncio.wait_for(self.stop.wait(), self.limiter.base * 2 ** (failures - 1))
                except TimeoutError:
                    pass
            else:
                self.limiter.succeeded()
                return result
        return None

    async def _check(self, name: str, final: bool) -> bool:
        self.current = name
        result = await self._request(self.backend.lookup, name)
        if result and result.status == NOT_FOUND and self.verify:
            result = await self._request(self.backend.verify, name)
        if result is None:
            return False
        self.store.record(name, result.status, self.plan.mode)
        if result.status == ERROR and not final:
            self._retry_queue.append(name)
            return True
        self.counts[result.status] += 1
        self.checked += 1
        self.writer.write(name, result.status, self.plan.mode, result.detail)
        if result.status in HITS:
            self.hits.appendleft((name, result.status, time.time()))
            if self.webhook:
                self.webhook.add(name, result.status)
        return True

    def _complete(self, index: int) -> None:
        """Advance the resume position only past a contiguous finished prefix."""
        self._finished.add(index)
        while self._position in self._finished:
            self._finished.remove(self._position)
            self._position += 1
        if self.plan.key:
            self.store.save_position(self.plan.key, self._position)

    def _source(self, start: int):
        for index, name in enumerate(self.plan.items(start), start):
            if self.stop.is_set():
                return
            if self.plan.limit and self._taken_from_plan >= self.plan.total:
                return
            if not self.ignore_history and self.store.fresh(name, self.max_age):
                self.skipped += 1
                self._complete(index)
                continue
            self._taken_from_plan += 1
            yield index, name

    async def _drain(self, source, final: bool) -> None:
        async def worker() -> None:
            for index, name in source:
                if not await self._check(name, final):
                    return
                if index is not None:
                    self._complete(index)
                await asyncio.sleep(0)

        async with asyncio.TaskGroup() as group:
            for _ in range(self.concurrency):
                group.create_task(worker())

    async def run(self) -> None:
        self.state, self._started = "running", time.monotonic()
        try:
            if self.plan.key:
                self._position = self.store.position(self.plan.key)
                if self._position >= self.plan.total:
                    self._position = 0  # a finished sweep starts over
            # on resume, retry errors an interrupted run left behind the saved position
            if self._position and self.plan.total <= 100_000:
                behind = set(list(self.plan.items(0))[:self._position])
                self._retry_queue = [n for n in self.store.errors(self.plan.mode) if n in behind]
            await self._drain(self._source(self._position), final=False)
            if self._retry_queue and not self.stop.is_set():
                self.state = "retrying errors"
                queue = list(dict.fromkeys(self._retry_queue))
                self._retry_queue = []
                await self._drain(((None, n) for n in queue if not self.stop.is_set()), final=True)
            self.state = "stopped" if self.stop.is_set() else "finished"
        except BaseException:
            self.state = "failed"
            raise
        finally:
            self._ended = time.monotonic()
            # errors that never reached the retry pass still reach the files
            for name in self._retry_queue:
                self.counts[ERROR] += 1
                self.writer.write(name, ERROR, self.plan.mode, "not retried (run interrupted)")
            self._retry_queue = []

    def snapshot(self) -> dict:
        end = self._ended or time.monotonic()
        elapsed = end - self._started if self._started else 0.0
        rate = self.requests / elapsed if elapsed > 0 else 0.0
        if self.plan.key:
            done = self._position
        elif self.plan.limit:
            done = self.checked
        else:
            done = self.checked + self.skipped
        done = min(done, self.plan.total)
        remaining = max(0, self.plan.total - done)
        return {
            "mode": self.plan.mode, "state": self.state, "total": self.plan.total, "done": done,
            "remaining": remaining, "checked": self.checked, "skipped": self.skipped,
            "requests": self.requests, "retries": self.retried, "rate": round(rate, 2),
            "elapsed": elapsed, "eta": remaining * self.limiter.delay,
            "backoff": round(self.limiter.backoff_remaining, 1),
            "delay": round(self.limiter.delay, 2), "rate_limited": self.limiter.total_429,
            "counts": dict(self.counts), "current": self.current,
            "hits": [{"name": n, "status": s, "at": t} for n, s, t in self.hits],
        }
