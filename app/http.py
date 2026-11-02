"""Resilient JSON fetcher: SQLite cache, retries with backoff + jitter, stale-if-error.

Every response is stored under a short `ref` (hash of the full URL). Verdict reasons carry that
ref, so `GET /evidence/{ref}` can show the exact raw API response behind any claim.
"""
import asyncio
import hashlib
import json
import logging
import random
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .config import get_settings
from .db import db

log = logging.getLogger("jholokjatra.http")
RETRY_STATUS = {429, 500, 502, 503, 504}


class UpstreamError(Exception):
    """An external API failed after retries (and no stale cache was available)."""


@dataclass
class Fetched:
    url: str
    ref: str
    data: Any
    from_cache: bool
    fetched_at: float
    stale: bool = False


def make_ref(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:16]


def build_url(base: str, params: dict | None) -> str:
    clean = {k: v for k, v in (params or {}).items() if v is not None}
    return str(httpx.URL(base, params=clean))


def _cache_get(ref: str):
    with db() as c:
        return c.execute("SELECT body, fetched_at FROM http_cache WHERE key=?", (ref,)).fetchone()


def _cache_put(ref: str, url: str, body: str, ts: float) -> None:
    with db() as c:
        c.execute("INSERT OR REPLACE INTO http_cache(key,url,body,fetched_at) VALUES (?,?,?,?)", (ref, url, body, ts))


def get_raw(ref: str) -> dict | None:
    row = None
    with db() as c:
        row = c.execute("SELECT url, body, fetched_at FROM http_cache WHERE key=?", (ref,)).fetchone()
    if not row:
        return None
    return {"ref": ref, "url": row["url"], "fetched_at": row["fetched_at"], "body": json.loads(row["body"])}


async def fetch_json(
    client: httpx.AsyncClient,
    base_url: str,
    params: dict | None = None,
    *,
    ttl: int = 3600,
    headers: dict | None = None,
) -> Fetched:
    s = get_settings()
    url = build_url(base_url, params)
    ref = make_ref(url)

    row = await asyncio.to_thread(_cache_get, ref)
    if row and time.time() - row["fetched_at"] <= ttl:
        return Fetched(url, ref, json.loads(row["body"]), True, row["fetched_at"])

    last: Exception | None = None
    for attempt in range(max(1, s.http_retries)):
        try:
            resp = await client.get(url, headers=headers, timeout=s.http_timeout_s)
            if resp.status_code in RETRY_STATUS:
                raise httpx.HTTPStatusError(f"retryable {resp.status_code}", request=resp.request, response=resp)
            resp.raise_for_status()
            data = resp.json()
            now = time.time()
            await asyncio.to_thread(_cache_put, ref, url, resp.text, now)
            return Fetched(url, ref, data, False, now)
        except httpx.HTTPStatusError as exc:
            last = exc
            if exc.response.status_code not in RETRY_STATUS:
                break  # 4xx: retrying will not help
        except (httpx.TransportError, ValueError) as exc:
            last = exc
        if attempt < s.http_retries - 1:
            await asyncio.sleep(min(2**attempt + random.random() * 0.3, 8))

    if row:  # stale-if-error: better an old answer (clearly marked) than none
        log.warning("serving stale cache for %s after error: %s", url, last)
        return Fetched(url, ref, json.loads(row["body"]), True, row["fetched_at"], stale=True)
    raise UpstreamError(f"{base_url} failed: {last}")
