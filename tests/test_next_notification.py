#!/usr/bin/env python3
"""
Тест функции расчета времени следующего уведомления
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from bot import get_next_notification_time
from datetime import datetime
import time

def test_notification_times():
    """Тестируем функцию расчета времени уведомлений"""
    print("=== ТЕСТИРОВАНИЕ РАСЧЕТА ВРЕМЕНИ УВЕДОМЛЕНИЙ ===")

    # Мокаем функцию t для тестирования
    def mock_t(user_id, key):
        translations = {
            "next_notify_discount": "при изменении цены",
            "next_notify_unknown": "неизвестно"
        }
        return translations.get(key, key)

    # Тест 1: Режим discount -> возвращается ключ перевода при отсутствии translate_func
    result = get_next_notification_time("discount", None, None, 123)
    assert result == "next_notify_discount"

    # Тест 2: Режим hourly без данных -> возвращает строку в формате HH:MM
    result = get_next_notification_time("hourly", None, None, 123)
    assert isinstance(result, str) and len(result) == 5 and result[2] == ':'

    # Тест 3: Режим hourly с данными
    current_time = int(time.time())
    last_notify = current_time - 1800  # 30 минут назад
    interval = 60  # 1 час в минутах

    result = get_next_notification_time("hourly", last_notify, interval, 123)
    # Ожидаем формат HH:MM
    assert isinstance(result, str) and len(result) == 5 and result[2] == ':'

    # Тест 4: Неизвестный режим
    result = get_next_notification_time("unknown", None, None, 123)
    assert result == "next_notify_unknown"

    # Если дошли до сюда — тесты прошли

if __name__ == '__main__':
    # Переопределяем функцию t для тестирования
    import bot
    original_t = bot.t
    bot.t = lambda user_id, key: {
        "next_notify_discount": "при изменении цены",
        "next_notify_unknown": "неизвестно"
    }.get(key, key)

    try:
        test_notification_times()
    finally:
        # Восстанавливаем оригинальную функцию
        bot.t = original_t
