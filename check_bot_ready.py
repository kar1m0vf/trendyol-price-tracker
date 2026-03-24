                      
"""
Скрипт проверки что бот готов к запуску.
Проверяет все критические компоненты.
"""

import sys
from pathlib import Path

def check_env_file():
    """Проверка что .env файл существует и содержит BOT_TOKEN"""
    env_path = Path(".env")
    if not env_path.exists():
        print("❌ .env файл не найден")
        return False
    
    with open(env_path) as f:
        content = f.read()
        if "BOT_TOKEN=" not in content:
            print("❌ BOT_TOKEN не найден в .env файле")
            return False
    
    print("✅ .env файл найден и содержит BOT_TOKEN")
    return True


def check_dotenv_installed():
    """Проверка что python-dotenv установлен"""
    try:
        import dotenv
        print("✅ python-dotenv установлен")
        return True
    except ImportError:
        print("❌ python-dotenv не установлен")
        print("   Выполните: pip install python-dotenv")
        return False


def check_config_import():
    """Проверка что config.py импортируется без ошибок"""
    try:
        from config import BOT_TOKEN, _check_bot_token
        if BOT_TOKEN:
            print(f"✅ config.py импортирован успешно")
            print(f"   BOT_TOKEN загружен: {bool(BOT_TOKEN)}")
            return True
        else:
            print("❌ BOT_TOKEN не загружен из .env")
            return False
    except Exception as e:
        print(f"❌ Ошибка при импорте config: {e}")
        return False


def check_bot_initialization():
    """Проверка что Bot инициализируется без ошибок"""
    try:
        from bot import bot, dp, check_all
        print("✅ bot.py загружен и Bot инициализирован")
        return True
    except Exception as e:
        print(f"❌ Ошибка при инициализации bot: {e}")
        return False


def check_database():
    """Проверка что database.py работает"""
    try:
        from database import (
            init_db, 
            get_user_settings,
            update_user_settings,
            save_price_point
        )
        print("✅ database.py загружен со всеми новыми функциями")
        return True
    except Exception as e:
        print(f"❌ Ошибка при импорте database: {e}")
        return False


def check_token_validation():
    """Проверка что валидация токена работает"""
    try:
        from config import _check_bot_token
        _check_bot_token()
        print("✅ Валидация BOT_TOKEN пройдена")
        return True
    except ValueError as e:
        print(f"❌ BOT_TOKEN validation error: {e}")
        return False
    except Exception as e:
        print(f"❌ Неожиданная ошибка: {e}")
        return False


def main():
    """Главная функция - выполняет все проверки"""
    print("=" * 60)
    print("Проверка готовности Telegram бота к запуску")
    print("=" * 60)
    print()
    
    checks = [
        ("Файл конфигурации", check_env_file),
        ("Зависимость python-dotenv", check_dotenv_installed),
        ("Импорт config.py", check_config_import),
        ("Валидация BOT_TOKEN", check_token_validation),
        ("Инициализация bot.py", check_bot_initialization),
        ("База данных", check_database),
    ]
    
    results = []
    for name, check_func in checks:
        print(f"Проверка: {name}")
        try:
            result = check_func()
            results.append(result)
        except Exception as e:
            print(f"❌ Ошибка при проверке {name}: {e}")
            results.append(False)
        print()
    
            
    print("=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"Результат: {passed}/{total} проверок пройдено")
    
    if all(results):
        print()
        print("✅ ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ!")
        print()
        print("Бот готов к запуску. Используйте команду:")
        print("  python bot.py")
        print()
        return 0
    else:
        print()
        print("❌ НЕКОТОРЫЕ ПРОВЕРКИ НЕ ПРОЙДЕНЫ")
        print()
        print("Пожалуйста исправьте проблемы выше перед запуском бота")
        print()
        return 1


if __name__ == "__main__":
    sys.exit(main())
