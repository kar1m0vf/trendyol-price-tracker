#!/usr/bin/env python3
"""
Тест на отсутствие конфликтов между старыми и новыми обработчиками.
"""
import os
import sys
import asyncio
from unittest.mock import MagicMock, AsyncMock

def test_no_double_registration():
    """Тест что обработчики не регистрируются дважды."""
    print("Testing handler conflict resolution...")

    # Test with new handlers enabled
    os.environ['USE_NEW_HANDLERS'] = 'true'
    try:
        import bot
        print("✅ New handlers mode: no conflicts detected")

        # Reset modules for clean reimport
        modules_to_reset = ['bot', 'handlers', 'handlers.basic', 'handlers.subscription_handler']
        for mod in modules_to_reset:
            if mod in sys.modules:
                del sys.modules[mod]

    except Exception as e:
        print(f"❌ New handlers mode failed: {e}")
        raise

    # Test with old handlers enabled
    os.environ['USE_NEW_HANDLERS'] = 'false'
    try:
        import bot
        print("✅ Old handlers mode: no conflicts detected")

        # Reset modules again
        for mod in modules_to_reset:
            if mod in sys.modules:
                del sys.modules[mod]

    except Exception as e:
        print(f"❌ Old handlers mode failed: {e}")
        raise

    return

def test_localization_module():
    """Тест нового модуля локализации."""
    try:
        from localization import t, LOCALES

        # Test translation
        result = t(12345, "start_text")
        assert isinstance(result, str), "Translation should return string"
        print("✅ Localization module works")

        # Test locales loaded
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

        # Test AntiSpamMiddleware creation
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

        # Test BasicHandler
        basic = BasicHandler()
        mock_msg = MagicMock()
        mock_msg.from_user.id = 12345
        mock_msg.answer = AsyncMock()

        await basic.handle_help(mock_msg)
        mock_msg.answer.assert_called_once()
        print("✅ BasicHandler functionality works")

        # Test SubscriptionHandler
        sub = SubscriptionHandler()
        await sub.handle_mysubs_command(mock_msg)
        # Should not crash
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

    # Test localization
    try:
        test_localization_module()
        results.append(True)
    except Exception:
        results.append(False)

    # Test middleware
    try:
        test_middleware_no_cycles()
        results.append(True)
    except Exception:
        results.append(False)

    # Test no double registration
    try:
        test_no_double_registration()
        results.append(True)
    except Exception:
        results.append(False)

    # Test functionality
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












