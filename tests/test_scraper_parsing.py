#!/usr/bin/env python3
"""
Комплексный тест функций парсинга в scraper.py
"""
import sys
import os
import asyncio
from unittest.mock import patch, MagicMock

# Добавляем корневую директорию в путь
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

def test_parse_price_text():
    """Тест функции parse_price_text"""
    print("🧪 Тестируем parse_price_text...")

    try:
        from scraper import parse_price_text

        test_cases = [
            ("1.234,56 TL", 1234.56),
            ("1,234.56 TL", 1234.56),
            ("1234.56", 1234.56),
            ("1234 TL", 1234.0),
            ("1.234 TL", 1234.0),
            ("1,234 TL", 1234.0),
            ("", None),
            ("цена не указана", None),
            ("NaN", None),
        ]

        passed = 0
        for input_text, expected in test_cases:
            result = parse_price_text(input_text)
            if result == expected or (result is None and expected is None):
                passed += 1
                print(f"  ✅ '{input_text}' -> {result}")
            else:
                print(f"  ❌ '{input_text}' -> {result} (ожидалось {expected})")

        print(f"Результат parse_price_text: {passed}/{len(test_cases)} тестов пройдено")
        return passed == len(test_cases)

    except Exception as e:
        print(f"❌ Ошибка в parse_price_text: {e}")
        return False

def test_extract_json_from_js_var():
    """Тест функции _extract_json_from_js_var"""
    print("🧪 Тестируем _extract_json_from_js_var...")

    try:
        from scraper import _extract_json_from_js_var

        # Тестовый HTML с JavaScript переменной
        html = '''
        <script>
        window.__PRODUCT_DETAIL_APP_INITIAL_STATE__ = {"product": {"price": 1234.56}};
        </script>
        '''

        result = _extract_json_from_js_var(html, 'window.__PRODUCT_DETAIL_APP_INITIAL_STATE__')
        expected = {"product": {"price": 1234.56}}

        if result == expected:
            print("✅ _extract_json_from_js_var работает корректно")
            return True
        else:
            print(f"❌ _extract_json_from_js_var: ожидалось {expected}, получено {result}")
            return False

    except Exception as e:
        print(f"❌ Ошибка в _extract_json_from_js_var: {e}")
        return False

