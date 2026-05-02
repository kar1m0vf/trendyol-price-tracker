from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
import time
from collections import defaultdict
import logging

logger = logging.getLogger('antispam')

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
