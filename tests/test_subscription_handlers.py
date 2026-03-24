                      
"""
Тесты для новых обработчиков подписок.
"""
import os
import sys
import asyncio
from unittest.mock import AsyncMock, MagicMock

                                                                         
os.environ['USE_NEW_HANDLERS'] = 'true'

def test_subscription_handlers_import():
    """Тест импорта обработчиков подписок."""
    try:
        from handlers import SubscriptionHandler
        print("✅ SubscriptionHandler import OK")

                           
        handler = SubscriptionHandler()
        print("✅ SubscriptionHandler instance created")

                          
        assert hasattr(handler, 'handle_mysubs_command'), "handle_mysubs_command method missing"
        assert hasattr(handler, 'handle_unsubscribe_command'), "handle_unsubscribe_command method missing"
        assert hasattr(handler, 'handle_url_subscription'), "handle_url_subscription method missing"
        print("✅ All required methods present")
        print("✅ All required methods present")
        return
    except Exception as e:
        print(f"❌ SubscriptionHandler test failed: {e}")
        raise

def test_utils_functions():
    """Тест функций из utils.py."""
    try:
        from utils import get_next_notification_time, parse_date_flexible
        print("✅ Utils functions import OK")

                                         
        result = get_next_notification_time("hourly", None, None, 12345)
        assert isinstance(result, str), "get_next_notification_time should return string"
        print("✅ get_next_notification_time works")

                                  
        dt = parse_date_flexible("20.09.2025")
        assert dt is not None, "parse_date_flexible should parse valid date"
        print("✅ parse_date_flexible works")
        print("✅ parse_date_flexible works")
        return
    except Exception as e:
        print(f"❌ Utils functions test failed: {e}")
        raise

async def test_handler_functionality():
    """Тест функциональности обработчиков."""
    try:
        from handlers import SubscriptionHandler
        from unittest.mock import AsyncMock

        handler = SubscriptionHandler()

                      
        mock_message = MagicMock()
        mock_message.from_user.id = 12345
        mock_message.text = "/mysubs"
        mock_message.answer = AsyncMock()

                                                                 
        await handler.handle_mysubs_command(mock_message)
        mock_message.answer.assert_called_once()
        print("✅ Handler functionality test passed")
        return
    except Exception as e:
        print(f"❌ Handler functionality test failed: {e}")
        raise

def test_old_handlers_still_work():
    """Тест что старые обработчики все еще работают при USE_NEW_HANDLERS=false."""
                                     
    original_value = os.environ.get('USE_NEW_HANDLERS')

    try:
                                     
        os.environ['USE_NEW_HANDLERS'] = 'false'

                                                            
        if 'bot' in sys.modules:
            del sys.modules['bot']

                                                             
        import bot
        assert hasattr(bot, 'cmd_mysubs'), "cmd_mysubs should still be available"
        assert hasattr(bot, 'cmd_unsubscribe'), "cmd_unsubscribe should still be available"
        print("✅ Old handlers still available when USE_NEW_HANDLERS=false")
        return
    except Exception as e:
        print(f"❌ Old handlers test failed: {e}")
        raise
    finally:
                                  
        if original_value is not None:
            os.environ['USE_NEW_HANDLERS'] = original_value
        elif 'USE_NEW_HANDLERS' in os.environ:
            del os.environ['USE_NEW_HANDLERS']

def main():
    """Запуск всех тестов."""
    print("🧪 Testing new subscription handlers...")
    print("=" * 50)

    results = []

                   
    try:
        test_subscription_handlers_import()
        results.append(True)
    except Exception:
        results.append(False)

    try:
        test_utils_functions()
        results.append(True)
    except Exception:
        results.append(False)

                           
    try:
        asyncio.run(test_handler_functionality())
        results.append(True)
        print("✅ Handler functionality test passed")
    except Exception as e:
        print(f"❌ Handler functionality test failed: {e}")
        results.append(False)

                                 
    try:
        test_old_handlers_still_work()
        results.append(True)
    except Exception:
        results.append(False)

    print("=" * 50)

    passed = sum(results)
    total = len(results)

    if passed == total:
        print(f"🎉 All tests passed! ({passed}/{total})")
        print("✅ New subscription handlers are ready!")
        return 0
    else:
        print(f"⚠️  Some tests failed: {passed}/{total}")
        return 1

if __name__ == "__main__":
    sys.exit(main())












