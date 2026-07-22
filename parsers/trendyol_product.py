"""Extract a stable product snapshot from a Trendyol product page.

The network client remains an owner-private runtime asset.  This module only
turns already-fetched HTML into the public domain model, which makes the
parser contract testable without sending requests to Trendyol.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup

from models.product import ProductSnapshot


_STATE_VARIABLES = (
    "window.__PRODUCT_DETAIL_APP_INITIAL_STATE__",
    "window.__INITIAL_STATE__",
    "window.__PRODUCT_INITIAL_STATE__",
    "__PRODUCT_DETAIL_APP_INITIAL_STATE__",
    "__INITIAL_STATE__",
)
_PRODUCT_ID_PATTERNS = (
    re.compile(r"-p-(\d+)(?:[/?#-]|$)", re.IGNORECASE),
    re.compile(r"/p/(\d+)(?:[/?#-]|$)", re.IGNORECASE),
)
_SPACE_RE = re.compile(r"\s+")
_CURRENCY_RE = re.compile(r"\b(TL|TRY|AZN)\b|[₺₼]", re.IGNORECASE)
_NUMBER_RE = re.compile(r"-?\d[\d\s.,]*")


def _clean_text(value: Any, *, max_length: int = 500) -> Optional[str]:
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return None
    text = _SPACE_RE.sub(" ", str(value).replace("\u00a0", " ")).strip()
    if not text:
        return None
    return text[:max_length]


def _parse_number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = _clean_text(value)
    if not text:
        return None
    match = _NUMBER_RE.search(text)
    if not match:
        return None
    raw = match.group(0).replace(" ", "")
    try:
        if "." in raw and "," in raw:
            if raw.rfind(",") > raw.rfind("."):
                raw = raw.replace(".", "").replace(",", ".")
            else:
                raw = raw.replace(",", "")
        elif "," in raw:
            tail = raw.rsplit(",", 1)[-1]
            raw = raw.replace(",", ".") if len(tail) in (1, 2) else raw.replace(",", "")
        elif "." in raw:
            tail = raw.rsplit(".", 1)[-1]
            if len(tail) not in (1, 2):
                raw = raw.replace(".", "")
        return float(raw)
    except (TypeError, ValueError):
        return None


def _parse_int(value: Any) -> Optional[int]:
    parsed = _parse_number(value)
    if parsed is None or parsed < 0:
        return None
    return int(parsed)


def _parse_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    text = (_clean_text(value) or "").casefold()
    if not text:
        return None
    if any(token in text for token in ("outofstock", "out_of_stock", "tükendi", "tukendi")):
        return False
    if any(token in text for token in ("instock", "in_stock", "stokta", "available")):
        return True
    if text in {"true", "yes", "evet", "var"}:
        return True
    if text in {"false", "no", "hayır", "hayir", "yok"}:
        return False
    return None


def _get_path(data: Any, *path: str) -> Any:
    current = data
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            return None
        current = current[key]
    return current


def _first(data: Any, paths: Sequence[Sequence[str]]) -> Any:
    for path in paths:
        value = _get_path(data, *path)
        if value is not None and value != "":
            return value
    return None


def _walk_dicts(value: Any, *, depth: int = 0) -> Iterator[Mapping[str, Any]]:
    if depth > 10:
        return
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from _walk_dicts(child, depth=depth + 1)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child, depth=depth + 1)


def _balanced_json_after(text: str, marker: str) -> Optional[Any]:
    """Read a JSON object assigned after *marker* without fragile regexes."""
    start_at = text.find(marker)
    if start_at < 0:
        return None
    assignment = text.find("=", start_at + len(marker))
    if assignment < 0:
        return None

    start = -1
    for index in range(assignment + 1, len(text)):
        if text[index] in "[{":
            start = index
            break
        if not text[index].isspace():
            return None
    if start < 0:
        return None

    opening = text[start]
    closing = "}" if opening == "{" else "]"
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : index + 1])
                except (TypeError, ValueError, json.JSONDecodeError):
                    return None
    return None


def _json_documents(html: str, soup: BeautifulSoup) -> List[Any]:
    documents: List[Any] = []
    for marker in _STATE_VARIABLES:
        document = _balanced_json_after(html, marker)
        if isinstance(document, (dict, list)):
            documents.append(document)

    for script in soup.find_all("script"):
        script_type = str(script.get("type") or "").casefold()
        script_id = str(script.get("id") or "").casefold()
        if "json" not in script_type and script_id != "__next_data__":
            continue
        try:
            document = json.loads(script.string or script.get_text() or "")
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(document, (dict, list)):
            documents.append(document)
    return documents


def _product_score(candidate: Mapping[str, Any]) -> int:
    keys = {str(key).casefold() for key in candidate}
    score = 0
    if keys & {"name", "title", "productname"}:
        score += 4
    if keys & {"id", "productid", "contentid"}:
        score += 3
    if keys & {"price", "sellingprice", "discountedprice", "offers"}:
        score += 3
    if keys & {"brand", "category", "attributes", "rating", "ratingscore", "aggregaterating"}:
        score += 2
    type_value = str(candidate.get("@type") or "").casefold()
    if type_value == "product":
        score += 8
    return score


def _select_product(documents: Iterable[Any]) -> Mapping[str, Any]:
    best: Mapping[str, Any] = {}
    best_score = -1
    for document in documents:
        if isinstance(document, Mapping) and isinstance(document.get("product"), Mapping):
            candidate = document["product"]
            score = _product_score(candidate) + 5
            if score > best_score:
                best, best_score = candidate, score
        for candidate in _walk_dicts(document):
            score = _product_score(candidate)
            if score > best_score:
                best, best_score = candidate, score
    return best


def _named_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _first(value, (("name",), ("value",), ("text",), ("label",)))
    if isinstance(value, list):
        parts = [_clean_text(_named_value(item), max_length=100) for item in value]
        return ", ".join(part for part in parts if part) or None
    return value


def _price_value(value: Any) -> Optional[float]:
    if isinstance(value, Mapping):
        value = _first(value, (("value",), ("amount",), ("price",), ("valueText",), ("text",)))
    parsed = _parse_number(value)
    return parsed if parsed is not None and 0 < parsed < 5_000_000 else None


def _extract_prices(product: Mapping[str, Any], fallback_price: Optional[float]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    price_node = product.get("price") if isinstance(product.get("price"), Mapping) else {}
    current = fallback_price or _price_value(
        _first(
            product,
            (
                ("sellingPrice",),
                ("currentPrice",),
                ("salePrice",),
                ("discountedPrice",),
                ("price",),
                ("offers", "price"),
                ("offers", "lowPrice"),
            ),
        )
    )
    if current is None:
        current = _price_value(
            _first(
                price_node,
                (("sellingPrice",), ("currentPrice",), ("discountedPrice",), ("value",)),
            )
        )

    old = _price_value(
        _first(
            product,
            (("originalPrice",), ("listPrice",), ("marketPrice",), ("price", "originalPrice"), ("price", "marketPrice")),
        )
    )
    basket = _price_value(
        _first(
            product,
            (("basketPrice",), ("campaignPrice",), ("price", "basketPrice"), ("price", "campaignPrice")),
        )
    )
    if old is not None and current is not None and old <= current:
        old = None
    return current, old, basket


def _extract_attributes(product: Mapping[str, Any]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    raw_groups = [
        product.get("attributes"),
        product.get("productAttributes"),
        product.get("attributeValues"),
    ]
    for raw in raw_groups:
        if isinstance(raw, Mapping):
            for key, value in raw.items():
                name = _clean_text(key, max_length=80)
                text = _clean_text(_named_value(value), max_length=160)
                if name and text:
                    result.setdefault(name, text)
        elif isinstance(raw, list):
            for item in raw:
                if not isinstance(item, Mapping):
                    continue
                name = _clean_text(
                    _named_value(_first(item, (("key",), ("attribute",), ("name",), ("label",)))),
                    max_length=80,
                )
                text = _clean_text(
                    _named_value(_first(item, (("value",), ("attributeValue",), ("values",), ("text",)))),
                    max_length=160,
                )
                if name and text:
                    result.setdefault(name, text)
        if len(result) >= 100:
            break
    return dict(list(result.items())[:100])


def _extract_variants(product: Mapping[str, Any]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    raw_variants = _first(
        product,
        (("selectedVariants",), ("selectedSlicingAttributes",), ("slicingAttributes",)),
    )
    if isinstance(raw_variants, Mapping):
        for key, value in raw_variants.items():
            name = _clean_text(key, max_length=60)
            text = _clean_text(_named_value(value), max_length=100)
            if name and text:
                result[name] = text
    elif isinstance(raw_variants, list):
        for item in raw_variants:
            if not isinstance(item, Mapping):
                continue
            selected = item.get("selected")
            if selected is False:
                continue
            name = _clean_text(
                _named_value(_first(item, (("attributeName",), ("name",), ("key",), ("label",)))),
                max_length=60,
            )
            text = _clean_text(
                _named_value(_first(item, (("attributeValue",), ("value",), ("selectedValue",)))),
                max_length=100,
            )
            if name and text:
                result[name] = text

    for key, label in (("color", "Renk"), ("size", "Beden"), ("capacity", "Kapasite")):
        text = _clean_text(_named_value(product.get(key)), max_length=100)
        if text:
            result.setdefault(label, text)
    return result


def _extract_category_path(product: Mapping[str, Any], soup: BeautifulSoup) -> Tuple[str, ...]:
    values: List[str] = []
    raw = _first(product, (("categoryPath",), ("breadcrumbs",), ("categoryHierarchy",)))
    if isinstance(raw, str):
        values.extend(part.strip() for part in re.split(r"[>/]", raw) if part.strip())
    elif isinstance(raw, list):
        for item in raw:
            text = _clean_text(_named_value(item), max_length=100)
            if text:
                values.append(text)

    if not values:
        for element in soup.select('[itemprop="itemListElement"] [itemprop="name"], nav[aria-label*="breadcrumb" i] a'):
            text = _clean_text(element.get("content") or element.get_text(" ", strip=True), max_length=100)
            if text:
                values.append(text)

    deduped: List[str] = []
    for value in values:
        if not deduped or deduped[-1].casefold() != value.casefold():
            deduped.append(value)
    return tuple(deduped[:12])


def _extract_product_id(product: Mapping[str, Any], url: str) -> Optional[str]:
    value = _first(product, (("id",), ("productId",), ("contentId",)))
    text = _clean_text(value, max_length=80)
    if text:
        return text
    for pattern in _PRODUCT_ID_PATTERNS:
        match = pattern.search(url)
        if match:
            return match.group(1)
    return None


def _extract_merchant_id(product: Mapping[str, Any], url: str) -> Optional[str]:
    query_value = parse_qs(urlsplit(url).query).get("merchantId", [None])[0]
    if query_value:
        return _clean_text(query_value, max_length=80)
    value = _first(
        product,
        (("merchant", "id"), ("seller", "id"), ("offers", "seller", "id"), ("merchantId",), ("sellerId",)),
    )
    return _clean_text(value, max_length=80)


def _extract_delivery(product: Mapping[str, Any], page_text: str) -> Optional[str]:
    value = _first(
        product,
        (("delivery",), ("deliveryInformation",), ("estimatedDelivery",), ("shipment", "description")),
    )
    text = _clean_text(_named_value(value), max_length=180)
    if text:
        return text
    patterns = (
        r"(Tahmini Kargoya Teslim:\s*[^\n.!]{1,100})",
        r"(en geç [^\n.!]{1,80} kargoda)",
    )
    for pattern in patterns:
        match = re.search(pattern, page_text, flags=re.IGNORECASE)
        if match:
            return _clean_text(match.group(1), max_length=180)
    return None


def _currency(product: Mapping[str, Any], soup: BeautifulSoup, page_text: str) -> Optional[str]:
    value = _first(
        product,
        (("currency",), ("currencyCode",), ("price", "currency"), ("offers", "priceCurrency")),
    )
    text = (_clean_text(value, max_length=12) or "").upper()
    if not text:
        meta = soup.find("meta", attrs={"property": "product:price:currency"})
        text = (_clean_text(meta.get("content") if meta else None, max_length=12) or "").upper()
    if text in {"TRY", "TL", "₺"}:
        return "TL"
    if text in {"AZN", "₼"}:
        return "AZN"
    match = _CURRENCY_RE.search(page_text)
    if match:
        symbol = match.group(0).upper()
        return "AZN" if symbol in {"AZN", "₼"} else "TL"
    return text or None


def parse_trendyol_product_snapshot(
    html: str,
    url: str,
    *,
    price: Optional[float] = None,
    title: Optional[str] = None,
    image: Optional[str] = None,
) -> ProductSnapshot:
    """Return normalized product and primary-offer fields from fetched HTML."""
    raw_html = html or ""
    soup = BeautifulSoup(raw_html, "html.parser")
    documents = _json_documents(raw_html, soup)
    product = _select_product(documents)
    page_text = soup.get_text("\n", strip=True)

    current_price, old_price, basket_price = _extract_prices(product, price)
    discount = _parse_number(
        _first(product, (("discountPercent",), ("discountRate",), ("price", "discountPercent")))
    )
    if discount is None and current_price and old_price and old_price > current_price:
        discount = round((old_price - current_price) / old_price * 100, 2)

    rating_node = _first(product, (("ratingScore",), ("aggregateRating",), ("rating",)))
    rating = _parse_number(
        _first(rating_node, (("averageRating",), ("ratingValue",), ("average",), ("score",)))
        if isinstance(rating_node, Mapping)
        else rating_node
    )
    review_count = _parse_int(
        _first(
            rating_node,
            (("totalCount",), ("reviewCount",), ("ratingCount",), ("count",)),
        )
        if isinstance(rating_node, Mapping)
        else _first(product, (("reviewCount",), ("ratingCount",)))
    )

    in_stock = _parse_bool(
        _first(product, (("inStock",), ("isInStock",), ("stock",), ("offers", "availability")))
    )
    if in_stock is None and re.search(r"Stoklar\s+Tükendi|Stokta\s+Yok", page_text, re.IGNORECASE):
        in_stock = False

    free_shipping = _parse_bool(
        _first(product, (("freeShipping",), ("isFreeShipping",), ("shipment", "freeShipping")))
    )
    if free_shipping is None and re.search(r"\bKargo\s+Bedava\b", page_text, re.IGNORECASE):
        free_shipping = True

    category_path = _extract_category_path(product, soup)
    brand = _clean_text(_named_value(product.get("brand")), max_length=120)
    category = _clean_text(_named_value(product.get("category")), max_length=120)
    if not category and category_path:
        category = category_path[-1]

    seller = _clean_text(
        _named_value(
            _first(product, (("merchant",), ("seller",), ("offers", "seller"), ("merchantName",), ("sellerName",)))
        ),
        max_length=160,
    )
    seller_rating = _parse_number(
        _first(
            product,
            (("merchant", "sellerScore"), ("merchant", "rating"), ("seller", "rating"), ("sellerScore",)),
        )
    )

    resolved_title = title or _clean_text(
        _first(product, (("name",), ("title",), ("productName",))),
        max_length=500,
    )
    resolved_image = image or _clean_text(
        _named_value(_first(product, (("image",), ("imageUrl",), ("images",)))),
        max_length=1000,
    )

    return ProductSnapshot(
        url=url,
        product_id=_extract_product_id(product, url),
        title=resolved_title,
        image=resolved_image,
        brand=brand,
        category=category,
        category_path=category_path,
        price=current_price,
        old_price=old_price,
        basket_price=basket_price,
        discount_percent=discount,
        currency=_currency(product, soup, page_text),
        in_stock=in_stock,
        rating=rating,
        review_count=review_count,
        question_count=_parse_int(_first(product, (("questionCount",), ("questions", "count")))),
        seller=seller,
        merchant_id=_extract_merchant_id(product, url),
        seller_rating=seller_rating,
        delivery=_extract_delivery(product, page_text),
        free_shipping=free_shipping,
        selected_variants=_extract_variants(product),
        attributes=_extract_attributes(product),
    )
