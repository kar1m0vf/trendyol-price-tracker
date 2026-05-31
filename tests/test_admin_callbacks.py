
"""
Тесты для админских callback handlers в боте
"""
import sys
import os
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

async def test_user_details_callback():
    """Тест callback handler для деталей пользователя"""
    print("🧪 Тестируем callback user_details...")

    try:
        import bot
        from handlers import CallbackHandler


        mock_cq = MagicMock()
        mock_cq.from_user.id = 975282591
        mock_cq.data = "user_details:12345"
        mock_cq.message = MagicMock()
        mock_cq.message.edit_text = AsyncMock()
        mock_cq.answer = AsyncMock()


        with patch.object(bot, 'bot') as mock_bot:
            mock_bot.send_message = AsyncMock()
            handler = CallbackHandler()
            handler._bot = mock_bot


            await handler.handle_admin_user_details(mock_cq)


            assert mock_cq.answer.called, "cq.answer должен быть вызван"

        print("✅ Callback user_details работает корректно")
        return

    except Exception as e:
        print(f"❌ Ошибка в callback user_details: {e}")
        import traceback
        traceback.print_exc()
        raise AssertionError("test reported failure")

async def test_user_details_callback_non_admin():
    """Тест callback handler для деталей пользователя от не-админа"""
    print("🧪 Тестируем callback user_details от не-админа...")

    try:
        import bot
        from handlers import CallbackHandler


        mock_cq = MagicMock()
        mock_cq.from_user.id = 12345
        mock_cq.data = "user_details:12345"
        mock_cq.message = MagicMock()
        mock_cq.answer = AsyncMock()


        handler = CallbackHandler()
        await handler.handle_admin_user_details(mock_cq)


        assert mock_cq.answer.called, "cq.answer должен быть вызван с отказом"

        print("✅ Защита user_details от не-админов работает корректно")
        return

    except Exception as e:
        print(f"❌ Ошибка в защите user_details: {e}")
        raise AssertionError("test reported failure")

async def test_user_details_callback_invalid_id():
    """Тест callback handler с некорректным ID пользователя"""
    print("🧪 Тестируем callback user_details с некорректным ID...")

    try:
        import bot
        from handlers import CallbackHandler


        mock_cq = MagicMock()
        mock_cq.from_user.id = 975282591
        mock_cq.data = "user_details:invalid_id"
        mock_cq.answer = AsyncMock()


        handler = CallbackHandler()
        await handler.handle_admin_user_details(mock_cq)


        assert mock_cq.answer.called, "cq.answer должен быть вызван с ошибкой"

        print("✅ Обработка некорректных ID в user_details работает корректно")
        return

    except Exception as e:
        print(f"❌ Ошибка в обработке некорректных ID: {e}")
        raise AssertionError("test reported failure")

async def test_admin_users_refresh_callback():
    """Тест callback handler для обновления списка пользователей"""
    print("🧪 Тестируем callback admin_users_refresh...")

    try:
        import bot
        from handlers import CallbackHandler


        mock_cq = MagicMock()
        mock_cq.from_user.id = 975282591
        mock_cq.data = "admin_users_refresh"
        mock_cq.message = MagicMock()
        mock_cq.message.edit_text = AsyncMock()
        mock_cq.answer = AsyncMock()


        handler = CallbackHandler()
        await handler.handle_main_callback(mock_cq)


        assert mock_cq.answer.called, "cq.answer должен быть вызван"

        print("✅ Callback admin_users_refresh работает корректно")
        return

    except Exception as e:
        print(f"❌ Ошибка в callback admin_users_refresh: {e}")
        import traceback
        traceback.print_exc()
        raise AssertionError("test reported failure")

async def test_admin_users_refresh_non_admin():
    """Тест callback handler для обновления списка пользователей от не-админа"""
    print("🧪 Тестируем callback admin_users_refresh от не-админа...")

    try:
        import bot
        from handlers import CallbackHandler


        mock_cq = MagicMock()
        mock_cq.from_user.id = 12345
        mock_cq.data = "admin_users_refresh"
        mock_cq.answer = AsyncMock()


        handler = CallbackHandler()
        await handler.handle_main_callback(mock_cq)


        assert mock_cq.answer.called, "cq.answer должен быть вызван с отказом"

        print("✅ Защита admin_users_refresh от не-админов работает корректно")
        return

    except Exception as e:
        print(f"❌ Ошибка в защите admin_users_refresh: {e}")
        raise AssertionError("test reported failure")

async def test_admin_user_details_callback_function():
    """Тест функции admin_user_details_callback"""
    print("🧪 Тестируем функцию admin_user_details_callback...")

    try:
        import bot


        mock_msg = MagicMock()
        mock_msg.edit_text = AsyncMock()
        mock_msg.reply_markup = None


        with patch.object(bot, 'bot') as mock_bot:
            mock_bot.send_message = AsyncMock()


            await bot.admin_user_details_callback(mock_msg, 975282591, 975282591)


            assert mock_msg.edit_text.called, "edit_text должен быть вызван"

        print("✅ Функция admin_user_details_callback работает корректно")
        return

    except Exception as e:
        print(f"❌ Ошибка в функции admin_user_details_callback: {e}")
        import traceback
        traceback.print_exc()
        raise AssertionError("test reported failure")

async def test_admin_users_list_interactive():
    """Тест функции admin_users_list_interactive"""
    print("🧪 Тестируем функцию admin_users_list_interactive...")

    try:
        import bot


        mock_msg = MagicMock()
        mock_msg.edit_text = AsyncMock()


        await bot.admin_users_list_interactive(mock_msg)


        assert mock_msg.edit_text.called, "edit_text должен быть вызван"

        print("✅ Функция admin_users_list_interactive работает корректно")
        return

    except Exception as e:
        print(f"❌ Ошибка в функции admin_users_list_interactive: {e}")
        import traceback
        traceback.print_exc()
        raise AssertionError("test reported failure")

async def test_admin_user_details():
    """Тест функции admin_user_details"""
    print("🧪 Тестируем функцию admin_user_details...")

    try:
        import bot


        mock_msg = MagicMock()
        mock_msg.answer = AsyncMock()


        await bot.admin_user_details(mock_msg, 975282591)


        assert mock_msg.answer.called, "answer должен быть вызван"

        print("✅ Функция admin_user_details работает корректно")
        return

    except Exception as e:
        print(f"❌ Ошибка в функции admin_user_details: {e}")
        import traceback
        traceback.print_exc()
        raise AssertionError("test reported failure")

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
            results.append(result is not False)
        except Exception as e:
            print(f"❌ Критическая ошибка в {test_func.__name__}: {e}")
            results.append(False)


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
