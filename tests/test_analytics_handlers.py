                      
"""
Комплексные тесты для обработчиков аналитики.
"""
import os
import sys
import asyncio
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

                                                                         
os.environ['USE_NEW_HANDLERS'] = 'true'

                                 
TEST_DB = tempfile.mktemp(suffix='.db')

def test_analytics_handlers_import():
    """Тест импорта обработчиков аналитики."""
    try:
        from handlers import AnalyticsHandler
        print("✅ AnalyticsHandler import OK")

                           
        handler = AnalyticsHandler()
        print("✅ AnalyticsHandler instance created")

                          
        assert hasattr(handler, 'handle_stats_command'), "handle_stats_command method missing"
        assert hasattr(handler, 'handle_all_list_command'), "handle_all_list_command method missing"
        assert hasattr(handler, 'handle_top_drops_command'), "handle_top_drops_command method missing"
        assert hasattr(handler, 'register'), "register method missing"
        print("✅ All required methods present")
        return True
    except Exception as e:
        print(f"❌ AnalyticsHandler test failed: {e}")
        raise

async def test_analytics_functionality():
    """Тест функциональности аналитических обработчиков."""
    try:
        from handlers import AnalyticsHandler
        from unittest.mock import AsyncMock

        handler = AnalyticsHandler()

                      
        mock_msg = MagicMock()
        mock_msg.from_user.id = 12345
        mock_msg.text = "/stats 1"
        mock_msg.answer = AsyncMock()

                                                                                       
        await handler.handle_stats_command(mock_msg)
        mock_msg.answer.assert_called_once()
        print("✅ handle_stats_command works")

                               
        mock_msg.text = "/all_list"
        mock_msg.answer.reset_mock()
        await handler.handle_all_list_command(mock_msg)
        mock_msg.answer.assert_called_once()
        print("✅ handle_all_list_command works")

                                
        mock_msg.answer.reset_mock()
        await handler.handle_top_drops_command(mock_msg)
        mock_msg.answer.assert_called_once()
        print("✅ handle_top_drops_command works")

        return True
    except Exception as e:
        print(f"❌ Analytics functionality test failed: {e}")
        raise

