"""Live result files and the batched Discord webhook."""
from __future__ import annotations

import asyncio
import csv
from datetime import datetime, timezone
from pathlib import Path

from .backend import ERROR, HITS


class Writer:
    def __init__(self, directory: str = "."):
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        available = root / "available.txt"
        self.known = set(available.read_text().split()) if available.exists() else set()
        self.available = available.open("a", encoding="utf-8")
        results = root / "results.csv"
        new = not results.exists() or results.stat().st_size == 0
        self.results = results.open("a", encoding="utf-8", newline="")
        self.csv = csv.writer(self.results)
        if new:
            self.csv.writerow(["name", "status", "timestamp", "mode"])
        self.errors = (root / "errors.txt").open("a", encoding="utf-8")

    def write(self, name: str, status: str, mode: str, detail: str = "") -> None:
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.csv.writerow([name, status, stamp, mode])
        if status in HITS and name not in self.known:
            self.known.add(name)
            self.available.write(name + "\n")
        if status == ERROR:
            self.errors.write(f"{name}\t{detail}\t{stamp}\n")
        for f in (self.available, self.results, self.errors):
            f.flush()

    def close(self) -> None:
        for f in (self.available, self.results, self.errors):
            f.close()


class Webhook:
    def __init__(self, url: str, interval: float):
        self.url, self.interval = url, interval
        self.pending: list[str] = []
        self._done = asyncio.Event()
        self._task: asyncio.Task | None = None

    def add(self, name: str, status: str) -> None:
        label = "verified" if status == "VERIFIED_AVAILABLE" else "likely available"
        self.pending.append(f"`{name}` {label}")

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        import aiohttp

        from .backend import parse_retry_after

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            failures = 0
            while True:
                try:
                    await asyncio.wait_for(self._done.wait(), self.interval)
                except TimeoutError:
                    pass
                if self.pending:
                    batch = self.pending[:30]
                    try:
                        async with session.post(self.url, json={
                                "content": "\n".join(batch),
                                "allowed_mentions": {"parse": []}}) as r:
                            if r.status < 300:
                                del self.pending[:len(batch)]
                                failures = 0
                            else:
                                failures += 1
                                wait = parse_retry_after(r.headers.get("Retry-After"))
                                await asyncio.sleep(min(wait or 5.0, 60.0))
                    except (aiohttp.ClientError, TimeoutError, ValueError):
                        failures += 1  # the URL is a secret: never log it
                if self._done.is_set() and (not self.pending or failures >= 3):
                    return

    async def close(self) -> None:
        self._done.set()
        if self._task:
            await asyncio.gather(self._task, return_exceptions=True)
