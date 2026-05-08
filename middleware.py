import os
from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
import time
from collections import defaultdict
import logging
from logging_utils import action_event, actor_label, short_value

logger = logging.getLogger('antispam')


def _env_flag(name: str, default: bool = True) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() not in {"0", "false", "no", "off"}


def _event_label(event: Message | CallbackQuery) -> str:
    return "callback" if isinstance(event, CallbackQuery) else "message"


def _event_details(event: Message | CallbackQuery) -> Dict[str, Any]:
    if isinstance(event, CallbackQuery):
        return {
            "data": short_value(getattr(event, "data", None), 100),
            "message_id": getattr(getattr(event, "message", None), "message_id", None),
        }

    text = getattr(event, "text", None) or getattr(event, "caption", None)
    details: Dict[str, Any] = {
        "chat": getattr(getattr(event, "chat", None), "id", None),
        "text": short_value(text, 100),
    }
    if text and text.startswith("/"):
        details["command"] = text.split(maxsplit=1)[0]
    return details


class ActivityLogMiddleware(BaseMiddleware):
    """Log user-facing activity and handler outcomes to the action log."""

    def __init__(self, *, enabled: bool | None = None, log_success: bool | None = None):
        self.enabled = _env_flag("BOT_ACTIVITY_LOG", True) if enabled is None else enabled
        self.log_success = _env_flag("BOT_ACTIVITY_LOG_SUCCESS", True) if log_success is None else log_success

    async def __call__(
        self,
        handler: Callable[[Message | CallbackQuery, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any],
    ) -> Any:
        if not self.enabled:
            return await handler(event, data)

        user = getattr(event, "from_user", None)
        event_type = _event_label(event)
        details = _event_details(event)
        start = time.perf_counter()

        action_event("IN", f"{event_type} received", user=actor_label(user), **details)
        try:
            result = await handler(event, data)
        except Exception as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            action_event(
                "ERROR",
                f"{event_type} failed",
                user=actor_label(user),
                duration_ms=duration_ms,
                error=type(exc).__name__,
                detail=short_value(exc, 140),
                **details,
            )
            raise

        if self.log_success:
            duration_ms = int((time.perf_counter() - start) * 1000)
            action_event(
                "OK",
                f"{event_type} handled",
                user=actor_label(user),
                duration_ms=duration_ms,
                **details,
            )
        return result

class UserRateLimit:
    def __init__(self, limit: int, interval: float):
        self.limit = limit
        self.interval = interval
        self.requests: Dict[int, list] = defaultdict(list)
        
    def _cleanup_old_requests(self, user_id: int):
        """Очищает старые запросы"""
        current = time.time()
        while self.requests[user_id] and current - self.requests[user_id][0] > self.interval:
            self.requests[user_id].pop(0)
            
    def can_proceed(self, user_id: int) -> bool:
        """Проверяет, не превышен ли лимит для пользователя"""
        self._cleanup_old_requests(user_id)
        return len(self.requests[user_id]) < self.limit
    
    def add_request(self, user_id: int):
        """Регистрирует новый запрос"""
        self._cleanup_old_requests(user_id)
        self.requests[user_id].append(time.time())

class AntiSpamMiddleware(BaseMiddleware):
    def __init__(
        self,
        message_limit: int = 20,                         
        message_interval: float = 60,               
        callback_limit: int = 30,                              
        callback_interval: float = 60                
    ):
        self.message_limiter = UserRateLimit(message_limit, message_interval)
        self.callback_limiter = UserRateLimit(callback_limit, callback_interval)
        
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any]
    ) -> Any:
        user_id = event.from_user.id if event.from_user else None
        if not user_id:
            return await handler(event, data)

        try:
            from database import save_user_profile

            save_user_profile(event.from_user)
        except Exception as exc:
            logger.debug("Could not persist Telegram user profile for %s: %s", user_id, exc)
            
        if isinstance(event, CallbackQuery):
            limiter = self.callback_limiter
            action = "callback"
        else:
            limiter = self.message_limiter
            action = "message"
            
        if not limiter.can_proceed(user_id):
            logger.warning(f"Rate limit exceeded for user {user_id} ({action})")
            action_event("WARN", "rate limit exceeded", user=actor_label(event.from_user), event=action)
                                                   
            if isinstance(event, CallbackQuery):
                                                       
                try:
                    from localization import t
                    msg = t(user_id, "rate_limit_exceeded")
                except Exception as e:
                    logger.exception("Failed to get localized rate limit message for user %s: %s", user_id, e)
                    msg = "Пожалуйста, подождите немного перед следующим действием"
                await event.answer(msg, show_alert=True)
                                            
            else:
                try:
                    from localization import t
                    msg = t(user_id, "rate_limit_exceeded")
                except Exception as e:
                    logger.exception("Failed to get localized rate limit message for user %s: %s", user_id, e)
                    msg = "Слишком много сообщений. Пожалуйста, подождите немного."
                await event.answer(msg)
            return None
            
        limiter.add_request(user_id)
        return await handler(event, data)
