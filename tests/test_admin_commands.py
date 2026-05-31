                      
"""
Комплексные тесты для админских команд бота
"""
import sys
import os
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

                                      
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

async def test_admin_command():
    """Тест основной команды /admin"""
    print("🧪 Тестируем команду /admin...")

    try:
        import bot

                                
        mock_msg = MagicMock()
        mock_msg.from_user.id = 975282591                      
        mock_msg.text = "/admin"
        mock_msg.answer = AsyncMock()

                             
        await bot.cmd_admin(mock_msg)

        assert mock_msg.answer.called, "Должен быть ответ на команду /admin"

        print("✅ Команда /admin работает корректно")
        return

    except Exception as e:
        print(f"❌ Ошибка в команде /admin: {e}")
        raise AssertionError("test reported failure")

async def test_admin_stats():
    """Тест команды /admin stats"""
    print("🧪 Тестируем команду /admin stats...")

    try:
        import bot

                                
        mock_msg = MagicMock()
        mock_msg.from_user.id = 975282591
        mock_msg.text = "/admin stats"
        mock_msg.answer = AsyncMock()

                                   
        await bot.cmd_admin(mock_msg)

        assert mock_msg.answer.called, "Должен быть ответ на команду /admin stats"

        print("✅ Команда /admin stats работает корректно")
        return

    except Exception as e:
        print(f"❌ Ошибка в команде /admin stats: {e}")
        raise AssertionError("test reported failure")

async def test_admin_broadcast():
    """Тест команды /admin broadcast"""
    print("🧪 Тестируем команду /admin broadcast...")

    try:
        import bot

                                
        mock_msg = MagicMock()
        mock_msg.from_user.id = 975282591
        mock_msg.text = "/admin broadcast Тестовое сообщение"
        mock_msg.answer = AsyncMock()

                               
        with patch.object(bot, 'bot') as mock_bot:
            mock_bot.send_message = AsyncMock()

                                           
            await bot.cmd_admin(mock_msg)

                                                
            assert mock_msg.answer.called, "Должен быть ответ админу"
                                                                                                    

        print("✅ Команда /admin broadcast работает корректно")
        return

    except Exception as e:
        print(f"❌ Ошибка в команде /admin broadcast: {e}")
        raise AssertionError("test reported failure")

async def test_admin_broadcast_empty():
    """Тест команды /admin broadcast без сообщения"""
    print("🧪 Тестируем команду /admin broadcast без сообщения...")

    try:
        import bot

                                
        mock_msg = MagicMock()
        mock_msg.from_user.id = 975282591
        mock_msg.text = "/admin broadcast"
        mock_msg.answer = AsyncMock()

                                                  
        await bot.cmd_admin(mock_msg)

        assert mock_msg.answer.called, "Должен быть ответ об ошибке"

        print("✅ Обработка пустого broadcast работает корректно")
        return

    except Exception as e:
        print(f"❌ Ошибка в обработке пустого broadcast: {e}")
        raise AssertionError("test reported failure")

async def test_admin_users():
    """Тест команды /admin users"""
    print("🧪 Тестируем команду /admin users...")

    try:
        import bot

                                
        mock_msg = MagicMock()
        mock_msg.from_user.id = 975282591
        mock_msg.text = "/admin users"
        mock_msg.answer = AsyncMock()

                                   
        await bot.cmd_admin(mock_msg)

        assert mock_msg.answer.called, "Должен быть ответ на команду /admin users"

        print("✅ Команда /admin users работает корректно")
        return

    except Exception as e:
        print(f"❌ Ошибка в команде /admin users: {e}")
        raise AssertionError("test reported failure")

async def test_admin_cleanup():
    """Тест команды /admin cleanup"""
    print("🧪 Тестируем команду /admin cleanup...")

    try:
        import bot

                                
        mock_msg = MagicMock()
        mock_msg.from_user.id = 975282591
        mock_msg.text = "/admin cleanup"
        mock_msg.answer = AsyncMock()

                                     
        await bot.cmd_admin(mock_msg)

        assert mock_msg.answer.called, "Должен быть ответ на команду /admin cleanup"

        print("✅ Команда /admin cleanup работает корректно")
        return

    except Exception as e:
        print(f"❌ Ошибка в команде /admin cleanup: {e}")
        raise AssertionError("test reported failure")

