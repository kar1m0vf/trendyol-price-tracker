#!/usr/bin/env python3
"""
Тесты для новых обработчиков callback'ов.
"""
import os
import sys
import asyncio
from unittest.mock import AsyncMock, MagicMock

# Устанавливаем переменную окружения для использования новых обработчиков
os.environ['USE_NEW_HANDLERS'] = 'true'

def test_callback_handlers_import():
    """Тест импорта обработчиков callback'ов."""
    try:
        from handlers import CallbackHandler
        print("✅ CallbackHandler import OK")

        # Создаем экземпляр
        handler = CallbackHandler()
        print("✅ CallbackHandler instance created")

        # Проверяем методы
        assert hasattr(handler, 'handle_main_callback'), "handle_main_callback method missing"
        assert hasattr(handler, 'handle_admin_user_details'), "handle_admin_user_details method missing"
        print("✅ All required methods present")

        return
    except Exception as e:
        print(f"❌ CallbackHandler test failed: {e}")
        raise

async def test_callback_functionality():
    """Тест функциональности callback обработчиков."""
    try:
        from handlers import CallbackHandler
        from aiogram.types import CallbackQuery

        handler = CallbackHandler()

        # Mock callback query
        mock_cq = MagicMock(spec=CallbackQuery)
        mock_cq.data = "lang:ru"
        # Ensure nested from_user is present on the mock
        mock_cq.from_user = MagicMock()
        mock_cq.from_user.id = 12345
        mock_cq.answer = AsyncMock()
        mock_cq.message = MagicMock()
        mock_cq.message.edit_text = AsyncMock()

        # Mock bot
        mock_bot = MagicMock()
        mock_bot.send_message = AsyncMock()
        handler._bot = mock_bot

        # Test language change callback
        await handler.handle_main_callback(mock_cq)
        mock_cq.answer.assert_called_once()
        print("✅ Callback functionality works")

        return
    except Exception as e:
        print(f"❌ Callback functionality test failed: {e}")
        raise

def main():
    """Запуск всех тестов."""
    print("🧪 Testing new callback handlers...")
    print("=" * 50)

    results = []

    # Тест импорта
    try:
        test_callback_handlers_import()
        results.append(True)
    except Exception:
        results.append(False)

    # Тест функциональности
    try:
        asyncio.run(test_callback_functionality())
        results.append(True)
        print("✅ Callback functionality test passed")
    except Exception as e:
        print(f"❌ Callback functionality test failed: {e}")
        results.append(False)

    print("=" * 50)

    passed = sum(results)
    total = len(results)

    if passed == total:
        print(f"🎉 All callback tests passed! ({passed}/{total})")
        print("✅ New callback handlers are ready!")
        return 0
    else:
        print(f"⚠️  Some tests failed: {passed}/{total}")
        return 1

if __name__ == "__main__":
    sys.exit(main())












