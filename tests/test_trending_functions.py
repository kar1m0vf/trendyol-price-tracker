                      
"""
Комплексные тесты для функций трендов в scraper.py
"""
import sys
import os
import asyncio
from unittest.mock import patch, MagicMock
from typing import List, Tuple, Optional

                                      
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

                             
from scraper import (
    TRENDING_CACHE,
    clean_trending_title,
    get_trending_all_top3,
    get_trending_by_search_top3,
    get_trending_by_category_top3,
    get_trending_all_top3_async,
    get_trending_by_search_top3_async,
    get_trending_by_category_top3_async,
    _extract_price_from_object,
    _fetch_first_working_listing,
    _get_trending_listing,
    _parse_listing_products
)


def test_clean_trending_title_removes_quick_view_label():
    title = clean_trending_title("Hızlı Bakış Roborock Q8 Akıllı Robot Süpürge")

    assert title == "Roborock Q8 Akıllı Robot Süpürge"


def test_clean_trending_title_removes_live_card_noise():
    title = clean_trending_title(
        "En Çok Satan 10. Ürün Samsung Galaxy Buds3 FE Bluetooth Kulaklık Siyah "
        "Var Var 4.9 ( 83 ) Azərbaycana Özəl Endirim Kargo Bedava əlavə endirim "
        "Azərbaycana Özəl Endirim -%6 163,97 ₼ 176,31 ₼ Sepete Ekle"
    )

    assert title == "Samsung Galaxy Buds3 FE Bluetooth Kulaklık Siyah"


def test_extract_price_from_nested_trendyol_listing_object():
    product = {
        "name": "Phone",
        "price": {
            "sellingPrice": {
                "value": 25999.9,
                "currency": "TRY",
            },
        },
    }

    assert _extract_price_from_object(product) == 25999.9


def test_extract_price_from_trendyol_price_text():
    product = {
        "name": "Phone",
        "priceInfo": {
            "discountedPriceText": "Sepette %10 indirim 163,97 ₼",
        },
    }

    assert _extract_price_from_object(product) == 163.97


def test_parse_listing_products_reads_nested_json_price():
    mock_html = '''
    <html>
    <script>
    window.__SEARCH_APP_INITIAL_STATE__ = {
        "products": [
            {
                "name": "Test Product",
                "brand": "Test Brand",
                "url": "/test-brand/test-product-p-123",
                "price": {"sellingPrice": {"value": 2599.99}}
            }
        ]
    };
    </script>
    </html>
    '''

    result = _parse_listing_products(mock_html, limit=3)

    assert result == [
        ("Test Brand Test Product", 2599.99, "https://www.trendyol.com/test-brand/test-product-p-123")
    ]


def test_parse_listing_products_reads_prc_card_price():
    mock_html = '''
    <html>
    <body>
        <div class="p-card-wrppr">
            <a href="/brand/product-p-123" title="Hızlı Bakış Product Name"></a>
            <div class="prc-box-dscntd">1.299,90 ₼</div>
        </div>
    </body>
    </html>
    '''

    result = _parse_listing_products(mock_html, limit=3)

    assert result == [
        ("Product Name", 1299.9, "https://www.trendyol.com/brand/product-p-123")
    ]


def test_parse_listing_products_does_not_reuse_first_price_for_multiple_links():
    mock_html = '''
    <html>
    <body>
        <div class="srch-prdcts">
            <div class="mixed-wrapper">
                <a href="/brand/first-p-111" title="First Product"></a>
                <span class="price">100 ₼</span>
                <a href="/brand/second-p-222" title="Second Product"></a>
                <span class="price">200 ₼</span>
            </div>
        </div>
    </body>
    </html>
    '''

    result = _parse_listing_products(mock_html, limit=3)

    assert result[:2] == [
        ("First Product", 100.0, "https://www.trendyol.com/brand/first-p-111"),
        ("Second Product", 200.0, "https://www.trendyol.com/brand/second-p-222"),
    ]


