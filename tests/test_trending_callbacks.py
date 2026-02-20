#!/usr/bin/env python3
"""
Тесты для callback handlers трендов в боте
"""
import sys
import os
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

# Добавляем корневую директорию в путь
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

async def test_trending_callbacks():
    """Тест callback handlers для трендов"""
    print("🧪 Тестируем callback handlers трендов...")

    try:
        # Импортируем bot (это важно для регистрации handlers)
        import bot

        # Mock callback query для трендов
        mock_cq = MagicMock()
        mock_cq.from_user.id = 12345
        mock_cq.data = "trend:all"
        mock_cq.message = MagicMock()
        mock_cq.message.edit_text = AsyncMock()
        mock_cq.message.delete = AsyncMock()
        mock_cq.answer = AsyncMock()

        # Mock bot.send_message
        with patch.object(bot, 'bot') as mock_bot:
            mock_bot.send_message = AsyncMock()

            # Тест callback "trend:all"
            await bot.callback_handler_old(mock_cq)

            # Проверяем что send_message был вызван
            assert mock_bot.send_message.called, "bot.send_message не был вызван для trend:all"

            # Сброс моков
            mock_bot.send_message.reset_mock()
            mock_cq.data = "trend:catmenu"
            mock_cq.message.edit_text.reset_mock()

            # Тест callback "trend:catmenu"
            await bot.callback_handler_old(mock_cq)

            # Проверяем что edit_text был вызван
            assert mock_cq.message.edit_text.called, "message.edit_text не был вызван для trend:catmenu"

            # Сброс моков
            mock_cq.message.edit_text.reset_mock()
            mock_cq.data = "trend:cat:electronics"

            # Тест callback "trend:cat:electronics"
            await bot.callback_handler_old(mock_cq)

            # Проверяем что send_message был вызван
            assert mock_bot.send_message.called, "bot.send_message не был вызван для trend:cat:electronics"

            # Сброс моков
            mock_bot.send_message.reset_mock()
            mock_cq.data = "trend:search"

            # Тест callback "trend:search"
            await bot.callback_handler_old(mock_cq)

            # Проверяем что edit_text был вызван
            assert mock_cq.message.edit_text.called, "message.edit_text не был вызван для trend:search"

        print("✅ Callback handlers трендов работают корректно")
        return True

    except Exception as e:
        print(f"❌ Ошибка в callback handlers трендов: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_trending_menu_kb():
    """Тест клавиатуры меню трендов"""
    print("🧪 Тестируем клавиатуру меню трендов...")

    try:
        from bot import trending_menu_kb

        kb = trending_menu_kb(12345)
        assert kb is not None, "Клавиатура не создана"

        # Проверяем что есть кнопки
        assert hasattr(kb, 'inline_keyboard'), "Клавиатура должна иметь inline_keyboard"
        assert len(kb.inline_keyboard) > 0, "Клавиатура должна содержать кнопки"

        # Проверяем callback_data кнопок
        button_callbacks = []
        for row in kb.inline_keyboard:
            for button in row:
                if hasattr(button, 'callback_data'):
                    button_callbacks.append(button.callback_data)

        expected_callbacks = ["trend:all", "trend:catmenu", "trend:search"]
        for expected in expected_callbacks:
            assert expected in button_callbacks, f"Кнопка с callback_data '{expected}' не найдена"

        print("✅ Клавиатура меню трендов работает корректно")
        return True

    except Exception as e:
        print(f"❌ Ошибка в клавиатуре меню трендов: {e}")
        return False

async def test_trending_categories_kb():
    """Тест клавиатуры категорий трендов"""
    print("🧪 Тестируем клавиатуру категорий трендов...")

    try:
        from bot import trending_categories_kb

        kb = trending_categories_kb(12345)
        assert kb is not None, "Клавиатура категорий не создана"

        # Проверяем что есть кнопки
        assert hasattr(kb, 'inline_keyboard'), "Клавиатура должна иметь inline_keyboard"
        assert len(kb.inline_keyboard) > 0, "Клавиатура должна содержать кнопки"

        # Проверяем callback_data кнопок
        button_callbacks = []
        for row in kb.inline_keyboard:
            for button in row:
                if hasattr(button, 'callback_data'):
                    button_callbacks.append(button.callback_data)

        expected_callbacks = ["trend:cat:electronics", "trend:cat:clothing", "trend:cat:shoes", "trend:cat:home"]
        for expected in expected_callbacks:
            assert expected in button_callbacks, f"Кнопка с callback_data '{expected}' не найдена"

        print("✅ Клавиатура категорий трендов работает корректно")
        return True

    except Exception as e:
        print(f"❌ Ошибка в клавиатуре категорий трендов: {e}")
        return False

async def test_format_trending_items():
    """Тест функции format_trending_items"""
    print("🧪 Тестируем format_trending_items...")

    try:
        from bot import format_trending_items

        # Тест с пустым списком
        result_empty = format_trending_items(12345, [])
        assert isinstance(result_empty, str), "Должен вернуть строку"
        assert len(result_empty) == 0, "Пустой список должен вернуть пустую строку"

        # Тест с товарами
        items = [
            ("iPhone 15 Pro", 45000.0, "https://trendyol.com/iphone-p-123"),
            ("Samsung Galaxy", None, "https://trendyol.com/samsung-p-456"),
            ("Test Product Very Long Name That Should Be Truncated", 1000.0, "https://trendyol.com/test-p-789")
        ]

        result = format_trending_items(12345, items)
        assert isinstance(result, str), "Должен вернуть строку"
        assert len(result) > 0, "Строка не должна быть пустой"

        # Проверяем что цены отформатированы правильно
        assert "45000.0 TL" in result, "Цена должна быть отформатирована"
        assert "цена неизвестна" in result, "Неизвестная цена должна быть обработана"

        print("✅ format_trending_items работает корректно")
        return True

    except Exception as e:
        print(f"❌ Ошибка в format_trending_items: {e}")
        return False

async def test_send_trending_list():
    """Тест функции send_trending_list"""
    print("🧪 Тестируем send_trending_list...")

    try:
        from bot import send_trending_list

        # Mock bot
        with patch('bot.bot') as mock_bot:
            mock_bot.send_message = AsyncMock()

            # Тест с пустым списком
            await send_trending_list(12345, [])
            assert mock_bot.send_message.called, "send_message должен быть вызван для пустого списка"

            # Проверяем что отправлено сообщение о недоступности
            call_args = mock_bot.send_message.call_args
            message_text = call_args[0][1]  # второй аргумент - текст сообщения
            assert "недоступ" in message_text.lower() or "доступ" in message_text.lower(), \
                "Должно быть сообщение о недоступности"

            # Сброс мока
            mock_bot.send_message.reset_mock()

            # Тест с товарами
            items = [("Test Product", 1000.0, "https://trendyol.com/test-p-123")]
            await send_trending_list(12345, items)

            assert mock_bot.send_message.called, "send_message должен быть вызван для списка товаров"

            # Проверяем что отправлено 1 сообщение (заголовок + товары вместе)
            assert mock_bot.send_message.call_count == 1, "Должно быть отправлено 1 сообщение"

        print("✅ send_trending_list работает корректно")
        return True

    except Exception as e:
        print(f"❌ Ошибка в send_trending_list: {e}")
        return False

async def main():
    """Запуск всех тестов трендов в боте"""
    print("=" * 60)
    print("🧪 ТЕСТИРОВАНИЕ ТРЕНДОВ В БОТЕ")
    print("=" * 60)

    test_functions = [
        test_trending_callbacks,
        test_trending_menu_kb,
        test_trending_categories_kb,
        test_format_trending_items,
        test_send_trending_list,
    ]

    results = []

    for test_func in test_functions:
        try:
            result = await test_func()
            results.append(result)
        except Exception as e:
            print(f"❌ Критическая ошибка в {test_func.__name__}: {e}")
            results.append(False)

    # Итоги
    print("\n" + "=" * 60)
    passed = sum(results)
    total = len(results)

    if passed == total:
        print(f"🎉 Все тесты трендов в боте прошли! ({passed}/{total})")
        return 0
    else:
        print(f"⚠️  Некоторые тесты трендов в боте провалились: {passed}/{total}")
        return 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
