import asyncio

import pytest

from models.product import ProductSnapshot
from services.product_fetch_service import ProductFetchService, canonical_product_url


def test_product_snapshot_supports_progressive_card_fields():
    snapshot = ProductSnapshot(
        url="https://www.trendyol.com/brand/product-p-1",
        price=1200.0,
        title="Product",
        brand="Brand",
        rating=4.8,
        review_count=250,
        seller="Store",
        attributes={"memory": "256 GB"},
    )

    assert snapshot.current_price == 1200.0
    assert snapshot.has_core_data is True
    assert snapshot.attributes["memory"] == "256 GB"


def test_canonical_product_url_preserves_query_and_removes_harmless_differences():
    assert canonical_product_url(
        " HTTPS://WWW.TRENDYOL.COM/brand/product-p-1/?merchantId=7#details "
    ) == "https://www.trendyol.com/brand/product-p-1?merchantId=7"


@pytest.mark.asyncio
async def test_product_fetch_service_caches_identical_urls():
    calls = 0

    async def fetch(url):
        nonlocal calls
        calls += 1
        return 100.0, "Product", "https://example.com/image.jpg"

    service = ProductFetchService(fetch, ttl_seconds=300)

    first = await service.get("https://www.trendyol.com/brand/product-p-1/")
    second = await service.get("https://www.trendyol.com/brand/product-p-1")

    assert first == second
    assert first.url == "https://www.trendyol.com/brand/product-p-1"
    assert calls == 1
    assert service.metrics_snapshot() == {
        "requests": 2,
        "cache_hits": 1,
        "cache_misses": 1,
        "coalesced_requests": 0,
        "successful_fetches": 1,
        "empty_fetches": 0,
        "failed_fetches": 0,
        "evictions": 0,
    }


@pytest.mark.asyncio
async def test_product_fetch_service_coalesces_concurrent_requests():
    calls = 0
    release = asyncio.Event()

    async def fetch(url):
        nonlocal calls
        calls += 1
        await release.wait()
        return ProductSnapshot(url=url, price=200.0, title="Shared")

    service = ProductFetchService(fetch)
    tasks = [
        asyncio.create_task(service.get("https://www.trendyol.com/brand/shared-p-2"))
        for _ in range(5)
    ]
    await asyncio.sleep(0)
    release.set()

    snapshots = await asyncio.gather(*tasks)

    assert calls == 1
    assert all(snapshot.price == 200.0 for snapshot in snapshots)
    metrics = service.metrics_snapshot()
    assert metrics["requests"] == 5
    assert metrics["cache_misses"] == 1
    assert metrics["coalesced_requests"] == 4


@pytest.mark.asyncio
async def test_product_fetch_service_uses_short_negative_ttl():
    calls = 0
    now = [0.0]

    async def fetch(_url):
        nonlocal calls
        calls += 1
        return None, None, None

    service = ProductFetchService(
        fetch,
        ttl_seconds=300,
        negative_ttl_seconds=10,
        clock=lambda: now[0],
    )

    await service.get("https://www.trendyol.com/brand/missing-p-3")
    await service.get("https://www.trendyol.com/brand/missing-p-3")
    assert calls == 1

    now[0] = 11.0
    await service.get("https://www.trendyol.com/brand/missing-p-3")

    assert calls == 2
    assert service.metrics_snapshot()["empty_fetches"] == 2


@pytest.mark.asyncio
async def test_product_fetch_service_force_refresh_and_failure_metrics():
    calls = 0

    async def fetch(url):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError("network failed")
        return ProductSnapshot(url=url, price=float(calls))

    service = ProductFetchService(fetch)
    url = "https://www.trendyol.com/brand/refresh-p-4"

    assert (await service.get(url)).price == 1.0
    assert (await service.get(url, force_refresh=True)).price == 2.0
    with pytest.raises(RuntimeError, match="network failed"):
        await service.get(url, force_refresh=True)

    metrics = service.metrics_snapshot()
    assert metrics["successful_fetches"] == 2
    assert metrics["failed_fetches"] == 1
