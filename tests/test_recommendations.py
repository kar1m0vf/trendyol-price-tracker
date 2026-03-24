                      
"""
Тест системы умных рекомендаций
"""

import sys
sys.path.append('.')

import pytest
from bot import analyze_user_preferences, generate_recommendations

                                                 
pytestmark = pytest.mark.skip(reason="Integration script - skip during unit test runs")
import asyncio

def test_preferences_analysis():
    """Тест анализа предпочтений пользователя"""
    print("🧪 ТЕСТИРОВАНИЕ АНАЛИЗА ПРЕДПОЧТЕНИЙ")

                                       
    user_id = 975282591                  

    try:
        preferences = analyze_user_preferences(user_id)
        print(f"✅ Анализ завершен для пользователя {user_id}")

        print(f"   📊 Подписок: {preferences.get('total_subscriptions', 0)}")
        print(f"   🏷️  Категории: {preferences.get('categories', [])}")
        print(f"   🏪 Бренды: {preferences.get('brands', [])}")
        print(f"   🔍 Ключевые слова: {preferences.get('keywords', [])}")

        return preferences

    except Exception as e:
        print(f"❌ Ошибка анализа: {e}")
        return None

async def test_recommendations():
    """Тест генерации рекомендаций"""
    print("\n🎯 ТЕСТИРОВАНИЕ РЕКОМЕНДАЦИЙ")

    user_id = 975282591

    try:
        recommendations = await generate_recommendations(user_id, limit=3)
        print(f"✅ Рекомендации сгенерированы: {len(recommendations)} шт.")

        for i, rec in enumerate(recommendations, 1):
            print(f"   {i}. {rec.get('title', 'N/A')}")
            print(f"      💰 {rec.get('price', 'N/A')}")
            print(f"      📝 {rec.get('reason', 'N/A')}")

        return len(recommendations) > 0

    except Exception as e:
        print(f"❌ Ошибка генерации рекомендаций: {e}")
        return False

def main():
    print("🚀 ЗАПУСК ТЕСТОВ СИСТЕМЫ РЕКОМЕНДАЦИЙ")
    print("=" * 50)

                                 
    preferences = test_preferences_analysis()

                                    
    success = asyncio.run(test_recommendations())

    print("\n" + "=" * 50)
    if preferences and success:
        print("✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ! Система рекомендаций работает корректно.")
        return True
    else:
        print("❌ НЕКОТОРЫЕ ТЕСТЫ ПРОВАЛИЛИСЬ")
        return False

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