async def test_stats_command_with_valid_data():
    """Тест команды /stats с валидными данными."""
    print("🧪 Тестируем /stats с тестовыми данными...")

    try:
                                 
        with patch('handlers.analytics_handler.get_subscription') as mock_get_sub,\
             patch('handlers.analytics_handler.get_price_stats') as mock_get_stats:

                         
            mock_sub = (1, 12345, "https://test.com", "hourly", 1000.0, "Test Product", None, None, None, None, None, None, None)
            mock_get_sub.return_value = mock_sub
            mock_get_stats.return_value = {
                'count': 5,
                'current': 950.0,
                'min': 900.0,
                'max': 1000.0,
                'avg': 950.0,
                'trend': "📈 +5.0%",
                'days': 7
            }

            from handlers import AnalyticsHandler
            handler = AnalyticsHandler()

                          
            mock_msg = MagicMock()
            mock_msg.from_user.id = 12345
            mock_msg.text = "/stats 1"
            mock_msg.answer = AsyncMock()

            await handler.handle_stats_command(mock_msg)

                                             
            assert mock_msg.answer.called, "answer должен быть вызван"
            call_args = mock_msg.answer.call_args
            assert call_args is not None, "должен быть текст ответа"

            text = call_args[0][0]
            assert "ID: 1" in text, "должен содержать ID подписки"
            assert "950.00 TL" in text, "должен содержать текущую цену"
            assert "900.00 TL" in text, "должен содержать минимальную цену"
            assert "1000.00 TL" in text, "должен содержать максимальную цену"
            assert "+5.0%" in text, "должен содержать тренд"

        print("✅ /stats с валидными данными работает корректно")
        return True

    except Exception as e:
        print(f"❌ Ошибка в /stats с валидными данными: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_stats_command_invalid_id():
    """Тест команды /stats с некорректным ID."""
    print("🧪 Тестируем /stats с некорректным ID...")

    try:
        from handlers import AnalyticsHandler
        handler = AnalyticsHandler()

                                        
        mock_msg = MagicMock()
        mock_msg.from_user.id = 12345
        mock_msg.text = "/stats abc"
        mock_msg.answer = AsyncMock()

        await handler.handle_stats_command(mock_msg)

                                                                
        assert mock_msg.answer.called, "answer должен быть вызван"

        print("✅ /stats с некорректным ID обрабатывается корректно")
        return True

    except Exception as e:
        print(f"❌ Ошибка в /stats с некорректным ID: {e}")
        return False

async def test_stats_command_no_args():
    """Тест команды /stats без аргументов."""
    print("🧪 Тестируем /stats без аргументов...")

    try:
        from handlers import AnalyticsHandler
        handler = AnalyticsHandler()

                                     
        mock_msg = MagicMock()
        mock_msg.from_user.id = 12345
        mock_msg.text = "/stats"
        mock_msg.answer = AsyncMock()

        await handler.handle_stats_command(mock_msg)

                                                      
        assert mock_msg.answer.called, "answer должен быть вызван"

        print("✅ /stats без аргументов обрабатывается корректно")
        return True

    except Exception as e:
        print(f"❌ Ошибка в /stats без аргументов: {e}")
        return False

async def test_all_list_command_with_data():
    """Тест команды /all_list с данными."""
    print("🧪 Тестируем /all_list с данными...")

    try:
                                 
        with patch('handlers.analytics_handler.get_user_subscriptions') as mock_get_subs:
                                      
            mock_subs = [
                (1, 12345, "https://test1.com", "hourly", 1000.0, "Product 1", None, None, None, None, None, None, None),
                (2, 12345, "https://test2.com", "discount", 2000.0, "Product 2", None, None, None, None, None, None, None),
            ]
            mock_get_subs.return_value = mock_subs

            from handlers import AnalyticsHandler
            handler = AnalyticsHandler()

                          
            mock_msg = MagicMock()
            mock_msg.from_user.id = 12345
            mock_msg.answer = AsyncMock()

            await handler.handle_all_list_command(mock_msg)

                                             
            assert mock_msg.answer.called, "answer должен быть вызван"
            call_args = mock_msg.answer.call_args
            assert call_args is not None, "должен быть текст ответа"

            text = call_args[0][0]
            assert "ID" in text, "должен содержать заголовок с ID"
            assert "1" in text, "должен содержать ID первой подписки"
            assert "2" in text, "должен содержать ID второй подписки"
            assert "⏰" in text, "должен содержать режимы уведомлений"

        print("✅ /all_list с данными работает корректно")
        return True

    except Exception as e:
        print(f"❌ Ошибка в /all_list с данными: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_top_drops_command_with_data():
    """Тест команды /top_drops с данными."""
    print("🧪 Тестируем /top_drops с данными...")

    try:
                                 
        with patch('handlers.analytics_handler.get_top_price_drops') as mock_get_drops:
                              
            mock_drops = [
                (1, "https://test1.com", "Product 1", 950.0, 1000.0, -5.0),
                (2, "https://test2.com", "Product 2", 1800.0, 2000.0, -10.0),
            ]
            mock_get_drops.return_value = mock_drops

            from handlers import AnalyticsHandler
            handler = AnalyticsHandler()

                          
            mock_msg = MagicMock()
            mock_msg.from_user.id = 12345
            mock_msg.answer = AsyncMock()

            await handler.handle_top_drops_command(mock_msg)

                                             
            assert mock_msg.answer.called, "answer должен быть вызван"
            call_args = mock_msg.answer.call_args
            assert call_args is not None, "должен быть текст ответа"

            text = call_args[0][0]
            assert "🔴" in text or "🟢" in text, "должен содержать индикаторы изменения цены"
            assert "-5.0%" in text, "должен содержать процент падения"
            assert "ID:1" in text, "должен содержать ID подписки"

        print("✅ /top_drops с данными работает корректно")
        return True

    except Exception as e:
        print(f"❌ Ошибка в /top_drops с данными: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_handler_registration():
    """Тест регистрации обработчиков."""
    print("🧪 Тестируем регистрацию обработчиков...")

    try:
        from handlers import AnalyticsHandler
        handler = AnalyticsHandler()

                 
        mock_dp = MagicMock()
        mock_dp.message.register = MagicMock()

                                  
        handler.register(mock_dp)

                                                                 
        assert mock_dp.message.register.call_count == 3, f"должно быть 3 регистрации, получено {mock_dp.message.register.call_count}"

        print("✅ Регистрация обработчиков работает корректно")
        return True

    except Exception as e:
        print(f"❌ Ошибка в регистрации обработчиков: {e}")
        return False

async def main():
    """Запуск всех тестов."""
    print("🧪 Тестирование аналитических обработчиков...")
    print("=" * 60)

    results = []

                  
    try:
        result = test_analytics_handlers_import()
        results.append(result)
    except Exception as e:
        print(f"❌ Тест импорта провалился: {e}")
        results.append(False)

                            
    test_functions = [
        test_analytics_functionality,
        test_stats_command_with_valid_data,
        test_stats_command_invalid_id,
        test_stats_command_no_args,
        test_all_list_command_with_data,
        test_top_drops_command_with_data,
    ]

                      
    sync_tests = [
        test_handler_registration,
    ]

    for test_func in sync_tests:
        try:
            result = test_func()
            results.append(result)
        except Exception as e:
            print(f"❌ {test_func.__name__} провалился: {e}")
            results.append(False)

    for test_func in test_functions:
        try:
            result = await test_func()
            results.append(result)
        except Exception as e:
            print(f"❌ {test_func.__name__} провалился: {e}")
            results.append(False)

    print("=" * 60)

    passed = sum(results)
    total = len(results)

    if passed == total:
        print(f"🎉 Все тесты аналитики прошли! ({passed}/{total})")
        print("✅ Аналитические обработчики готовы!")
        return 0
    else:
        print(f"⚠️  Некоторые тесты провалились: {passed}/{total}")
        return 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))






