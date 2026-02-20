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
