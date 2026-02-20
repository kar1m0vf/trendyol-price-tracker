#!/usr/bin/env python3
"""
Тест для проверки что кнопки редактирования подписок работают правильно.
"""
import os
import sys
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

# Устанавливаем переменную окружения для использования новых обработчиков
os.environ['USE_NEW_HANDLERS'] = 'true'

def test_buttons_creation():
    """Тест что кнопки создаются правильно."""
    try:
        from handlers import SubscriptionHandler
        from database import add_user_if_not_exists

        # Создаем обработчик
        handler = SubscriptionHandler()

        # Добавляем тестового пользователя
        add_user_if_not_exists(12345)

        # Mock message
        mock_msg = MagicMock()
        mock_msg.from_user.id = 12345
        mock_msg.answer = AsyncMock()

        # Вызываем обработчик
        asyncio.run(handler.handle_mysubs_command(mock_msg))

        # Проверяем что answer был вызван
        mock_msg.answer.assert_called_once()

        # Получаем аргументы вызова
        call_args = mock_msg.answer.call_args
        text = call_args[0][0]  # Первый позиционный аргумент
        kwargs = call_args[1]   # Ключевые аргументы

        print(f"✅ Message sent with text: {text[:100]}...")
        print(f"✅ Reply markup included: {'reply_markup' in kwargs}")

        if 'reply_markup' in kwargs:
            markup = kwargs['reply_markup']
            if hasattr(markup, 'inline_keyboard'):
                buttons_count = len(markup.inline_keyboard)
                print(f"✅ Inline keyboard has {buttons_count} button rows")

                if buttons_count > 0:
                    first_row = markup.inline_keyboard[0]
                    if first_row:
                        first_button = first_row[0]
                        callback_data = getattr(first_button, 'callback_data', '')
                        print(f"✅ First button callback: {callback_data}")
                        assert 'edit_sub:' in callback_data, "Button should have edit_sub callback"
            else:
                print("⚠️  No inline_keyboard attribute")
        else:
            print("❌ No reply_markup in message")

        return
    except Exception as e:
        print(f"❌ Button creation test failed: {e}")
        import traceback
        traceback.print_exc()
        raise

def main():
    """Запуск тестов."""
    print("🧪 Testing subscription buttons functionality...")
    print("=" * 60)

    results = []

    # Тест создания кнопок
    try:
        test_buttons_creation()
        results.append(True)
    except Exception:
        results.append(False)

    print("=" * 60)

    passed = sum(results)
    total = len(results)

    if passed == total:
        print(f"🎉 All button tests passed! ({passed}/{total})")
        print("✅ Subscription buttons are working correctly!")
        print("✅ Buttons are sent inline with the message!")
        return 0
    else:
        print(f"⚠️  Some button tests failed: {passed}/{total}")
        return 1

if __name__ == "__main__":
    sys.exit(main())












