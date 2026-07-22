from models.product import ProductSnapshot
from presenters.product_card import ProductCardView, render_product_card


LABELS = {
    "current_price": "Current",
    "mode": "Mode",
    "subscription_card_next": "Next",
    "price_alert_label": "Target",
    "product_basket_price": "In cart",
    "product_reviews": "Reviews: {count}",
    "product_seller": "Seller",
    "product_in_stock": "In stock",
    "product_out_of_stock": "Out of stock",
    "product_brand": "Brand",
    "product_category": "Category",
    "product_variants": "Variant",
    "product_delivery": "Delivery",
    "product_free_shipping": "Free shipping",
    "product_characteristics": "Key features",
    "product_updated": "Updated",
    "product_details_unavailable": "Details unavailable",
}


def _tr(key: str) -> str:
    return LABELS[key]


def _view(snapshot=None) -> ProductCardView:
    return ProductCardView(
        subscription_label="№ 2",
        title="Saved product",
        url="https://www.trendyol.com/brand/product-p-1",
        status_icon="✅",
        status_text="Active",
        current_price=1200.0,
        mode_text="Discount only",
        next_notification="after a price drop",
        unknown_price_text="Unknown",
        price_alert=1000.0,
        snapshot=snapshot,
    )


def test_compact_card_is_useful_without_enriched_snapshot():
    text = render_product_card(_view(), _tr)

    assert "Saved product" in text
    assert "1 200 TL" in text
    assert "Discount only" in text
    assert "1 000 TL" in text
    assert "Seller" not in text
    assert "Details unavailable" not in text


def test_compact_card_shows_decision_fields_and_escapes_dynamic_values():
    snapshot = ProductSnapshot(
        price=900.0,
        old_price=1200.0,
        basket_price=850.0,
        discount_percent=25.0,
        currency="TL",
        title="Phone <Pro>",
        rating=4.8,
        review_count=250,
        seller="Store & Co",
        seller_rating=9.4,
        in_stock=False,
    )

    text = render_product_card(_view(snapshot), _tr)

    assert "Phone &lt;Pro&gt;" in text
    assert "<s>1 200 TL</s> → <b>900 TL</b> · −25.0%" in text
    assert "In cart" in text and "850 TL" in text
    assert "4.8" in text and "Reviews: 250" in text
    assert "Store &amp; Co" in text
    assert "Out of stock" in text


def test_expanded_card_keeps_only_high_value_details_and_fits_caption():
    snapshot = ProductSnapshot(
        price=900.0,
        title="Phone",
        brand="Brand",
        category="Smartphones",
        category_path=("Electronics", "Phones", "Smartphones"),
        selected_variants={"Color": "Blue", "Memory": "256 GB"},
        delivery="Ships today",
        free_shipping=True,
        in_stock=True,
        attributes={f"Feature {index}": f"Value {index}" for index in range(10)},
        fetched_at=1_700_000_000,
    )

    text = render_product_card(_view(snapshot), _tr, expanded=True)

    assert "Brand" in text
    assert "Electronics › Phones › Smartphones" in text
    assert "Color: Blue · Memory: 256 GB" in text
    assert "Ships today · Free shipping" in text
    assert "Feature 0" in text and "Feature 3" in text
    assert "Feature 4" not in text
    assert len(text) <= 1000


def test_compact_and_expanded_cards_bound_unusually_long_scraped_values():
    snapshot = ProductSnapshot(
        price=1e100,
        old_price=2e100,
        basket_price=9e99,
        title="T" * 2_000,
        rating=4.9,
        review_count=999_999,
        seller="S" * 2_000,
        seller_rating=9.9,
        in_stock=False,
        brand="B" * 2_000,
        category_path=("C" * 2_000,),
        attributes={"A" * 500: "V" * 2_000},
    )

    compact = render_product_card(_view(snapshot), _tr)
    expanded = render_product_card(_view(snapshot), _tr, expanded=True)

    assert "Out of stock" in compact
    assert len(compact) <= 1000
    assert len(expanded) <= 1000
