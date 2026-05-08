import pytest
from datetime import datetime

import bot


def test_parse_kv_floats_basic():
    s = "min: 12.5 max: 99,99 percent: 10%"
    out = bot._parse_kv_floats(s)
    assert pytest.approx(out.get('min', 0.0), rel=1e-3) == 12.5
    assert pytest.approx(out.get('max', 0.0), rel=1e-3) == 99.99
    assert pytest.approx(out.get('percent', 0.0), rel=1e-3) == 10.0


def test_parse_kv_floats_missing_or_bad():
    assert bot._parse_kv_floats("") == {}
    assert bot._parse_kv_floats(None) == {}
    assert bot._parse_kv_floats("min: abc percent: 5%") == {'percent': 5.0}


def test_normalize_url_variants():
    assert bot.normalize_url("https://trendyol.com/p/123/") == "https://trendyol.com/p/123"
    assert bot.normalize_url("https://trendyol.com/p/123?utm=1#foo") == "https://trendyol.com/p/123"
    assert bot.normalize_url("   https://trendyol.com/p/123   ") == "https://trendyol.com/p/123"


def test_extract_supported_url_from_message():
    assert bot.extract_supported_url("check this https://ty.gl/abc123.") == "https://ty.gl/abc123"
    assert bot.extract_supported_url("ty.gl/abc123") == "https://ty.gl/abc123"
    assert (
        bot.extract_supported_url("Link: trendyol.com/brand/product-p-123?utm=1")
        == "https://trendyol.com/brand/product-p-123?utm=1"
    )


def test_is_trendyol_short_url():
    assert bot.is_trendyol_short_url("https://ty.gl/abc123")
    assert bot.is_trendyol_short_url("ty.gl/abc123")
    assert not bot.is_trendyol_short_url("https://example.com/abc123")
    assert not bot.is_trendyol_short_url("https://ty.gl/")


def test_extract_trendyol_product_redirect_url_from_select_country():
    redirect_url = (
        "https://www.trendyol.com/en/select-country?"
        "cb=/en/Cream-Co-/Leke-Karsiti-Nemlendirici-Yuz-Temizleme-Jeli-"
        "Niacinamide-Hya-p-885896576?boutiqueId=61&merchantId=556702"
    )

    extracted = bot.extract_trendyol_product_redirect_url(redirect_url)

    assert extracted == (
        "https://www.trendyol.com/en/Cream-Co-/Leke-Karsiti-Nemlendirici-"
        "Yuz-Temizleme-Jeli-Niacinamide-Hya-p-885896576?boutiqueId=61"
    )
    assert bot.is_trendyol_product_url(bot.normalize_url(bot.convert_to_turkish_url(extracted)))


@pytest.mark.asyncio
async def test_resolve_short_url_adds_scheme_and_follows_redirect(monkeypatch):
    requested_urls = []

    class FakeResponse:
        url = "https://www.trendyol.com/brand/product-p-123?utm=1"

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def get(self, url, **_kwargs):
            requested_urls.append(url)
            return FakeResponse()

    monkeypatch.setattr(bot.aiohttp, "ClientSession", lambda: FakeSession())

    result = await bot.resolve_short_url("ty.gl/abc123")

    assert requested_urls == ["https://ty.gl/abc123"]
    assert result == "https://www.trendyol.com/brand/product-p-123?utm=1"


@pytest.mark.asyncio
async def test_resolve_short_url_extracts_product_from_select_country(monkeypatch):
    class FakeResponse:
        url = (
            "https://www.trendyol.com/en/select-country?"
            "cb=/en/Cream-Co-/Leke-Karsiti-Nemlendirici-Yuz-Temizleme-Jeli-"
            "Niacinamide-Hya-p-885896576?boutiqueId=61&merchantId=556702"
        )

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def get(self, _url, **_kwargs):
            return FakeResponse()

    monkeypatch.setattr(bot.aiohttp, "ClientSession", lambda: FakeSession())

    result = await bot.resolve_short_url("https://ty.gl/xvwhn0s1vdvia")

    assert result.startswith("https://www.trendyol.com/Cream-Co-/")
    assert "-p-885896576" in result
    assert bot.is_trendyol_product_url(bot.normalize_url(result))


def test_is_trendyol_product_url_positive():
    assert bot.is_trendyol_product_url("https://www.trendyol.com/some-brand/p/12345")
    assert bot.is_trendyol_product_url("https://trendyol.com/en/some/p/abc-p-987")


def test_is_trendyol_product_url_negative():
    assert not bot.is_trendyol_product_url("")
    assert not bot.is_trendyol_product_url("https://trendyol.com/search?q=phone")
    assert not bot.is_trendyol_product_url("https://example.com/p/123")


def test_parse_date_flexible_various():
    assert bot.parse_date_flexible("20.09.2025 14:30:00") == datetime(2025, 9, 20, 14, 30, 0)
    assert bot.parse_date_flexible("20.09.2025") == datetime(2025, 9, 20)
    assert bot.parse_date_flexible("2025-09-20 14:30") == datetime(2025, 9, 20, 14, 30)
    assert bot.parse_date_flexible("09/20/2025") == datetime(2025, 9, 20)
    assert bot.parse_date_flexible("not a date") is None