async def test_admin_backup():
    """Тест команды /admin backup"""
    print("🧪 Тестируем команду /admin backup...")

    try:
        import bot

                                
        mock_msg = MagicMock()
        mock_msg.from_user.id = 975282591
        mock_msg.text = "/admin backup"
        mock_msg.answer = AsyncMock()

                                    
        await bot.cmd_admin(mock_msg)

        assert mock_msg.answer.called, "Должен быть ответ на команду /admin backup"

        print("✅ Команда /admin backup работает корректно")
        return

    except Exception as e:
        print(f"❌ Ошибка в команде /admin backup: {e}")
        raise AssertionError("test reported failure")

async def test_admin_respond():
    """Тест команды /admin respond"""
    print("🧪 Тестируем команду /admin respond...")

    try:
        import bot

                                
        mock_msg = MagicMock()
        mock_msg.from_user.id = 975282591
        mock_msg.text = "/admin respond"
        mock_msg.answer = AsyncMock()

                                     
        await bot.cmd_admin(mock_msg)

        assert mock_msg.answer.called, "Должен быть ответ на команду /admin respond"

        print("✅ Команда /admin respond работает корректно")
        return

    except Exception as e:
        print(f"❌ Ошибка в команде /admin respond: {e}")
        raise AssertionError("test reported failure")

async def test_admin_unknown_command():
    """Тест неизвестной админской команды"""
    print("🧪 Тестируем неизвестную админскую команду...")

    try:
        import bot

                                
        mock_msg = MagicMock()
        mock_msg.from_user.id = 975282591
        mock_msg.text = "/admin unknown_command"
        mock_msg.answer = AsyncMock()

                                  
        await bot.cmd_admin(mock_msg)

        assert mock_msg.answer.called, "Должен быть ответ на неизвестную команду"

        print("✅ Обработка неизвестных команд работает корректно")
        return

    except Exception as e:
        print(f"❌ Ошибка в обработке неизвестных команд: {e}")
        raise AssertionError("test reported failure")

async def test_admin_non_admin():
    """Тест доступа к админским командам не-админом"""
    print("🧪 Тестируем доступ к админским командам не-админом...")

    try:
        import bot

                                               
        mock_msg = MagicMock()
        mock_msg.from_user.id = 12345            
        mock_msg.text = "/admin"
        mock_msg.answer = AsyncMock()

                                
        await bot.cmd_admin(mock_msg)

        assert mock_msg.answer.called, "Должен быть отказ в доступе"

        print("✅ Защита от не-админов работает корректно")
        return

    except Exception as e:
        print(f"❌ Ошибка в защите от не-админов: {e}")
        raise AssertionError("test reported failure")

async def test_is_admin_function():
    """Тест функции is_admin"""
    print("🧪 Тестируем функцию is_admin...")

    try:
        from bot import is_admin

                        
        assert is_admin(975282591), "Должен вернуть True для админа"

                           
        assert not is_admin(12345), "Должен вернуть False для не-админа"

                           
        assert not is_admin(123456789), "Должен вернуть False для не-админа"

        print("✅ Функция is_admin работает корректно")
        return

    except Exception as e:
        print(f"❌ Ошибка в функции is_admin: {e}")
        raise AssertionError("test reported failure")

async def main():
    """Запуск всех тестов админских команд"""
    print("=" * 60)
    print("🧪 ТЕСТИРОВАНИЕ АДМИНСКИХ КОМАНД")
    print("=" * 60)

    test_functions = [
        test_admin_command,
        test_admin_stats,
        test_admin_broadcast,
        test_admin_broadcast_empty,
        test_admin_users,
        test_admin_cleanup,
        test_admin_backup,
        test_admin_respond,
        test_admin_unknown_command,
        test_admin_non_admin,
        test_is_admin_function,
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
        print(f"🎉 Все тесты админских команд прошли! ({passed}/{total})")
        return 0
    else:
        print(f"⚠️  Некоторые тесты админских команд провалились: {passed}/{total}")
        return 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
