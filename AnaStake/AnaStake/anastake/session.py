"""Shared wiring used by both the terminal and the web front end."""
from __future__ import annotations

import os
from dataclasses import dataclass

from . import config
from .backend import MojangBackend
from .generators import Plan
from .output import Webhook, Writer
from .ratelimit import Limiter
from .runner import Runner
from .store import Store


@dataclass
class Settings:
    concurrency: int = config.DEFAULT_CONCURRENCY
    delay: float = config.DEFAULT_DELAY
    verify: bool = False
    ignore_history: bool = False
    max_age: float = config.HISTORY_MAX_AGE_HOURS
    db: str = "anastake.db"
    out: str = "."
    confirm_above: int = config.CONFIRM_THRESHOLD


def estimate(total: int, delay: float) -> float:
    """Lower bound in seconds; verification and retries add requests."""
    return total * max(delay, config.MIN_DELAY)


def fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    days, seconds = divmod(seconds, 86400)
    h, seconds = divmod(seconds, 3600)
    m, s = divmod(seconds, 60)
    return (f"{days}d " if days else "") + f"{h:02d}:{m:02d}:{s:02d}"


async def execute(plan: Plan, settings: Settings, on_ready) -> Runner:
    token = os.environ.get(config.TOKEN_ENV) or None
    if settings.verify and not token:
        raise ValueError(f"--verify needs the {config.TOKEN_ENV} environment variable")
    backend = MojangBackend(token if settings.verify else None)
    store, writer = Store(settings.db), Writer(settings.out)
    url = os.environ.get(config.WEBHOOK_ENV)
    webhook = Webhook(url, config.WEBHOOK_BATCH_SECONDS) if url else None
    runner = Runner(plan, backend, store, writer, Limiter(settings.delay),
                    concurrency=settings.concurrency, verify=settings.verify,
                    max_age_hours=settings.max_age, ignore_history=settings.ignore_history,
                    webhook=webhook)
    try:
        if webhook:
            webhook.start()
        on_ready(runner)
        await runner.run()
    finally:
        if webhook:
            await webhook.close()
        await backend.close()
        writer.close()
        store.close()
    return runner
