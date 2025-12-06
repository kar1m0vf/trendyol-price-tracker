import logging
import os
from logging.handlers import RotatingFileHandler
import functools
import time
import asyncio
from typing import Any, Callable, TypeVar

# Настройка логирования
def setup_logger(name: str, log_file: str, level=logging.INFO) -> logging.Logger:
    """Настраивает и возвращает logger с ротацией файлов"""
    formatter = logging.Formatter(
        fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    if not os.path.exists('logs'):
        os.makedirs('logs')

    handler = RotatingFileHandler(
        f'logs/{log_file}',
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5
    )
    handler.setFormatter(formatter)

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.addHandler(handler)
    
    return logger

# Декоратор для повторных попыток
def retry(
    exceptions: tuple = (Exception,),
    tries: int = 3,
    delay: float = 1,
    backoff: float = 2,
    logger: logging.Logger = None
):
    """
    Декоратор для повторных попыток выполнения функции
    :param exceptions: кортеж исключений, которые обрабатываем
    :param tries: количество попыток
    :param delay: начальная задержка между попытками
    :param backoff: множитель для увеличения задержки
    :param logger: logger для записи ошибок
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            _tries, _delay = tries, delay
            while _tries > 0:
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    _tries -= 1
                    if _tries == 0:
                        if logger:
                            logger.error(
                                f"Function {func.__name__} failed after {tries} tries. Error: {str(e)}"
                            )
                        raise
                    if logger:
                        logger.warning(
                            f"Function {func.__name__} failed. {_tries} tries remaining. Error: {str(e)}"
                        )
                    time.sleep(_delay)
                    _delay *= backoff
            return None
        return wrapper

    return decorator

# Асинхронная версия декоратора retry
def async_retry(
    exceptions: tuple = (Exception,),
    tries: int = 3,
    delay: float = 1,
    backoff: float = 2,
    logger: logging.Logger = None
):
    """
    Асинхронный декоратор для повторных попыток выполнения функции
    Параметры аналогичны sync версии
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            _tries, _delay = tries, delay
            while _tries > 0:
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    _tries -= 1
                    if _tries == 0:
                        if logger:
                            logger.error(
                                f"Function {func.__name__} failed after {tries} tries. Error: {str(e)}"
                            )
                        raise
                    if logger:
                        logger.warning(
                            f"Function {func.__name__} failed. {_tries} tries remaining. Error: {str(e)}"
                        )
                    await asyncio.sleep(_delay)
                    _delay *= backoff
            return None
        return wrapper

    return decorator

# Rate limiting
class RateLimiter:
    """
    Простой rate limiter на основе sliding window
    """
    def __init__(self, max_requests: int, time_window: float):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = []

    def _cleanup_old_requests(self):
        """Удаляет запросы старше time_window"""
        current = time.time()
        while self.requests and current - self.requests[0] > self.time_window:
            self.requests.pop(0)

    def can_proceed(self) -> bool:
        """Проверяет, можно ли сделать новый запрос"""
        self._cleanup_old_requests()
        return len(self.requests) < self.max_requests

    def add_request(self):
        """Регистрирует новый запрос"""
        self._cleanup_old_requests()
        self.requests.append(time.time())

# Асинхронная версия rate limiter
class AsyncRateLimiter:
    """
    Асинхронная версия rate limiter
    """
    def __init__(self, max_requests: int, time_window: float):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = []
        self._lock = asyncio.Lock()

    async def _cleanup_old_requests(self):
        """Удаляет запросы старше time_window"""
        current = time.time()
        while self.requests and current - self.requests[0] > self.time_window:
            self.requests.pop(0)

    async def can_proceed(self) -> bool:
        """Проверяет, можно ли сделать новый запрос"""
        async with self._lock:
            await self._cleanup_old_requests()
            return len(self.requests) < self.max_requests

    async def add_request(self):
        """Регистрирует новый запрос"""
        async with self._lock:
            await self._cleanup_old_requests()
            self.requests.append(time.time())