async def test_get_price_async_with_mock():
    """Тест get_price_async с mock данными"""
    print("🧪 Тестируем get_price_async с mock...")

    try:
        from scraper import get_price_async

        # Mock ответа сервера
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '''
        <html>
        <script>
        window.__PRODUCT_DETAIL_APP_INITIAL_STATE__ = {
            "product": {
                "price": {"sellingPrice": {"value": 2599.99}}
            }
        };
        </script>
        </html>
        '''

        with patch('scraper.SCRAPER') as mock_scraper:
            mock_scraper.get.return_value = mock_response

            result = await get_price_async("https://trendyol.com/test-product-p-123")

            if result == 2599.99:
                print("✅ get_price_async с JavaScript парсингом работает")
                return True
            else:
                print(f"❌ get_price_async: ожидалось 2599.99, получено {result}")
                return False

    except Exception as e:
        print(f"❌ Ошибка в get_price_async: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_get_product_info_async_with_mock():
    """Тест get_product_info_async с mock данными"""
    print("🧪 Тестируем get_product_info_async с mock...")

    try:
        from scraper import get_product_info_async

        # Mock ответа сервера
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '''
        <html>
        <head>
            <title>iPhone 15 Pro Max - Trendyol</title>
            <meta property="og:image" content="https://cdn.trendyol.com/image1.jpg" />
        </head>
        <body>
            <script>
            window.__PRODUCT_DETAIL_APP_INITIAL_STATE__ = {
                "product": {
                    "name": "iPhone 15 Pro Max",
                    "price": {"sellingPrice": {"value": 45000.99}}
                }
            };
            </script>
        </body>
        </html>
        '''

        with patch('scraper.SCRAPER') as mock_scraper:
            mock_scraper.get.return_value = mock_response

            price, title, image = await get_product_info_async("https://trendyol.com/test-product-p-123")

            success = True
            if price != 45000.99:
                print(f"❌ Цена: ожидалось 45000.99, получено {price}")
                success = False
            if title != "iPhone 15 Pro Max":
                print(f"❌ Название: ожидалось 'iPhone 15 Pro Max', получено '{title}'")
                success = False
            if image != "https://cdn.trendyol.com/image1.jpg":
                print(f"❌ Изображение: ожидалось 'https://cdn.trendyol.com/image1.jpg', получено '{image}'")
                success = False

            if success:
                print("✅ get_product_info_async работает корректно")
                return True
            else:
                return False

    except Exception as e:
        print(f"❌ Ошибка в get_product_info_async: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_rate_limiters():
    """Тест rate limiter'ов"""
    print("🧪 Тестируем rate limiter'ы...")

    try:
        from scraper import TRENDYOL_LIMITER

        # Тест только синхронного limiter'а (асинхронный требует event loop)
        initial_can_proceed = TRENDYOL_LIMITER.can_proceed()
        if initial_can_proceed:
            TRENDYOL_LIMITER.add_request()
            print("✅ Синхронный rate limiter работает")
            return True
        else:
            print("❌ Синхронный rate limiter не работает")
            return False

    except Exception as e:
        print(f"❌ Ошибка в rate limiter'ах: {e}")
        return False

async def test_trendyol_url_validation():
    """Тест валидации URL Trendyol"""
    print("🧪 Тестируем валидацию URL Trendyol...")

    try:
        from bot import is_trendyol_product_url

        test_urls = [
            ("https://www.trendyol.com/test-product-p-123456", True),
            ("https://www.trendyol.com/test-product-p-123456/", True),
            ("https://trendyol.com/test-product-p-123456", True),
            ("https://m.trendyol.com/test-product-p-123456", True),
            ("https://www.trendyol.com/sr?q=iphone", False),  # Поиск, не товар
            ("https://amazon.com/product", False),  # Другой сайт
            ("not-a-url", False),  # Не URL
        ]

        passed = 0
        for url, expected in test_urls:
            result = is_trendyol_product_url(url)
            if result == expected:
                passed += 1
                print(f"  ✅ '{url[:50]}...' -> {result}")
            else:
                print(f"  ❌ '{url[:50]}...' -> {result} (ожидалось {expected})")

        print(f"Результат валидации URL: {passed}/{len(test_urls)} тестов пройдено")
        return passed == len(test_urls)

    except Exception as e:
        print(f"❌ Ошибка в валидации URL: {e}")
        return False

async def test_parsing_error_handling():
    """Тест обработки ошибок в парсинге"""
    print("🧪 Тестируем обработку ошибок в парсинге...")

    try:
        from scraper import get_price_async, get_product_info_async

        # Тест с несуществующим URL
        result1 = await get_price_async("https://non-existent-domain-12345.com/product")
        result2 = await get_product_info_async("https://non-existent-domain-12345.com/product")

        # Функции должны вернуть None при ошибках
        if result1 is None and result2[0] is None:
            print("✅ Обработка ошибок сети работает корректно")
            return True
        else:
            print(f"❌ Ожидалось (None, (None, None, None)), получено ({result1}, {result2})")
            return False

    except Exception as e:
        print(f"❌ Ошибка в обработке ошибок парсинга: {e}")
        return False

def test_scraper_initialization():
    """Тест инициализации scraper'а"""
    print("🧪 Тестируем инициализацию scraper'а...")

    try:
        from scraper import SCRAPER, HEADERS, TRENDYOL_LIMITER

        # Проверяем что основные компоненты инициализированы
        if HEADERS and isinstance(HEADERS, dict):
            print("✅ HEADERS инициализированы")
        else:
            print("❌ HEADERS не инициализированы")
            return False

        if TRENDYOL_LIMITER:
            print("✅ TRENDYOL_LIMITER инициализирован")
        else:
            print("❌ TRENDYOL_LIMITER не инициализирован")
            return False

        # SCRAPER может быть None, это нормально
        if SCRAPER is not None:
            print("✅ SCRAPER (cloudscraper) доступен")
        else:
            print("⚠️  SCRAPER не доступен (будет использоваться requests)")

        return True

    except Exception as e:
        print(f"❌ Ошибка в инициализации scraper'а: {e}")
        return False

async def test_fallback_parsing():
    """Тест fallback парсинга"""
    print("🧪 Тестируем fallback парсинг...")

    try:
        from scraper import _parse_listing_products

        # HTML без JavaScript данных, но с обычными элементами
        html_fallback = '''
        <html>
        <body>
            <div class="product-card">
                <h3>Test Product</h3>
                <span class="price">1,250 TL</span>
                <a href="/test-product-p-123">Link</a>
            </div>
        </body>
        </html>
        '''

        result = _parse_listing_products(html_fallback, limit=3)

        if isinstance(result, list):
            print(f"✅ Fallback парсинг вернул {len(result)} товаров")
            return True
        else:
            print(f"❌ Fallback парсинг вернул {type(result)}")
            return False

    except Exception as e:
        print(f"❌ Ошибка в fallback парсинге: {e}")
        return False

async def main():
    """Запуск всех тестов парсинга"""
    print("=" * 70)
    print("🔍 КОМПЛЕКСНОЕ ТЕСТИРОВАНИЕ ПАРСИНГА БОТА")
    print("=" * 70)

    test_functions = [
        test_scraper_initialization,
        test_parse_price_text,
        test_extract_json_from_js_var,
        test_get_price_async_with_mock,
        test_get_product_info_async_with_mock,
        test_rate_limiters,
        test_trendyol_url_validation,
        test_parsing_error_handling,
        test_fallback_parsing,
    ]

    results = []

    for test_func in test_functions:
        try:
            if asyncio.iscoroutinefunction(test_func):
                result = await test_func()
            else:
                result = test_func()
            results.append(result)
        except Exception as e:
            print(f"❌ Критическая ошибка в {test_func.__name__}: {e}")
            results.append(False)

    # Итоги
    print("\n" + "=" * 70)
    passed = sum(results)
    total = len(results)

    if passed == total:
        print(f"🎉 Все тесты парсинга прошли! ({passed}/{total})")
        print("✅ Парсинг бота работает корректно!")
        print("\n📋 Что проверено:")
        print("• Инициализация scraper компонентов")
        print("• Парсинг цен из текста")
        print("• Извлечение JSON из JavaScript")
        print("• Асинхронное получение цен")
        print("• Получение информации о товарах")
        print("• Rate limiting")
        print("• Валидация URL Trendyol")
        print("• Обработка ошибок")
        print("• Fallback парсинг")
    else:
        print(f"⚠️  Некоторые тесты парсинга провалились: {passed}/{total}")
        failed_tests = [test_func.__name__ for test_func, result in zip(test_functions, results) if not result]
        print(f"Провалившиеся тесты: {', '.join(failed_tests)}")

    return passed == total

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)