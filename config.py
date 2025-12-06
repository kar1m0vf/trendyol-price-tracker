import os
from typing import Optional
from pathlib import Path

# Загружаем переменные из .env если dotenv доступен
try:
    from dotenv import load_dotenv
    # Явно указываем путь к .env файлу
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=True)
    else:
        # Пытаемся найти .env в родительской директории если нет в текущей
        load_dotenv(override=True)
except ImportError:
    pass  # dotenv не установлен, используем переменные окружения

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
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
DATABASE_PATH = os.getenv("DATABASE_PATH", "trendyol_bot.db")