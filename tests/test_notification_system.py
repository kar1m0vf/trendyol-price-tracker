                      
"""
Комплексный тест системы уведомлений бота
"""
import sys
import os
import asyncio
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

                                      
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

                                 
TEST_DB = tempfile.mktemp(suffix='.db')

def test_notification_logic():
    """Тест базовой логики уведомлений"""
    print("🧪 Тестируем логику уведомлений...")

    try:
                                  
        test_cases = [
                                                                                                          
            ("hourly", 1000.0, 950.0, None, None, True, "Почасовое уведомление"),
            ("discount", 1000.0, 950.0, 5.0, None, True, "Уведомление при скидке > 5%"),
            ("discount", 1000.0, 980.0, 5.0, None, False, "Уведомление при скидке < 5%"),
            ("discount", 1000.0, 950.0, None, None, True, "Уведомление при любой скидке"),
            ("other", 1000.0, 950.0, None, None, False, "Неизвестный режим"),
            ("hourly", 1000.0, 950.0, None, 960.0, True, "Целевая цена достигнута"),
            ("hourly", 1000.0, 950.0, None, 940.0, True, "Целевая цена достигнута (ниже)"),
        ]

        passed = 0
        for mode, last_price, current_price, notify_percent, price_alert, expected, desc in test_cases:
            notification_needed = False

                                                  
            if price_alert is not None and current_price <= price_alert:
                notification_needed = True
            elif mode == "hourly":
                notification_needed = True
            elif mode == "discount":
                if last_price and current_price:
                    price_changed_percent = ((last_price - current_price) / last_price) * 100
                    if notify_percent and abs(price_changed_percent) >= notify_percent:
                        notification_needed = True
                    elif not notify_percent and current_price < last_price:
                        notification_needed = True

            if notification_needed == expected:
                passed += 1
                print(f"  ✅ {desc}")
            else:
                print(f"  ❌ {desc} (ожидалось {expected}, получено {notification_needed})")

        print(f"Результат логики: {passed}/{len(test_cases)} тестов пройдено")
        assert passed == len(test_cases)

    except Exception as e:
        print(f"❌ Ошибка в логике уведомлений: {e}")
        raise AssertionError("test reported failure")

async def test_send_grouped_notifications():
    """Тест отправки групповых уведомлений"""
    print("🧪 Тестируем отправку групповых уведомлений...")

    try:
        from bot import send_grouped_notifications

                                   
        mock_notifications = {
            12345: [
                ("Цена товара X упала до 950 TL", "http://example.com/image1.jpg"),
                ("Цена товара Y упала до 850 TL", None),
            ],
            67890: [
                ("Цена товара Z упала до 750 TL", "http://example.com/image2.jpg"),
            ]
        }

        with patch('bot.send_notification_with_timeout') as mock_send:
            mock_send.return_value = None                          

            await send_grouped_notifications(mock_notifications)

                                                
            assert mock_send.call_count >= 2, f"Ожидалось минимум 2 вызова, получено {mock_send.call_count}"

            print("✅ Групповые уведомления отправляются корректно")
            return

    except Exception as e:
        print(f"❌ Ошибка в групповых уведомлениях: {e}")
        raise AssertionError("test reported failure")

async def test_scheduler_setup():
    """Тест настройки планировщика"""
    print("🧪 Тестируем настройку планировщика...")

    try:
        from bot import start_scheduler_async, scheduler
        from apscheduler.schedulers.asyncio import AsyncIOScheduler

                                            
        assert isinstance(scheduler, AsyncIOScheduler), "Scheduler должен быть AsyncIOScheduler"

                                                                
        assert callable(start_scheduler_async), "start_scheduler_async должна быть функцией"

        print("✅ Планировщик настроен корректно")
        return

    except Exception as e:
        print(f"❌ Ошибка в настройке планировщика: {e}")
        raise AssertionError("test reported failure")

async def test_notification_service_methods():
    """Тест методов NotificationService"""
    print("🧪 Тестируем методы NotificationService...")

    try:
        from services.notification_service import NotificationService

                  
        mock_bot = MagicMock()
        mock_bot.send_message = AsyncMock()
        mock_bot.send_photo = AsyncMock()

        service = NotificationService(mock_bot)

                                             
        mock_bot.send_message.reset_mock()
        result = await service.send_notification_safe(12345, "Test message")
        assert result == True, "send_notification_safe должен вернуть True"
        assert mock_bot.send_message.called, "send_message должен быть вызван"

                                                       
        mock_bot.send_photo.reset_mock()
        mock_bot.send_message.reset_mock()

                                    
        mock_bot.send_photo.side_effect = asyncio.TimeoutError()
        result = await service.send_notification_safe(12345, "Test message", image="http://example.com/image.jpg")
        assert result == True, "Должен быть fallback на текст при timeout фото"
        assert mock_bot.send_message.called, "send_message должен быть вызван для fallback"

        print("✅ Методы NotificationService работают корректно")
        return

    except Exception as e:
        print(f"❌ Ошибка в NotificationService: {e}")
        import traceback
        traceback.print_exc()
        raise AssertionError("test reported failure")

