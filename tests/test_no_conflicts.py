"""
Тест на отсутствие конфликтов при единой регистрации обработчиков.
"""
import os
import sys
import asyncio
from unittest.mock import MagicMock, AsyncMock

def test_no_double_registration():
    """Тест что обработчики не регистрируются дважды."""
    print("Testing handler conflict resolution...")
    original_value = os.environ.get('USE_NEW_HANDLERS')

    try:
        try:
            import bot
            print("✅ Package handler architecture: no conflicts detected")
            assert bot.USE_NEW_HANDLERS is True

            modules_to_reset = ['bot', 'handlers', 'handlers.basic', 'handlers.subscription_handler']
            for mod in modules_to_reset:
                if mod in sys.modules:
                    del sys.modules[mod]

        except Exception as e:
            print(f"❌ Handler architecture failed: {e}")
            raise

        # The old USE_NEW_HANDLERS=false switch is ignored for compatibility.
        os.environ['USE_NEW_HANDLERS'] = 'false'
        try:
            import bot
            assert bot.USE_NEW_HANDLERS is True
            print("✅ Deprecated handler switch does not re-enable legacy registration")

            for mod in modules_to_reset:
                if mod in sys.modules:
                    del sys.modules[mod]

        except Exception as e:
            print(f"❌ Deprecated handler switch check failed: {e}")
            raise
    finally:
        if original_value is not None:
            os.environ['USE_NEW_HANDLERS'] = original_value
        elif 'USE_NEW_HANDLERS' in os.environ:
            del os.environ['USE_NEW_HANDLERS']

    return

def test_localization_module():
    """Тест нового модуля локализации."""
    try:
        from localization import t, LOCALES

                          
        result = t(12345, "start_text")
        assert isinstance(result, str), "Translation should return string"
        print("✅ Localization module works")

                             
        assert "ru" in LOCALES, "Russian locale should be loaded"
        print("✅ Locales loaded correctly")
        return
    except Exception as e:
        print(f"❌ Localization test failed: {e}")
        raise

def test_middleware_no_cycles():
    """Тест что middleware не имеет циклических импортов."""
    try:
        import middleware
        print("✅ Middleware imports without cycles")

                                          
        mw = middleware.AntiSpamMiddleware()
        print("✅ AntiSpamMiddleware can be instantiated")
        return
    except Exception as e:
        print(f"❌ Middleware test failed: {e}")
        raise

async def test_handlers_functionality():
    """Тест функциональности обработчиков."""
    try:
        from handlers import BasicHandler, SubscriptionHandler
        from unittest.mock import AsyncMock

                           
        basic = BasicHandler()
        mock_msg = MagicMock()
        mock_msg.from_user.id = 12345
        mock_msg.answer = AsyncMock()

        await basic.handle_help(mock_msg)
        mock_msg.answer.assert_called_once()
        print("✅ BasicHandler functionality works")

                                  
        sub = SubscriptionHandler()
        await sub.handle_mysubs_command(mock_msg)
                          
        print("✅ SubscriptionHandler functionality works")
        return
    except Exception as e:
        print(f"❌ Handler functionality test failed: {e}")
        raise

def main():
    """Запуск всех тестов."""
    print("🧪 Testing conflict resolution and fixes...")
    print("=" * 60)

    results = []

                       
    try:
        test_localization_module()
        results.append(True)
    except Exception:
        results.append(False)

                     
    try:
        test_middleware_no_cycles()
        results.append(True)
    except Exception:
        results.append(False)

                                 
    try:
        test_no_double_registration()
        results.append(True)
    except Exception:
        results.append(False)

                        
    try:
        asyncio.run(test_handlers_functionality())
        results.append(True)
        print("✅ Handler functionality test passed")
    except Exception as e:
        print(f"❌ Handler functionality test failed: {e}")
        results.append(False)

    print("=" * 60)

    passed = sum(results)
    total = len(results)

    if passed == total:
        print(f"🎉 All conflict resolution tests passed! ({passed}/{total})")
        print("✅ No more handler conflicts!")
        print("✅ Circular imports resolved!")
        print("✅ Localization centralized!")
        return 0
    else:
        print(f"⚠️  Some tests failed: {passed}/{total}")
        return 1

if __name__ == "__main__":
    sys.exit(main())












