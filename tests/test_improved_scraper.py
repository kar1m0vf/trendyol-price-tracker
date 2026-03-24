                      
"""
Тест улучшенных функций scraper.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import scraper

def test_title_extraction():
    """Тестируем улучшенное извлечение названий."""
    print('=== ТЕСТИРОВАНИЕ УЛУЧШЕННОГО ИЗВЛЕЧЕНИЯ НАЗВАНИЙ ===')

    test_urls = [
        'https://www.trendyol.com/product-p-123',
        'https://www.trendyol.com/brand/product-p-456'
    ]

    for url in test_urls:
        try:
            title = scraper.get_product_title(url)
            print(f'{url}: {title or "Не найдено"}')
        except Exception as e:
            print(f'{url}: Ошибка - {e}')

def test_relevance():
    """Тестируем функцию релевантности."""
    print('\n=== ТЕСТИРОВАНИЕ РЕЛЕВАНТНОСТИ ===')

    test_cases = [
        ('iPhone 14 Pro', 'iPhone 14 Pro Max 256GB'),
        ('Samsung Galaxy', 'Samsung Galaxy S23'),
        ('MacBook Air', 'MacBook Pro M3'),
        ('iPhone 14 Pro', 'Samsung Galaxy S23'),
    ]

    for search, candidate in test_cases:
        rel = scraper._calculate_relevance(search.lower(), candidate.lower())
        print('.2f')

def test_cache():
    """Тестируем систему кэширования."""
    print('\n=== ТЕСТИРОВАНИЕ КЭША ===')

    key = scraper._get_cache_key('test query', 'test_source')
    print(f'Cache key: {key}')

    scraper._set_cached_result(key, 'test_data')
    cached = scraper._get_cached_result(key)
    print(f'Cached data: {cached}')

def test_json_extraction():
    """Тестируем извлечение из JSON."""
    print('\n=== ТЕСТИРОВАНИЕ ИЗВЛЕЧЕНИЯ ИЗ JSON ===')

                                
    test_html = '''
    <script>
    window.__PRODUCT_DETAIL_APP_INITIAL_STATE__ = {
        "product": {
            "name": "Test Product Name",
            "title": "Test Title",
            "priceHistory": [
                {"date": "01.01.2024", "price": 100.0},
                {"date": "02.01.2024", "price": 95.0}
            ]
        }
    };
    </script>
    '''

    title = scraper._extract_title_from_json(test_html)
    print(f'Extracted title: {title}')

                                  
    hist = scraper._extract_price_history_from_object({"product": {"priceHistory": [
        {"date": "01.01.2024", "price": 100.0},
        {"date": "02.01.2024", "price": 95.0}
    ]}})
    print(f'Extracted history: {hist}')

if __name__ == '__main__':
    try:
        test_title_extraction()
        test_relevance()
        test_cache()
        test_json_extraction()
        print('\n✅ Все тесты завершены')
    except Exception as e:
        print(f'\n❌ Ошибка тестирования: {e}')
        import traceback
        traceback.print_exc()