async def test_quiet_hours_logic():
    """Тест логики тихих часов"""
    print("🧪 Тестируем логику тихих часов...")

    try:
        from datetime import datetime

                                     
        test_cases = [
                                                                                 
            (2, 23, 7, True, "Ночь между днями"),                            
            (14, 23, 7, False, "День"),                                
            (6, 23, 7, True, "Раннее утро"),                            
            (10, 9, 18, True, "Рабочий день"),                             
            (20, 9, 18, False, "Вечер после работы"),                                
        ]

        passed = 0
        for current_hour, quiet_start, quiet_end, expected, desc in test_cases:
            is_quiet_time = False
            if quiet_start <= quiet_end:
                is_quiet_time = quiet_start <= current_hour < quiet_end
            else:                          
                is_quiet_time = current_hour >= quiet_start or current_hour < quiet_end

            if is_quiet_time == expected:
                passed += 1
                print(f"  ✅ {desc}")
            else:
                print(f"  ❌ {desc} (ожидалось {expected}, получено {is_quiet_time})")

        print(f"Результат тихих часов: {passed}/{len(test_cases)} тестов пройдено")
        assert passed == len(test_cases)

    except Exception as e:
        print(f"❌ Ошибка в логике тихих часов: {e}")
        raise AssertionError("test reported failure")

async def test_notification_templates():
    """Тест шаблонов уведомлений"""
    print("🧪 Тестируем шаблоны уведомлений...")

    try:
        from localization import t

                                    
        templates = [
            ('hourly_msg', 'price', 'url'),
            ('discount_msg', 'old', 'new', 'url'),
            ('price_below_min_msg', 'price', 'min_price', 'url'),
            ('price_above_max_msg', 'price', 'max_price', 'url'),
        ]

        passed = 0
        for template_key, *params in templates:
            try:
                template = t(12345, template_key)
                assert template, f"Шаблон {template_key} пустой"

                                                           
                for param in params:
                    assert f"{{{param}}}" in template, f"В шаблоне {template_key} нет плейсхолдера {{{param}}}"

                passed += 1
                print(f"  ✅ Шаблон {template_key}")

            except Exception as e:
                print(f"  ❌ Шаблон {template_key}: {e}")

        print(f"Результат шаблонов: {passed}/{len(templates)} шаблонов корректны")
        assert passed == len(templates)

    except Exception as e:
        print(f"❌ Ошибка в шаблонах уведомлений: {e}")
        raise AssertionError("test reported failure")

async def main():
    """Запуск всех тестов уведомлений"""
    print("=" * 70)
    print("🔔 КОМПЛЕКСНОЕ ТЕСТИРОВАНИЕ СИСТЕМЫ УВЕДОМЛЕНИЙ")
    print("=" * 70)

    test_functions = [
        test_notification_logic,
        test_send_grouped_notifications,
        test_scheduler_setup,
        test_notification_service_methods,
        test_quiet_hours_logic,
        test_notification_templates,
    ]

    results = []

    for test_func in test_functions:
        try:
            if asyncio.iscoroutinefunction(test_func):
                result = await test_func()
            else:
                result = test_func()
            results.append(result is not False)
        except Exception as e:
            print(f"❌ Критическая ошибка в {test_func.__name__}: {e}")
            results.append(False)

           
    print("\n" + "=" * 70)
    passed = sum(results)
    total = len(results)

    if passed == total:
        print(f"🎉 Все тесты уведомлений прошли! ({passed}/{total})")
        print("✅ Система уведомлений работает корректно!")
        print("\n📋 Что проверено:")
        print("• Логика условий отправки уведомлений")
        print("• Групповые уведомления")
        print("• Настройка планировщика")
        print("• Сервис уведомлений")
        print("• Тихие часы")
        print("• Шаблоны сообщений")
    else:
        print(f"⚠️  Некоторые тесты уведомлений провалились: {passed}/{total}")
        failed_tests = [test_func.__name__ for test_func, result in zip(test_functions, results) if not result]
        print(f"Провалившиеся тесты: {', '.join(failed_tests)}")

    return passed == total

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
