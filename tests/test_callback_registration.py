#!/usr/bin/env python3
"""
Тест для проверки регистрации callback обработчиков.
"""
import os
import sys
import asyncio
from unittest.mock import MagicMock, AsyncMock

# Устанавливаем переменную окружения для использования новых обработчиков
os.environ['USE_NEW_HANDLERS'] = 'true'

def test_callback_registration():
    """Тест что callback обработчики регистрируются правильно."""
    try:
        from aiogram import Dispatcher
        from handlers import CallbackHandler

        # Создаем mock dispatcher
        dp = MagicMock(spec=Dispatcher)
        dp.callback_query = MagicMock()

        # Создаем обработчик
        handler = CallbackHandler()

        # Регистрируем
        handler.register(dp)

        # Проверяем что методы register были вызваны
        assert dp.callback_query.register.called, "callback_query.register was not called"

        # Проверяем сколько раз был вызван register
        call_count = dp.callback_query.register.call_count
        print(f"✅ callback_query.register was called {call_count} times")

        # Проверяем что обработчики были переданы
        calls = dp.callback_query.register.call_args_list
        for i, call in enumerate(calls):
            handler_func = call[0][0]  # Первый аргумент - функция обработчик
            print(f"✅ Handler {i+1}: {handler_func.__name__}")

        # Успех — возвращаемся нормально (pytest воспринимает отсутствие исключений как успех)
        return
    except Exception as e:
        print(f"❌ Callback registration test failed: {e}")
        import traceback
        traceback.print_exc()
        # Пробрасываем исключение чтобы pytest корректно отметил падение теста
        raise

async def test_callback_execution():
    """Тест выполнения callback обработчика."""
    try:
        from handlers import CallbackHandler
        from aiogram.types import CallbackQuery

        handler = CallbackHandler()

        # Mock callback query
        mock_cq = MagicMock(spec=CallbackQuery)
        mock_cq.data = "lang:ru"
        mock_cq.from_user = MagicMock()
        mock_cq.from_user.id = 12345
        mock_cq.answer = AsyncMock()
        mock_cq.message = MagicMock()
        mock_cq.message.edit_text = AsyncMock()

        # Mock bot
        mock_bot = MagicMock()
        handler._bot = mock_bot

        # Выполняем обработчик
        await handler.handle_main_callback(mock_cq)

        # Проверяем что answer был вызван
        mock_cq.answer.assert_called()
        print("✅ Callback execution works")

        return
    except Exception as e:
        print(f"❌ Callback execution test failed: {e}")
        # Пробрасываем исключение для pytest
        raise

def main():
    """Запуск тестов."""
    print("🧪 Testing callback handler registration...")
    print("=" * 60)

    results = []

    # Тест регистрации
    try:
        test_callback_registration()
        results.append(True)
    except Exception:
        results.append(False)

    # Тест выполнения
    try:
        asyncio.run(test_callback_execution())
        results.append(True)
        print("✅ Callback execution test passed")
    except Exception as e:
        print(f"❌ Callback execution test failed: {e}")
        results.append(False)

    print("=" * 60)

    passed = sum(results)
    total = len(results)

    if passed == total:
        print(f"🎉 All callback tests passed! ({passed}/{total})")
        print("✅ Callback handlers are registered and working!")
        return 0
    else:
        print(f"⚠️  Some callback tests failed: {passed}/{total}")
        return 1

if __name__ == "__main__":
    sys.exit(main())












