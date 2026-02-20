"""
Base handler with common utilities and shared functionality.
"""
from typing import Optional, Dict, Any
from aiogram import Bot
from localization import t as translate_func, get_user_language_safe

# Import bot lazily to avoid circular imports
_bot = None

def get_bot() -> Bot:
    """Get bot instance lazily."""
    global _bot
    if _bot is None:
        try:
            from config import bot as config_bot
            _bot = config_bot
        except ImportError:
            # Fallback - try to import from bot module
            from bot import bot as bot_bot
            _bot = bot_bot
    return _bot

# Импорт локалей из localization модуля
try:
    from localization import LOCALES
except ImportError:
    # Fallback если импорт не работает
    LOCALES = {}

class BaseHandler:
    """Base class for all handlers with common functionality."""

    def __init__(self):
        self._bot = None

    @property
    def bot(self) -> Bot:
        """Get bot instance."""
        if self._bot is None:
            self._bot = get_bot()
        return self._bot

    def t(self, user_id: int, key: str, **kwargs) -> str:
        """Translate text for user with optional formatting."""
        return translate_func(user_id, key, **kwargs)

    async def answer_safe(self, message_or_query, text: str, **kwargs) -> bool:
        """Safely answer to message or callback query.

        Returns:
            True if sent successfully, False otherwise
        """
        try:
            if hasattr(message_or_query, 'answer'):  # CallbackQuery
                await message_or_query.answer(text, **kwargs)
            else:  # Message
                await message_or_query.answer(text, **kwargs)
            return True
        except Exception as e:
            # Логируем но не крашим
            print(f"Failed to send answer: {e}")
            return False

    def get_user_language(self, user_id: int) -> str:
        """Get user's language preference."""
        try:
            return get_user_language_safe(user_id)
        except Exception:
            return "ru"
