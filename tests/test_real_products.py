                      
"""
Тестирование системы получения истории цен на реальных товарах Trendyol
"""

import sys
import os
import asyncio
import time
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from scraper import get_price_history_from_akakce_async, get_product_title
import logging

                                        
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

                                                                                
pytestmark = pytest.mark.skip(reason="Integration test script - skip during unit test runs")

                                                               
TEST_PRODUCTS = [
    {
        "name": "Cream Co Moisturizer",
        "url": "https://www.trendyol.com/cream-co/su-bazli-moisturizer-nemlendirici-aydinlatici-yuz-kremi-hyaluronik-asit-50-ml-tum-cilt-tipleri-p-318291787",
        "category": "Косметика"
    },
    {
        "name": "Roborock Q8 Robot Vacuum",
        "url": "https://www.trendyol.com/roborock/q8-akilli-robot-supurge-siyah-10-000-pa-hyperforce-emis-gucu-p-944315539",
        "category": "Бытовая техника"
    },
    {
        "name": "Narwal Freo X Ultra",
        "url": "https://www.trendyol.com/narwal/freo-x-ultra-akilli-robot-supurge-beyaz-8-200pa-emis-gucu-p-904667260",
        "category": "Бытовая техника"
    },
    {
        "name": "Dreame L40 Ultra CE",
        "url": "https://www.trendyol.com/dreame/l40-ultra-ce-robot-supurge-beyaz-13-000pa-emis-gucu-ozel-hali-temizligi-stratejisi-gucu-p-952228702",
        "category": "Бытовая техника"
    },
    {
        "name": "Raptic iPhone 17 Case",
        "url": "https://www.trendyol.com/raptic/iphone-17-pro-max-uyumlu-kilif-m-safe-sarjli-aramid-skin-transform-serisi-kapak-kahverengi-p-974545261",
        "category": "Аксессуары"
    }
]

async def test_single_product(product):
    """Тестирует получение истории цен для одного товара."""
    print(f"\n🔍 Тестирую: {product['name']} ({product['category']})")
    print(f"   URL: {product['url']}")

    start_time = time.time()

    try:
                                         
        print("   📝 Получаю название товара...")
        title = get_product_title(product['url'])
        if title:
            print(f"   ✅ Название: {title}")
        else:
            print("   ❌ Название не найдено")
            return False, 0, time.time() - start_time

                                     
        print("   📊 Получаю историю цен...")
        history = await get_price_history_from_akakce_async(product['url'])

        elapsed = time.time() - start_time

        if history and len(history) >= 3:
            print(f"   ✅ История получена: {len(history)} точек")
            print(f"   📅 Диапазон: {history[0][0]} - {history[-1][0]}")
            print(f"   💰 Цены: {history[0][1]:.0f} - {history[-1][1]:.0f} TL")
            return True, len(history), elapsed
        else:
            print("   ❌ История не найдена или недостаточно данных")
            return False, 0, elapsed

    except Exception as e:
        elapsed = time.time() - start_time
        print(f"   ❌ Ошибка: {e}")
        return False, 0, elapsed

async def run_tests():
    """Запускает тестирование всех товаров."""
    print("=" * 80)
    print("🧪 ТЕСТИРОВАНИЕ СИСТЕМЫ ИСТОРИИ ЦЕН НА РЕАЛЬНЫХ ТОВАРАХ")
    print("=" * 80)

    results = []
    total_time = 0

    for i, product in enumerate(TEST_PRODUCTS, 1):
        print(f"\n[ {i}/{len(TEST_PRODUCTS)} ]")
        success, points, elapsed = await test_single_product(product)
        results.append({
            'product': product,
            'success': success,
            'points': points,
            'time': elapsed
        })
        total_time += elapsed

                                         
        await asyncio.sleep(2)

                        
    print("\n" + "=" * 80)
    print("📊 РЕЗУЛЬТАТЫ ТЕСТИРОВАНИЯ")
    print("=" * 80)

    successful = sum(1 for r in results if r['success'])
    total = len(results)
    success_rate = (successful / total) * 100

    print(f"✅ Успешных: {successful}/{total} ({success_rate:.1f}%)")
    print(f"📊 Всего товаров: {total}")
    print(f"📈 Среднее время: {total_time/total:.1f} сек")

    print("\n📋 ПОДРОБНЫЕ РЕЗУЛЬТАТЫ:")
    for i, result in enumerate(results, 1):
        status = "✅" if result['success'] else "❌"
        points = f" ({result['points']} точек)" if result['success'] else ""
        print(f"  {i}. {status} {result['product']['name']}{points} - {result['time']:.1f} сек")
    print("\n" + "=" * 80)

                          
    category_stats = {}
    for result in results:
        cat = result['product']['category']
        if cat not in category_stats:
            category_stats[cat] = {'total': 0, 'success': 0}
        category_stats[cat]['total'] += 1
        if result['success']:
            category_stats[cat]['success'] += 1

    print("📊 СТАТИСТИКА ПО КАТЕГОРИЯМ:")
    for cat, stats in category_stats.items():
        rate = (stats['success'] / stats['total']) * 100
        print(f"  {cat}: {stats['success']}/{stats['total']} ({rate:.1f}%)")
    return success_rate

if __name__ == '__main__':
    try:
        success_rate = asyncio.run(run_tests())
        print(f"\n🎯 ИТОГОВЫЙ ПРОЦЕНТ УСПЕХА: {success_rate:.1f}%")

        if success_rate >= 80:
            print("🎉 Отличный результат! Система работает очень хорошо.")
        elif success_rate >= 60:
            print("👍 Хороший результат, но есть что улучшить.")
        else:
            print("⚠️  Нужно доработать систему.")

    except KeyboardInterrupt:
        print("\n⏹️  Тестирование прервано пользователем")
    except Exception as e:
        print(f"\n❌ Ошибка тестирования: {e}")
        import traceback
        traceback.print_exc()
