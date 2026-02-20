import logging
import os
from logging.handlers import RotatingFileHandler
import functools
import time
import asyncio
from typing import Any, Callable, TypeVar, Optional
from datetime import datetime

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


def parse_date_flexible(date_str: str) -> Optional[datetime]:
    """
    Гибкий парсер дат в различных форматах.
    Пытается распарсить дату в нескольких популярных форматах.

    Args:
        date_str: Строка с датой

    Returns:
        datetime объект или None если парсинг не удался
    """
    if not date_str:
        return None

    date_str = date_str.strip()

    # Список форматов для попытки парсинга (в порядке вероятности)
    formats = [
        "%d.%m.%Y %H:%M:%S",      # 20.09.2025 14:30:00
        "%d.%m.%Y %H:%M",         # 20.09.2025 14:30
        "%d.%m.%Y",                # 20.09.2025
        "%Y-%m-%d %H:%M:%S",       # 2025-09-20 14:30:00
        "%Y-%m-%d %H:%M",          # 2025-09-20 14:30
        "%Y-%m-%d",                # 2025-09-20
        "%d/%m/%Y",                # 20/09/2025
        "%m/%d/%Y",                # 09/20/2025
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue

    logging.getLogger(__name__).debug(f"Could not parse date: {date_str}")
    return None


def get_next_notification_time(mode: str, last_notify_time: Optional[int], notify_interval: Optional[int], user_id: int, translate_func=None) -> str:
    """
    Рассчитывает время следующего уведомления для подписки.
    Возвращает строку с описанием времени или типа уведомлений.

    Args:
        mode: Режим уведомлений ("hourly" или "discount")
        last_notify_time: Время последнего уведомления (timestamp)
        notify_interval: Интервал уведомлений в минутах
        user_id: ID пользователя для локализации
        translate_func: Функция перевода (если None, возвращает ключи)

    Returns:
        Строка с временем следующего уведомления
    """
    try:
        if mode == "discount":
            # Для режима "только при скидке" показываем, что уведомления приходят при изменениях
            return translate_func(user_id, "next_notify_discount") if translate_func else "next_notify_discount"
        elif mode == "hourly":
            # Для почасового режима рассчитываем точное время следующего уведомления
            if last_notify_time and notify_interval:
                # notify_interval в минутах, переводим в секунды
                interval_seconds = notify_interval * 60
                next_time = last_notify_time + interval_seconds
                current_time = int(time.time())

                if next_time > current_time:
                    # Показываем время в формате HH:MM
                    dt = datetime.fromtimestamp(next_time)
                    return dt.strftime("%H:%M")
                else:
                    # Если время уже прошло, показываем ближайшее следующее время
                    # Округляем до следующего часа
                    current_hour = datetime.now().hour
                    next_hour = (current_hour + 1) % 24
                    return f"{next_hour:02d}:00"
            else:
                # Если нет данных, показываем следующий час
                next_hour = (datetime.now().hour + 1) % 24
                return f"{next_hour:02d}:00"
        else:
            return translate_func(user_id, "next_notify_unknown") if translate_func else "next_notify_unknown"

    except Exception as e:
        logging.getLogger(__name__).debug(f"Error calculating next notification time: {e}")
        return translate_func(user_id, "next_notify_unknown") if translate_func else "next_notify_unknown"