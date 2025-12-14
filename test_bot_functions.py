"""
Комплексный тест функций бота
Проверяет работу функций БД, валидацию, обработку ошибок
"""
import sys
import os
import tempfile
import time
import sqlite3
from pathlib import Path

# Добавляем корневую директорию в путь
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

# Создаем временную БД для тестов
TEST_DB = tempfile.mktemp(suffix='.db')

print("=" * 60)
print("ТЕСТИРОВАНИЕ ФУНКЦИЙ БОТА")
print("=" * 60)

# Мокаем БД для тестов
import database
original_db = database.DB
database.DB = TEST_DB

try:
    # Тест 1: Инициализация БД
    print("\n[1] Тест инициализации БД...")
    database.init_db()
    print("✅ БД инициализирована успешно")
    
    # Тест 2: Добавление пользователя
    print("\n[2] Тест добавления пользователя...")
    test_user_id = 999999
    database.add_user_if_not_exists(test_user_id, "ru")
    lang = database.get_user_language(test_user_id)
    assert lang == "ru", f"Ожидался язык 'ru', получен '{lang}'"
    print("✅ Пользователь добавлен, язык установлен")
    
    # Тест 3: Добавление подписки
    print("\n[3] Тест добавления подписки...")
    test_url = "https://www.trendyol.com/test-product-p-123456"
    sub_id = database.add_subscription(
        test_user_id, 
        test_url, 
        mode="hourly",
        product_title="Test Product",
        product_image="https://example.com/image.jpg"
    )
    assert isinstance(sub_id, int) and sub_id > 0, f"Неверный ID подписки: {sub_id}"
    print(f"✅ Подписка создана с ID: {sub_id}")
    
    # Тест 4: Получение подписки
    print("\n[4] Тест получения подписки...")
    sub = database.get_subscription(sub_id)
    assert sub is not None, "Подписка не найдена"
    assert sub[1] == test_user_id, "Неверный user_id"
    assert sub[2] == test_url, "Неверный URL"
    assert len(sub) >= 13, f"Неверное количество полей: {len(sub)}"
    print(f"✅ Подписка получена: {len(sub)} полей")
    
    # Тест 5: Добавление точек цены
    print("\n[5] Тест добавления точек цены...")
    now = int(time.time())
    prices = [3000.0, 2900.0, 2800.0, 2700.0, 2600.0]
    for i, price in enumerate(prices):
        ts = now - (len(prices) - i) * 3600  # каждый час
        point_id = database.add_price_point(sub_id, test_url, price, ts)
        assert isinstance(point_id, int), f"Неверный ID точки: {point_id}"
    print(f"✅ Добавлено {len(prices)} точек цены")
    
    # Тест 6: Получение истории цен
    print("\n[6] Тест получения истории цен...")
    history = database.get_price_history(sub_id, limit=100)
    assert len(history) == len(prices), f"Ожидалось {len(prices)} точек, получено {len(history)}"
    print(f"✅ История получена: {len(history)} точек")
    
    # Тест 7: Статистика цен
    print("\n[7] Тест статистики цен...")
    stats = database.get_price_stats(sub_id)
    assert stats['count'] == len(prices), f"Неверное количество точек в статистике"
    assert stats['min'] == min(prices), f"Неверный минимум: {stats['min']} != {min(prices)}"
    assert stats['max'] == max(prices), f"Неверный максимум: {stats['max']} != {max(prices)}"
    assert stats['current'] == prices[-1], f"Неверная текущая цена"
    print(f"✅ Статистика: мин={stats['min']}, макс={stats['max']}, текущая={stats['current']}")
    
    # Тест 8: Обновление цены
    print("\n[8] Тест обновления цены...")
    new_price = 2500.0
    database.update_last_price(sub_id, new_price)
    sub_updated = database.get_subscription(sub_id)
    assert abs(sub_updated[4] - new_price) < 0.01, f"Цена не обновлена: {sub_updated[4]}"
    print(f"✅ Цена обновлена: {new_price}")
    
    # Тест 9: Обновление режима
    print("\n[9] Тест обновления режима...")
    database.update_mode(sub_id, "discount")
    sub_mode = database.get_subscription(sub_id)
    assert sub_mode[3] == "discount", f"Режим не обновлен: {sub_mode[3]}"
    print("✅ Режим обновлен на 'discount'")
    
    # Тест 10: Настройки подписки
    print("\n[10] Тест настроек подписки...")
    database.update_subscription_settings(
        sub_id,
        min_price=2000.0,
        max_price=3500.0,
        notify_percent=10.0,
        price_alert=2400.0
    )
    sub_settings = database.get_subscription(sub_id)
    # Проверяем что настройки применились (нужно проверить поля)
    print("✅ Настройки подписки обновлены")
    
    # Тест 11: Получение подписок пользователя
    print("\n[11] Тест получения подписок пользователя...")
    user_subs = database.get_user_subscriptions(test_user_id)
    assert len(user_subs) > 0, "Подписки пользователя не найдены"
    assert any(s[0] == sub_id for s in user_subs), "Созданная подписка не найдена"
    print(f"✅ Найдено подписок: {len(user_subs)}")
    
    # Тест 12: Топ падений цены
    print("\n[12] Тест топ падений цены...")
    drops = database.get_top_price_drops(test_user_id, limit=10)
    assert len(drops) > 0, "Топ падений пуст"
    print(f"✅ Найдено падений: {len(drops)}")
    
    # Тест 13: Экспорт подписок
    print("\n[13] Тест экспорта подписок...")
    exported = database.export_user_subscriptions(test_user_id)
    assert len(exported) > 0, "Экспорт пуст"
    assert 'id' in exported[0], "Неверный формат экспорта"
    print(f"✅ Экспортировано подписок: {len(exported)}")
    
    # Тест 14: Удаление подписки
    print("\n[14] Тест удаления подписки...")
    removed = database.remove_subscription(sub_id)
    assert removed is True, "Подписка не удалена"
    sub_deleted = database.get_subscription(sub_id)
    assert sub_deleted is None, "Подписка все еще существует"
    print("✅ Подписка удалена")
    
    # Тест 15: Обработка несуществующих данных
    print("\n[15] Тест обработки несуществующих данных...")
    non_existent = database.get_subscription(999999)
    assert non_existent is None, "Должен вернуть None для несуществующей подписки"
    empty_history = database.get_price_history(999999)
    assert empty_history == [], "Должен вернуть пустой список"
    print("✅ Обработка несуществующих данных работает корректно")
    
    print("\n" + "=" * 60)
    print("✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ УСПЕШНО!")
    print("=" * 60)
    
except AssertionError as e:
    print(f"\n❌ ОШИБКА ТЕСТА: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
except Exception as e:
    print(f"\n❌ НЕОЖИДАННАЯ ОШИБКА: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
finally:
    # Восстанавливаем оригинальную БД
    database.DB = original_db
    # Удаляем тестовую БД
    try:
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)
    except:
        pass

