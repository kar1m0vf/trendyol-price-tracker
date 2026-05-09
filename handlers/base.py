"""
Base handler with common utilities and shared functionality.
"""
import logging
import sys
from typing import Optional, Dict, Any
from aiogram import Bot
from localization import t as translate_func, get_user_language_safe

logger = logging.getLogger(__name__)

                                             
_bot = None

def get_bot() -> Bot:
    """Get bot instance lazily."""
    global _bot
    if _bot is not None:
        return _bot

    for module_name in ("__main__", "bot"):
        module = sys.modules.get(module_name)
        runtime_bot = getattr(module, "bot", None) if module else None
        if runtime_bot is not None:
            _bot = runtime_bot
            return _bot

    try:
        from bot import _get_runtime_bot

        _bot = _get_runtime_bot()
        return _bot
    except Exception as exc:
        raise RuntimeError("Bot runtime is not initialized. Call create_app() first.") from exc
    return _bot

                                       
try:
    from localization import LOCALES
except ImportError:
                                      
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

    def bind_runtime_bot(self, candidate) -> None:
        """Bind bot from an incoming aiogram event when available."""
        if self._bot is not None:
            return
        if candidate is None:
            return
        if hasattr(candidate, "send_message"):
            self._bot = candidate

    def t(self, user_id: int, key: str, **kwargs) -> str:
        """Translate text for user with optional formatting."""
        return translate_func(user_id, key, **kwargs)

    async def answer_safe(self, message_or_query, text: str, **kwargs) -> bool:
        """Safely answer to message or callback query.

        Returns:
            True if sent successfully, False otherwise
        """
        try:
            if hasattr(message_or_query, 'answer'):                 
                await message_or_query.answer(text, **kwargs)
            else:           
                await message_or_query.answer(text, **kwargs)
            return True
        except Exception as e:
                                   
            print(f"Failed to send answer: {e}")
            return False

    async def send_status_message(self, target, text: str, **kwargs):
        """Send a temporary user-facing status message.

        The returned message can later be edited or deleted so long-running
        actions feel responsive without leaving extra noise in chat.
        """
        try:
            if hasattr(target, "answer"):
                return await target.answer(text, **kwargs)
            return await self.bot.send_message(target, text, **kwargs)
        except Exception:
            logger.debug("Failed to send status message", exc_info=True)
            return None

    async def replace_status_message(self, status_message, text: str, *, fallback_target=None, **kwargs) -> bool:
        """Replace a status message with the final user-facing result."""
        if status_message is not None:
            try:
                await status_message.edit_text(text, **kwargs)
                return True
            except Exception:
                logger.debug("Failed to edit status message", exc_info=True)

        if fallback_target is not None:
            sent = await self.send_status_message(fallback_target, text, **kwargs)
            return sent is not None
        return False

    async def clear_status_message(self, status_message) -> bool:
        """Remove a temporary status message after a separate result was sent."""
        if status_message is None:
            return False
        try:
            await status_message.delete()
            return True
        except Exception:
            logger.debug("Failed to delete status message", exc_info=True)
            return False

    def get_user_language(self, user_id: int) -> str:
        """Get user's language preference."""
        try:
            return get_user_language_safe(user_id)
        except Exception:
            return "ru"