def test_parse_listing_products_reads_price_from_anchor_text():
    mock_html = '''
    <html>
    <body>
        <a href="/brand/first-p-111">
            En Çok Satan 1. Ürün First Product 4.9 ( 12 )
            Azərbaycana Özəl Endirim 100 ₼ Sepete Ekle
        </a>
        <a href="/brand/second-p-222">
            En Çok Satan 2. Ürün Second Product 4.8 ( 10 )
            Azərbaycana Özəl Endirim 200 ₼ Sepete Ekle
        </a>
    </body>
    </html>
    '''

    result = _parse_listing_products(mock_html, limit=3)

    assert result[:2] == [
        ("First Product", 100.0, "https://www.trendyol.com/brand/first-p-111"),
        ("Second Product", 200.0, "https://www.trendyol.com/brand/second-p-222"),
    ]


def test_get_trending_listing_fills_missing_prices_from_product_page():
    TRENDING_CACHE.clear()
    items = [
        ("First Product", None, "https://www.trendyol.com/brand/first-p-111"),
        ("Second Product", 200.0, "https://www.trendyol.com/brand/second-p-222"),
    ]

    with patch("scraper._fetch_first_working_listing", return_value=items), patch(
        "scraper.get_price",
        return_value=100.0,
    ) as get_price_mock:
        result = _get_trending_listing("test-fill-missing-prices", ["https://example.com"], limit=2)

    assert result == [
        ("First Product", 100.0, "https://www.trendyol.com/brand/first-p-111"),
        ("Second Product", 200.0, "https://www.trendyol.com/brand/second-p-222"),
    ]
    get_price_mock.assert_called_once_with("https://www.trendyol.com/brand/first-p-111")


def test_get_trending_all_top3():
    """Тест функции get_trending_all_top3"""
    print("🧪 Тестируем get_trending_all_top3...")

    try:
                                                         
        result = get_trending_all_top3()
        assert isinstance(result, list), f"Ожидался список, получен {type(result)}"

                                         
        for item in result:
            assert isinstance(item, tuple), f"Ожидался tuple, получен {type(item)}"
            assert len(item) == 3, f"Ожидался tuple из 3 элементов, получен {len(item)}"

            title, price, url = item
            assert isinstance(title, str), f"Title должен быть строкой, получен {type(title)}"
            assert price is None or isinstance(price, (int, float)), f"Price должен быть числом или None, получен {type(price)}"
            assert isinstance(url, str), f"URL должен быть строкой, получен {type(url)}"

        print(f"✅ get_trending_all_top3 вернул {len(result)} элементов")
        return True

    except Exception as e:
        print(f"❌ Ошибка в get_trending_all_top3: {e}")
        return False

def test_get_trending_by_search_top3():
    """Тест функции get_trending_by_search_top3"""
    print("🧪 Тестируем get_trending_by_search_top3...")

    try:
                                
        result_empty = get_trending_by_search_top3("")
        assert isinstance(result_empty, list), "Пустой запрос должен вернуть список"

                                 
        result = get_trending_by_search_top3("iphone")
        assert isinstance(result, list), f"Ожидался список, получен {type(result)}"

                                         
        for item in result:
            assert isinstance(item, tuple), f"Ожидался tuple, получен {type(item)}"
            assert len(item) == 3, f"Ожидался tuple из 3 элементов, получен {len(item)}"

        print(f"✅ get_trending_by_search_top3 вернул {len(result)} элементов")
        return True

    except Exception as e:
        print(f"❌ Ошибка в get_trending_by_search_top3: {e}")
        return False

def test_get_trending_by_category_top3():
    """Тест функции get_trending_by_category_top3"""
    print("🧪 Тестируем get_trending_by_category_top3...")

    try:
                                       
        categories = ["electronics", "clothing", "shoes", "home"]

        for category in categories:
            result = get_trending_by_category_top3(category)
            assert isinstance(result, list), f"Категория {category} должна вернуть список"

                                             
            for item in result:
                assert isinstance(item, tuple), f"Ожидался tuple, получен {type(item)}"
                assert len(item) == 3, f"Ожидался tuple из 3 элементов, получен {len(item)}"

                                       
        result_unknown = get_trending_by_category_top3("unknown")
        assert isinstance(result_unknown, list), "Неизвестная категория должна вернуть список"

        print("✅ get_trending_by_category_top3 работает корректно")
        return True

    except Exception as e:
        print(f"❌ Ошибка в get_trending_by_category_top3: {e}")
        return False

