import pytest
import asyncio
import time
from bot import (
    _parse_kv_floats,
    normalize_url,
    is_trendyol_product_url,
    convert_to_turkish_url,
    parse_date_flexible,
    safe_ts_to_iso
)
from datetime import datetime


def test_parse_kv_floats():
    s = "min: 100,5 max:200 percent: 10%"
    res = _parse_kv_floats(s)
    assert isinstance(res, dict)
    assert res.get('min') == pytest.approx(100.5)
    assert res.get('max') == pytest.approx(200.0)
    assert res.get('percent') == pytest.approx(10.0)


def test_normalize_url_and_trailing():
    assert normalize_url('https://example.com/path/?q=1#frag') == 'https://example.com/path'
    assert normalize_url('https://example.com/path/') == 'https://example.com/path'
    assert normalize_url('') == ''


def test_is_trendyol_product_url():
    assert is_trendyol_product_url('https://www.trendyol.com/product/p/12345')
    assert is_trendyol_product_url('https://www.trendyol.com/x-p-12345')
    assert not is_trendyol_product_url('https://example.com/p-123')
    assert not is_trendyol_product_url(None)


def test_convert_to_turkish_url():
    assert convert_to_turkish_url('https://www.trendyol.com/en/p/123') == 'https://www.trendyol.com/p/123'
    assert convert_to_turkish_url('https://www.trendyol.com/p/123') == 'https://www.trendyol.com/p/123'


def test_parse_date_flexible():
    d = parse_date_flexible('20.09.2025')
    assert isinstance(d, datetime)
    assert d.year == 2025
    d2 = parse_date_flexible('2025-09-20 14:30:00')
    assert isinstance(d2, datetime)
    assert d2.hour == 14
    assert parse_date_flexible('not a date') is None


def test_safe_ts_to_iso():
    assert safe_ts_to_iso(None) == ''
    now = int(time.time())
    iso = safe_ts_to_iso(now)
    assert 'T' in iso
    s = safe_ts_to_iso('20.09.2025')
    assert '2025' in s
    assert safe_ts_to_iso('not-a-date') == 'not-a-date'
