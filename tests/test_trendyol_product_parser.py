from pathlib import Path
from unittest.mock import MagicMock

import pytest

from parsers.trendyol_product import parse_trendyol_product_snapshot


FIXTURES = Path(__file__).parent / "fixtures" / "trendyol"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parses_electronics_product_and_primary_offer_fields():
    snapshot = parse_trendyol_product_snapshot(
        _fixture("electronics.html"),
        "https://www.trendyol.com/apple/iphone-p-985256863?merchantId=968",
        image="https://cdn.example/iphone.jpg",
    )

    assert snapshot.product_id == "985256863"
    assert snapshot.title == "Apple iPhone 17 256GB Ada Çayı"
    assert snapshot.brand == "Apple"
    assert snapshot.category == "Cep Telefonu"
    assert snapshot.category_path == (
        "Elektronik",
        "Cep Telefonu & Aksesuar",
        "Cep Telefonu",
    )
    assert snapshot.price == 77949.0
    assert snapshot.old_price == 79999.0
    assert snapshot.basket_price == 76949.0
    assert snapshot.discount_percent == 2.56
    assert snapshot.currency == "TL"
    assert snapshot.in_stock is True
    assert snapshot.rating == 4.6
    assert snapshot.review_count == 130
    assert snapshot.question_count == 48
    assert snapshot.seller == "Trendyol"
    assert snapshot.merchant_id == "968"
    assert snapshot.seller_rating == 9.3
    assert snapshot.delivery == "En geç bugün kargoda"
    assert snapshot.free_shipping is True
    assert snapshot.selected_variants == {"Renk": "Ada Çayı", "Dahili Hafıza": "256 GB"}
    assert snapshot.attributes["Garanti Tipi"] == "Apple Türkiye Garantili"
    assert snapshot.attributes["RAM Kapasitesi"] == "8 GB"


def test_parses_category_specific_clothing_attributes():
    snapshot = parse_trendyol_product_snapshot(
        _fixture("clothing.html"),
        "https://www.trendyol.com/olalook/dress-p-810287719",
    )

    assert snapshot.product_id == "810287719"
    assert snapshot.price == 899.9
    assert snapshot.old_price == 1099.9
    assert snapshot.discount_percent == pytest.approx(18.18, abs=0.01)
    assert snapshot.currency == "TL"
    assert snapshot.in_stock is True
    assert snapshot.seller == "olalook official"
    assert snapshot.merchant_id == "441"
    assert snapshot.selected_variants == {"Renk": "Siyah", "Beden": "M"}
    assert snapshot.attributes["Kumaş Tipi"] == "Triko"
    assert snapshot.attributes["Yıkama Talimatı"] == "Type 1"


def test_parses_schema_product_and_out_of_stock_state():
    snapshot = parse_trendyol_product_snapshot(
        _fixture("cosmetics.html"),
        "https://www.trendyol.com/cremika/cream-p-822729029",
    )

    assert snapshot.product_id == "822729029"
    assert snapshot.title == "Nemlendirici Yüz Kremi 50 ml"
    assert snapshot.brand == "Cremika"
    assert snapshot.category == "Yüz Kremi"
    assert snapshot.category_path == ("Bakım", "Cilt Bakımı", "Yüz Kremi")
    assert snapshot.price == 355.51
    assert snapshot.currency == "TL"
    assert snapshot.in_stock is False
    assert snapshot.rating == 4.8
    assert snapshot.review_count == 842
    assert snapshot.seller == "Cremika Store"
    assert snapshot.attributes == {
        "Cilt Tipi": "Tüm Cilt Tipleri",
        "İçerik": "Niacinamide",
        "Hacim": "50 ml",
    }


def test_query_merchant_context_wins_over_embedded_seller_id():
    snapshot = parse_trendyol_product_snapshot(
        _fixture("electronics.html"),
        "https://www.trendyol.com/apple/iphone-p-985256863?merchantId=777",
    )

    assert snapshot.seller == "Trendyol"
    assert snapshot.merchant_id == "777"


@pytest.mark.asyncio
async def test_owner_runtime_full_snapshot_uses_one_http_request(monkeypatch):
    import scraper

    response = MagicMock(status_code=200, text=_fixture("electronics.html"))
    client = MagicMock()
    client.get.return_value = response
    monkeypatch.setattr(scraper, "SCRAPER", client)

    snapshot = await scraper.get_product_snapshot_async(
        "https://www.trendyol.com/apple/iphone-p-985256863?merchantId=968"
    )

    assert client.get.call_count == 1
    assert snapshot.price == 77949.0
    assert snapshot.seller == "Trendyol"
    assert snapshot.attributes["RAM Kapasitesi"] == "8 GB"
