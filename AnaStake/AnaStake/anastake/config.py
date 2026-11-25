"""Every endpoint, header, timeout and status mapping lives here.

UNVERIFIED: URLs, status codes and body shapes below are assumptions that must
be confirmed against the live API. Edit the mappings if reality differs.
"""
from __future__ import annotations

LOOKUP_URL = "https://api.minecraftservices.com/minecraft/profile/lookup/name/{name}"
VERIFY_URL = "https://api.minecraftservices.com/minecraft/profile/name/{name}/available"
HEADERS = {"Accept": "application/json", "User-Agent": "AnaStake/1.0"}
TIMEOUT_SECONDS = 10.0

TOKEN_ENV = "ANASTAKE_TOKEN"
WEBHOOK_ENV = "ANASTAKE_WEBHOOK"

# HTTP status -> meaning. Anything not listed is ERROR.
LOOKUP_STATUS_MAP = {200: "TAKEN", 404: "NOT_FOUND"}
# A mapped 404 must also carry a JSON object with one of these keys, so that a
# wrong URL or an HTML error page is not read as a free name.
NOT_FOUND_BODY_KEYS = ("errorMessage", "error", "path")
# Body "status" value of a 200 from the verify endpoint.
VERIFY_BODY_MAP = {"AVAILABLE": "VERIFIED_AVAILABLE", "DUPLICATE": "TAKEN",
                   "NOT_ALLOWED": "BLOCKED"}

DEFAULT_CONCURRENCY = 2
DEFAULT_DELAY = 1.0          # seconds between request starts, all workers
MIN_DELAY = 0.2
MAX_DELAY = 30.0
NETWORK_RETRIES = 3
BACKOFF_BASE = 2.0
BACKOFF_CAP = 300.0
SLOWDOWN_AFTER_429 = 3       # consecutive 429s before the rate is halved
CONFIRM_THRESHOLD = 100_000
HISTORY_MAX_AGE_HOURS = 24.0
WEBHOOK_BATCH_SECONDS = 10.0
