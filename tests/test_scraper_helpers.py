import logging

import pytest
from bs4 import BeautifulSoup
import scraper


def test_try_parse_html_table_history_parses_pairs():
    html = '''
    <div class="price-history">
        <table>
            <tr><td>20.09.2025</td><td>3.000 TL</td></tr>
            <tr><td>21.09.2025</td><td>2.900 TL</td></tr>
        </table>
    </div>
    '''
    soup = BeautifulSoup(html, "html.parser")
    res = scraper._try_parse_html_table_history(soup)
    assert res is not None
    assert isinstance(res, list)
    assert len(res) == 2
    assert res[0][1] == pytest.approx(3000.0)


class DummyResponse:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code


def test_find_similar_products_filters_same_id(monkeypatch):
                                                                                      
                                                           
    search_html = '''
    <a href="https://www.trendyol.com/p-12345">Product A</a>
    <a href="https://www.trendyol.com/p-99999">Product B</a>
    '''
    monkeypatch.setattr(scraper, 'SCRAPER', None)

    class DummyReq:
        @staticmethod
        def get(url, headers=None, timeout=15):
            return DummyResponse(search_html)

    monkeypatch.setattr(scraper, 'requests', DummyReq)

    res = scraper.find_similar_products("Some product", "https://www.trendyol.com/x/p-12345", limit=5)
    assert isinstance(res, list)
                                             
    urls = {r['url'] for r in res}
    assert "https://www.trendyol.com/x/p-12345" not in urls


def test_get_price_logs_404_as_warning(monkeypatch, caplog):
    class DummyLimiter:
        def can_proceed(self):
            return True

        def add_request(self):
            return None

    class DummyReq:
        @staticmethod
        def get(url, headers=None, timeout=20):
            return DummyResponse("", status_code=404)

    monkeypatch.setattr(scraper, "SCRAPER", None)
    monkeypatch.setattr(scraper, "requests", DummyReq)
    monkeypatch.setattr(scraper, "TRENDYOL_LIMITER", DummyLimiter())

    with caplog.at_level(logging.WARNING, logger="scraper"):
        assert scraper.get_price("https://www.trendyol.com/missing-p-1") is None

    matching_records = [
        record for record in caplog.records
        if record.name == "scraper" and "HTTP 404" in record.message
    ]
    assert matching_records
    assert all(record.levelno == logging.WARNING for record in matching_records)
