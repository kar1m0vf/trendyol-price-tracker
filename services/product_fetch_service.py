"""Cached and request-coalesced product snapshot loading."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import asdict, dataclass, replace
import time
from typing import Awaitable, Callable, Dict, Optional, Tuple, Union
from urllib.parse import urlsplit, urlunsplit

from models.product import ProductSnapshot


LegacyProductResult = Tuple[Optional[float], Optional[str], Optional[str]]
ProductFetcher = Callable[
    [str],
    Awaitable[Union[ProductSnapshot, LegacyProductResult]],
]


@dataclass
class ProductFetchMetrics:
    requests: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    coalesced_requests: int = 0
    successful_fetches: int = 0
    empty_fetches: int = 0
    failed_fetches: int = 0
    evictions: int = 0


@dataclass(frozen=True)
class _CacheEntry:
    snapshot: ProductSnapshot
    expires_at: float


def canonical_product_url(url: str) -> str:
    """Normalize harmless URL differences without changing seller context."""
    raw = str(url or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
        if not parsed.scheme or not parsed.netloc:
            return raw.rstrip("/")
        path = parsed.path.rstrip("/") or "/"
        return urlunsplit(
            (
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                path,
                parsed.query,
                "",
            )
        )
    except Exception:
        return raw.rstrip("/")


class ProductFetchService:
    """Load product snapshots while avoiding duplicate external requests."""

    def __init__(
        self,
        fetcher: ProductFetcher,
        *,
        ttl_seconds: int = 15 * 60,
        negative_ttl_seconds: int = 60,
        max_entries: int = 2000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._fetcher = fetcher
        self._ttl_seconds = max(1, int(ttl_seconds))
        self._negative_ttl_seconds = max(1, int(negative_ttl_seconds))
        self._max_entries = max(1, int(max_entries))
        self._clock = clock
        self._cache: "OrderedDict[str, _CacheEntry]" = OrderedDict()
        self._inflight: Dict[str, asyncio.Task[ProductSnapshot]] = {}
        self._lock = asyncio.Lock()
        self._metrics = ProductFetchMetrics()

    async def get(self, url: str, *, force_refresh: bool = False) -> ProductSnapshot:
        """Return a snapshot, sharing an in-flight fetch for identical URLs."""
        key = canonical_product_url(url)
        if not key:
            raise ValueError("Product URL is empty")

        async with self._lock:
            self._metrics.requests += 1
            now = self._clock()
            entry = self._cache.get(key)
            if entry is not None and entry.expires_at <= now:
                self._cache.pop(key, None)
                entry = None

            if entry is not None and not force_refresh:
                self._cache.move_to_end(key)
                self._metrics.cache_hits += 1
                return entry.snapshot

            task = self._inflight.get(key)
            if task is not None:
                self._metrics.coalesced_requests += 1
            else:
                self._metrics.cache_misses += 1
                task = asyncio.create_task(self._load_and_cache(key))
                self._inflight[key] = task

        try:
            return await asyncio.shield(task)
        finally:
            if task.done():
                async with self._lock:
                    if self._inflight.get(key) is task:
                        self._inflight.pop(key, None)

    async def _load_and_cache(self, url: str) -> ProductSnapshot:
        try:
            raw_result = await self._fetcher(url)
            snapshot = self._coerce_snapshot(url, raw_result)
        except Exception:
            async with self._lock:
                self._metrics.failed_fetches += 1
            raise

        async with self._lock:
            if snapshot.has_core_data:
                ttl = self._ttl_seconds
                self._metrics.successful_fetches += 1
            else:
                ttl = self._negative_ttl_seconds
                self._metrics.empty_fetches += 1

            self._cache[url] = _CacheEntry(
                snapshot=snapshot,
                expires_at=self._clock() + ttl,
            )
            self._cache.move_to_end(url)
            while len(self._cache) > self._max_entries:
                self._cache.popitem(last=False)
                self._metrics.evictions += 1
        return snapshot

    async def peek(self, url: str) -> Optional[ProductSnapshot]:
        """Return a fresh cached snapshot without starting an external request."""
        key = canonical_product_url(url)
        if not key:
            return None

        async with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            if entry.expires_at <= self._clock():
                self._cache.pop(key, None)
                return None
            self._cache.move_to_end(key)
            return entry.snapshot

    @staticmethod
    def _coerce_snapshot(
        url: str,
        result: Union[ProductSnapshot, LegacyProductResult],
    ) -> ProductSnapshot:
        if isinstance(result, ProductSnapshot):
            if result.url == url:
                return result
            return replace(result, url=url)

        price, title, image = result
        return ProductSnapshot(
            url=url,
            price=price,
            title=title,
            image=image,
        )

    async def clear(self) -> None:
        """Drop cached entries without cancelling active external requests."""
        async with self._lock:
            self._cache.clear()

    def metrics_snapshot(self) -> Dict[str, int]:
        """Return cumulative counters suitable for logs and health output."""
        return {key: int(value) for key, value in asdict(self._metrics).items()}
