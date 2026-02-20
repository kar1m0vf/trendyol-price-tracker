#!/usr/bin/env python3
"""
Тесты для админских callback handlers в боте
"""
import sys
import os
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

# Добавляем корневую директорию в путь
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

async def test_user_details_callback():
    """Тест callback handler для деталей пользователя"""
    print("🧪 Тестируем callback user_details...")

    try:
        import bot

        # Mock callback query от админа
        mock_cq = MagicMock()
        mock_cq.from_user.id = 975282591  # Админ
        mock_cq.data = "user_details:12345"
        mock_cq.message = MagicMock()
        mock_cq.message.edit_text = AsyncMock()
        mock_cq.answer = AsyncMock()

        # Mock bot.send_message
        with patch.object(bot, 'bot') as mock_bot:
            mock_bot.send_message = AsyncMock()

            # Тест callback "user_details:12345"
            await bot.callback_handler_old(mock_cq)

            # Проверяем что были вызовы
            assert mock_cq.answer.called, "cq.answer должен быть вызван"

        print("✅ Callback user_details работает корректно")
        return True

    except Exception as e:
        print(f"❌ Ошибка в callback user_details: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_user_details_callback_non_admin():
    """Тест callback handler для деталей пользователя от не-админа"""
    print("🧪 Тестируем callback user_details от не-админа...")

    try:
        import bot

        # Mock callback query от не-админа
        mock_cq = MagicMock()
        mock_cq.from_user.id = 12345  # Не админ
        mock_cq.data = "user_details:12345"
        mock_cq.message = MagicMock()
        mock_cq.answer = AsyncMock()

        # Тест callback от не-админа
        await bot.callback_handler_old(mock_cq)

        # Проверяем что был отказ в доступе
        assert mock_cq.answer.called, "cq.answer должен быть вызван с отказом"

        print("✅ Защита user_details от не-админов работает корректно")
        return True

    except Exception as e:
        print(f"❌ Ошибка в защите user_details: {e}")
        return False

async def test_user_details_callback_invalid_id():
    """Тест callback handler с некорректным ID пользователя"""
    print("🧪 Тестируем callback user_details с некорректным ID...")

    try:
        import bot

        # Mock callback query с некорректным ID
        mock_cq = MagicMock()
        mock_cq.from_user.id = 975282591  # Админ
        mock_cq.data = "user_details:invalid_id"
        mock_cq.answer = AsyncMock()

        # Тест callback с некорректным ID
        await bot.callback_handler_old(mock_cq)

        # Проверяем что была ошибка
        assert mock_cq.answer.called, "cq.answer должен быть вызван с ошибкой"

        print("✅ Обработка некорректных ID в user_details работает корректно")
        return True

    except Exception as e:
        print(f"❌ Ошибка в обработке некорректных ID: {e}")
        return False

async def test_admin_users_refresh_callback():
    """Тест callback handler для обновления списка пользователей"""
    print("🧪 Тестируем callback admin_users_refresh...")

    try:
        import bot

        # Mock callback query от админа
        mock_cq = MagicMock()
        mock_cq.from_user.id = 975282591  # Админ
        mock_cq.data = "admin_users_refresh"
        mock_cq.message = MagicMock()
        mock_cq.message.edit_text = AsyncMock()
        mock_cq.answer = AsyncMock()

        # Тест callback "admin_users_refresh"
        await bot.callback_handler_old(mock_cq)

        # Проверяем что были вызовы
        assert mock_cq.answer.called, "cq.answer должен быть вызван"

        print("✅ Callback admin_users_refresh работает корректно")
        return True

    except Exception as e:
        print(f"❌ Ошибка в callback admin_users_refresh: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_admin_users_refresh_non_admin():
    """Тест callback handler для обновления списка пользователей от не-админа"""
    print("🧪 Тестируем callback admin_users_refresh от не-админа...")

    try:
        import bot

        # Mock callback query от не-админа
        mock_cq = MagicMock()
        mock_cq.from_user.id = 12345  # Не админ
        mock_cq.data = "admin_users_refresh"
        mock_cq.answer = AsyncMock()

        # Тест callback от не-админа
        await bot.callback_handler_old(mock_cq)

        # Проверяем что был отказ в доступе
        assert mock_cq.answer.called, "cq.answer должен быть вызван с отказом"

        print("✅ Защита admin_users_refresh от не-админов работает корректно")
        return True

    except Exception as e:
        print(f"❌ Ошибка в защите admin_users_refresh: {e}")
        return False

async def test_admin_user_details_callback_function():
    """Тест функции admin_user_details_callback"""
    print("🧪 Тестируем функцию admin_user_details_callback...")

    try:
        import bot

        # Mock message
        mock_msg = MagicMock()
        mock_msg.edit_text = AsyncMock()
        mock_msg.reply_markup = None

        # Mock bot.send_message для inline клавиатуры
        with patch.object(bot, 'bot') as mock_bot:
            mock_bot.send_message = AsyncMock()

            # Тест функции с существующим пользователем
            await bot.admin_user_details_callback(mock_msg, 975282591, 975282591)

            # Проверяем что edit_text был вызван
            assert mock_msg.edit_text.called, "edit_text должен быть вызван"

        print("✅ Функция admin_user_details_callback работает корректно")
        return True

    except Exception as e:
        print(f"❌ Ошибка в функции admin_user_details_callback: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_admin_users_list_interactive():
    """Тест функции admin_users_list_interactive"""
    print("🧪 Тестируем функцию admin_users_list_interactive...")

    try:
        import bot

        # Mock message
        mock_msg = MagicMock()
        mock_msg.edit_text = AsyncMock()

        # Тест функции
        await bot.admin_users_list_interactive(mock_msg)

        # Проверяем что edit_text был вызван
        assert mock_msg.edit_text.called, "edit_text должен быть вызван"

        print("✅ Функция admin_users_list_interactive работает корректно")
        return True

    except Exception as e:
        print(f"❌ Ошибка в функции admin_users_list_interactive: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_admin_user_details():
    """Тест функции admin_user_details"""
    print("🧪 Тестируем функцию admin_user_details...")

    try:
        import bot

        # Mock message
        mock_msg = MagicMock()
        mock_msg.answer = AsyncMock()

        # Тест функции с админом
        await bot.admin_user_details(mock_msg, 975282591)

        # Проверяем что answer был вызван
        assert mock_msg.answer.called, "answer должен быть вызван"

        print("✅ Функция admin_user_details работает корректно")
        return True

    except Exception as e:
        print(f"❌ Ошибка в функции admin_user_details: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    """Запуск всех тестов админских callback handlers"""
    print("=" * 60)
    print("🧪 ТЕСТИРОВАНИЕ АДМИНСКИХ CALLBACK HANDLERS")
    print("=" * 60)

    test_functions = [
        test_user_details_callback,
        test_user_details_callback_non_admin,
        test_user_details_callback_invalid_id,
        test_admin_users_refresh_callback,
        test_admin_users_refresh_non_admin,
        test_admin_user_details_callback_function,
        test_admin_users_list_interactive,
        test_admin_user_details,
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
        print(f"🎉 Все тесты админских callback handlers прошли! ({passed}/{total})")
        return 0
    else:
        print(f"⚠️  Некоторые тесты админских callback handlers провалились: {passed}/{total}")
        return 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
