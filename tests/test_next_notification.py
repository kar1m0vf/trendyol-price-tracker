                      
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

                                       
    def mock_t(user_id, key):
        translations = {
            "next_notify_discount": "при изменении цены",
            "next_notify_unknown": "неизвестно"
        }
        return translations.get(key, key)

                                                                                        
    result = get_next_notification_time("discount", None, None, 123)
    assert result == "next_notify_discount"

                                                                          
    result = get_next_notification_time("hourly", None, None, 123)
    assert isinstance(result, str) and len(result) == 5 and result[2] == ':'

                                    
    current_time = int(time.time())
    last_notify = current_time - 1800                  
    interval = 60                   

    result = get_next_notification_time("hourly", last_notify, interval, 123)
                          
    assert isinstance(result, str) and len(result) == 5 and result[2] == ':'

                               
    result = get_next_notification_time("unknown", None, None, 123)
    assert result == "next_notify_unknown"

                                       

if __name__ == '__main__':
                                               
    import bot
    original_t = bot.t
    bot.t = lambda user_id, key: {
        "next_notify_discount": "при изменении цены",
        "next_notify_unknown": "неизвестно"
    }.get(key, key)

    try:
        test_notification_times()
    finally:
                                              
        bot.t = original_t
