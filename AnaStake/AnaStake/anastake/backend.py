"""AvailabilityBackend interface, response mapping and the HTTP implementation."""
from __future__ import annotations

import abc
import email.utils
import json
import time
from dataclasses import dataclass

from . import config

TAKEN, NOT_FOUND, VERIFIED, BLOCKED, ERROR = (
    "TAKEN", "NOT_FOUND", "VERIFIED_AVAILABLE", "BLOCKED", "ERROR")
HITS = (NOT_FOUND, VERIFIED)


class RateLimited(Exception):
    def __init__(self, retry_after: float | None = None):
        super().__init__("429")
        self.retry_after = retry_after


class Transient(Exception):
    """Network error or timeout; worth retrying."""


@dataclass
class Result:
    status: str
    detail: str = ""


def _json_object(body: str) -> dict:
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def map_lookup(status: int, body: str, name: str) -> Result:
    meaning = config.LOOKUP_STATUS_MAP.get(status)
    data = _json_object(body)
    if meaning == TAKEN and data.get("id") and str(data.get("name", "")).lower() == name.lower():
        return Result(TAKEN)
    if meaning == NOT_FOUND and any(k in data for k in config.NOT_FOUND_BODY_KEYS):
        return Result(NOT_FOUND)
    return Result(ERROR, f"unrecognised lookup response (HTTP {status})")


def map_verify(status: int, body: str) -> Result:
    meaning = config.VERIFY_BODY_MAP.get(str(_json_object(body).get("status")))
    if status == 200 and meaning:
        return Result(meaning)
    return Result(ERROR, f"unrecognised verify response (HTTP {status})")


def parse_retry_after(value: str | None, now: float | None = None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(value).timestamp()
    except (TypeError, ValueError):
        return None
    return max(0.0, when - (time.time() if now is None else now))


class AvailabilityBackend(abc.ABC):
    can_verify = False

    @abc.abstractmethod
    async def lookup(self, name: str) -> Result: ...

    async def verify(self, name: str) -> Result:
        raise NotImplementedError("this backend has no verifier")

    async def close(self) -> None:
        return None


class MojangBackend(AvailabilityBackend):
    def __init__(self, token: str | None = None):
        import aiohttp

        self._aiohttp = aiohttp
        self._token = token
        self.can_verify = bool(token)
        self._session = None

    async def _get(self, url: str, headers: dict) -> tuple[int, str]:
        aiohttp = self._aiohttp
        if self._session is None:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=config.TIMEOUT_SECONDS))
        try:
            async with self._session.get(url, headers=headers, allow_redirects=False) as r:
                if r.status == 429:
                    raise RateLimited(parse_retry_after(r.headers.get("Retry-After")))
                return r.status, await r.text()
        except (aiohttp.ClientError, TimeoutError, UnicodeError) as exc:
            raise Transient(type(exc).__name__) from None

    async def lookup(self, name: str) -> Result:
        status, body = await self._get(config.LOOKUP_URL.format(name=name), config.HEADERS)
        return map_lookup(status, body, name)

    async def verify(self, name: str) -> Result:
        headers = {**config.HEADERS, "Authorization": f"Bearer {self._token}"}
        status, body = await self._get(config.VERIFY_URL.format(name=name), headers)
        return map_verify(status, body)

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None
