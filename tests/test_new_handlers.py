#!/usr/bin/env python3
"""
Тесты для новых обработчиков.
"""
import os
import sys
import asyncio
from unittest.mock import AsyncMock, MagicMock

# Устанавливаем переменную окружения для использования новых обработчиков
os.environ['USE_NEW_HANDLERS'] = 'true'

def test_basic_handlers_import():
    """Тест импорта новых обработчиков."""
    try:
        from handlers import BasicHandler
        print("✅ BasicHandler import OK")

        # Создаем экземпляр
        handler = BasicHandler()
        print("✅ BasicHandler instance created")

        # Проверяем методы
        assert hasattr(handler, 'handle_start'), "handle_start method missing"
        assert hasattr(handler, 'handle_help'), "handle_help method missing"
        assert hasattr(handler, 'handle_language_command'), "handle_language_command method missing"
        print("✅ All required methods present")

        return
    except Exception as e:
        print(f"❌ BasicHandler test failed: {e}")
        raise

def test_keyboard_import():
    """Тест импорта клавиатур."""
    try:
        import keyboards
        print("✅ keyboards import OK")

        # Проверяем функции
        assert hasattr(keyboards, 'get_main_kb'), "get_main_kb function missing"
        print("✅ Keyboard functions present")

        return
    except Exception as e:
        print(f"❌ Keyboard test failed: {e}")
        raise

def test_services_import():
    """Тест импорта сервисов."""
    try:
        from services import NotificationService
        print("✅ NotificationService import OK")

        # Создаем экземпляр (нужен mock bot)
        mock_bot = MagicMock()
        service = NotificationService(mock_bot)
        print("✅ NotificationService instance created")

        # Проверяем методы
        assert hasattr(service, 'send_notification_safe'), "send_notification_safe method missing"
        print("✅ Service methods present")

        return
    except Exception as e:
        print(f"❌ Service test failed: {e}")
        raise

async def test_handler_functionality():
    """Тест функциональности обработчиков."""
    try:
        from handlers import BasicHandler
        from unittest.mock import AsyncMock

        handler = BasicHandler()

        # Mock message
        mock_message = MagicMock()
        mock_message.from_user.id = 12345
        mock_message.answer = AsyncMock()

        # Тестируем handle_help (простая функция)
        await handler.handle_help(mock_message)

        # Проверяем что answer был вызван
        mock_message.answer.assert_called_once()
        print("✅ Handler functionality test passed")

        return
    except Exception as e:
        print(f"❌ Handler functionality test failed: {e}")
        raise

def main():
    """Запуск всех тестов."""
    print("🧪 Testing new handler architecture...")
    print("=" * 50)

    results = []

    # Тесты импорта
    try:
        test_basic_handlers_import()
        results.append(True)
    except Exception:
        results.append(False)

    try:
        test_keyboard_import()
        results.append(True)
    except Exception:
        results.append(False)

    try:
        test_services_import()
        results.append(True)
    except Exception:
        results.append(False)

    # Асинхронный тест
    try:
        asyncio.run(test_handler_functionality())
        results.append(True)
        print("✅ Handler functionality test passed")
    except Exception as e:
        print(f"❌ Handler functionality test failed: {e}")
        results.append(False)

    print("=" * 50)

    passed = sum(results)
    total = len(results)

    if passed == total:
        print(f"🎉 All tests passed! ({passed}/{total})")
        print("✅ New handler architecture is ready!")
        return 0
    else:
        print(f"⚠️  Some tests failed: {passed}/{total}")
        return 1

if __name__ == "__main__":
    sys.exit(main())