async def test_async_wrappers():
    """Тест асинхронных оберток для функций трендов"""
    print("🧪 Тестируем асинхронные обертки...")

    try:
                                          
        result_all = await get_trending_all_top3_async()
        assert isinstance(result_all, list), "get_trending_all_top3_async должен вернуть список"

                                                
        result_search = await get_trending_by_search_top3_async("test")
        assert isinstance(result_search, list), "get_trending_by_search_top3_async должен вернуть список"

                                                  
        result_cat = await get_trending_by_category_top3_async("electronics")
        assert isinstance(result_cat, list), "get_trending_by_category_top3_async должен вернуть список"

        print("✅ Асинхронные обертки работают корректно")
        return True

    except Exception as e:
        print(f"❌ Ошибка в асинхронных обертках: {e}")
        return False

def test_parse_listing_products():
    """Тест функции _parse_listing_products"""
    print("🧪 Тестируем _parse_listing_products...")

    try:
                            
        result_empty = _parse_listing_products("", limit=3)
        assert isinstance(result_empty, list), "Пустой HTML должен вернуть список"
        assert len(result_empty) == 0, "Пустой HTML должен вернуть пустой список"

                                  
        result_invalid = _parse_listing_products("<html><body>invalid</body></html>", limit=3)
        assert isinstance(result_invalid, list), "Некорректный HTML должен вернуть список"

                                    
        mock_html = '''
        <html>
        <script>
        window.__SEARCH_APP_INITIAL_STATE__ = {
            "products": [
                {
                    "name": "Test Product",
                    "brand": "Test Brand",
                    "url": "/p-test-product-p-123",
                    "price": {"value": 100.50}
                }
            ]
        };
        </script>
        </html>
        '''

        result_mock = _parse_listing_products(mock_html, limit=3)
        assert isinstance(result_mock, list), "Mock HTML должен вернуть список"

        print("✅ _parse_listing_products работает корректно")
        return True

    except Exception as e:
        print(f"❌ Ошибка в _parse_listing_products: {e}")
        return False

def test_fetch_first_working_listing():
    """Тест функции _fetch_first_working_listing"""
    print("🧪 Тестируем _fetch_first_working_listing...")

    try:
                                   
        result_empty = _fetch_first_working_listing([], limit=3)
        assert isinstance(result_empty, list), "Пустой список URL должен вернуть список"
        assert len(result_empty) == 0, "Пустой список URL должен вернуть пустой список"

        print("✅ _fetch_first_working_listing работает корректно")
        return True

    except Exception as e:
        print(f"❌ Ошибка в _fetch_first_working_listing: {e}")
        return False

def main():
    """Запуск всех тестов трендов"""
    print("=" * 60)
    print("🧪 ТЕСТИРОВАНИЕ ФУНКЦИЙ ТРЕНДОВ")
    print("=" * 60)

    results = []

                      
    tests = [
        test_get_trending_all_top3,
        test_get_trending_by_search_top3,
        test_get_trending_by_category_top3,
        test_parse_listing_products,
        test_fetch_first_working_listing,
    ]

    for test_func in tests:
        try:
            result = test_func()
            results.append(result)
        except Exception as e:
            print(f"❌ Критическая ошибка в {test_func.__name__}: {e}")
            results.append(False)

                       
    try:
        async_result = asyncio.run(test_async_wrappers())
        results.append(async_result)
    except Exception as e:
        print(f"❌ Критическая ошибка в асинхронных тестах: {e}")
        results.append(False)

           
    print("\n" + "=" * 60)
    passed = sum(results)
    total = len(results)

    if passed == total:
        print(f"🎉 Все тесты трендов прошли! ({passed}/{total})")
        return 0
    else:
        print(f"⚠️  Некоторые тесты трендов провалились: {passed}/{total}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
