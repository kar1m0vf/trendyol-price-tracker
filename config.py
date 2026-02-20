import os
from typing import Optional
from pathlib import Path

# Загружаем переменные из .env если dotenv доступен
try:
    from dotenv import load_dotenv
    import sys

    # Явно указываем путь к .env файлу
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        result = load_dotenv(dotenv_path=env_path, override=True)
        if result:
            print(f"✅ Переменные окружения загружены из {env_path}", file=sys.stderr)
        else:
            print(f"⚠️  Не удалось загрузить переменные из {env_path}", file=sys.stderr)
    else:
        # Пытаемся найти .env в родительской директории
        result = load_dotenv(override=True)
        if result:
            print("✅ Переменные окружения загружены из родительской директории", file=sys.stderr)
        else:
            print("ℹ️  Файл .env не найден, используем системные переменные окружения", file=sys.stderr)
except ImportError:
    print("ℹ️  python-dotenv не установлен, используем системные переменные окружения", file=sys.stderr)

# Безопасное получение токена из переменных окружения или .env
BOT_TOKEN: Optional[str] = os.getenv("BOT_TOKEN")

# ВАЖНО: Не вызываем здесь ValueError при импорте!
# Ошибка будет выброшена только когда токен действительно понадобится
def _check_bot_token():
    """Проверяет что BOT_TOKEN установлен. Вызывается перед использованием."""
    if not BOT_TOKEN:
        raise ValueError(
            "❌ BOT_TOKEN не установлен!\n"
            "\n"
            "Установите переменную окружения одним из способов:\n"
            "  1. Windows (PowerShell): $env:BOT_TOKEN='your_token_here'\n"
            "  2. Windows (Command Prompt): set BOT_TOKEN=your_token_here\n"
            "  3. Linux/Mac: export BOT_TOKEN=your_token_here\n"
            "  4. Создайте файл .env в корне проекта:\n"
            "     BOT_TOKEN=your_token_here\n"
            "\n"
            "Получите токен у @BotFather в Telegram"
        )
    return True

# Дополнительные настройки
DEFAULT_NOTIFY_MODE = os.getenv("DEFAULT_NOTIFY_MODE", "hourly")

# ADMIN_IDS only from environment/.env
admin_ids_str = os.getenv("ADMIN_IDS", "")
if admin_ids_str.strip():
    ADMIN_IDS = [int(x) for x in admin_ids_str.split(",") if x.strip()]
    print(f"✅ ADMIN_IDS loaded from environment: {ADMIN_IDS}")
else:
    ADMIN_IDS = []
    print("WARNING: ADMIN_IDS not set; admin features are disabled.")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
DATABASE_PATH = os.getenv("DATABASE_PATH", "trendyol_bot.db")

# Feature flags for gradual migration
USE_NEW_HANDLERS = os.getenv("USE_NEW_HANDLERS", "false").lower() == "true"
