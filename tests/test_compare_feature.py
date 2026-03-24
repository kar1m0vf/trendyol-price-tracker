                      
"""
Тест новой функции сравнения товаров
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import asyncio
from scraper import find_similar_products

def test_similarity_algorithm():
    """Тестируем алгоритм поиска похожих товаров"""
    print("=== ТЕСТИРОВАНИЕ АЛГОРИТМА ПОИСКА ПОХОЖИХ ТОВАРОВ ===")

                     
    test_cases = [
        {
            "title": "iPhone 15 Pro Max 256GB Black",
            "url": "https://www.trendyol.com/apple/iphone-15-pro-max-256-gb-siyah-p-123",
            "keywords": ["iphone", "15", "pro", "max"]
        },
        {
            "title": "Samsung Galaxy S24 Ultra 512GB Black",
            "url": "https://www.trendyol.com/samsung/galaxy-s24-ultra-512-gb-siyah-p-456",
            "keywords": ["samsung", "galaxy", "s24", "ultra"]
        },
        {
            "title": "MacBook Air M3 13 inch",
            "url": "https://www.trendyol.com/apple/macbook-air-13-m3-p-789",
            "keywords": ["macbook", "air", "m3"]
        }
    ]

    for i, test_case in enumerate(test_cases, 1):
        print(f"\n{i}. Тестируем: '{test_case['title']}'")

                                  
        similar = find_similar_products(test_case['title'], test_case['url'], limit=3)

        if similar:
            print(f"   ✅ Найдено {len(similar)} похожих товаров:")
            for j, item in enumerate(similar, 1):
                print(f"     {j}. {item['title'][:50]}... (релевантность: {item['relevance']})")
        else:
            print("   ❌ Похожие товары не найдены")

async def test_full_comparison():
    """Тестируем полную функцию сравнения"""
    print("\n=== ТЕСТИРОВАНИЕ ПОЛНОЙ ФУНКЦИИ СРАВНЕНИЯ ===")

                                   
    from scraper import get_similar_products_comparison
    from database import get_all_subscriptions

                                                     
    try:
        subs = get_all_subscriptions()
        if not subs:
            print("❌ Нет подписок для тестирования")
            return

                               
        test_sub = subs[0]
        sub_id = test_sub[0]
        user_id = test_sub[1]

        print(f"Тестируем сравнение для подписки ID {sub_id}")

                             
        result = await get_similar_products_comparison(user_id, sub_id)

        if result:
            print("✅ Сравнение выполнено успешно")
                                                       
            preview = result.replace('\n', ' ').replace('*', '')[:200]
            print(f"Превью: {preview}...")
        else:
            print("❌ Сравнение не удалось")

    except Exception as e:
        print(f"❌ Ошибка тестирования: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    try:
                          
        test_similarity_algorithm()

                           
        asyncio.run(test_full_comparison())

        print("\n🎉 Тестирование завершено!")

    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
