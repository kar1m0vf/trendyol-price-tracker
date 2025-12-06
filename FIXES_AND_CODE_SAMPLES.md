# 🔧 ИСПРАВЛЕНИЯ & КОД-ПРИМЕРЫ

Этот файл содержит конкретные решения для критических и серьёзных проблем.

---

## 1️⃣ FIX: Security - Hardcoded BOT_TOKEN

### Шаг 1: Создать .env.example

```bash
# .env.example
BOT_TOKEN=your_token_here
DEFAULT_NOTIFY_MODE=hourly
ADMIN_IDS=123456789,987654321
LOG_LEVEL=INFO
DATABASE_PATH=trendyol_bot.db
WEBHOOK_URL=
WEBHOOK_PORT=8443
```

### Шаг 2: Обновить config.py

```python
# config.py
import os
from typing import Optional
from dotenv import load_dotenv  # pip install python-dotenv

# Загрузить переменные из .env
load_dotenv()

# Безопасное получение токена ТОЛЬКО из переменных окружения
BOT_TOKEN: Optional[str] = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError(
        "❌ BOT_TOKEN не установлен!\n"
        "   Windows: set BOT_TOKEN=your_token_here\n"
        "   Linux:   export BOT_TOKEN=your_token_here\n"
        "   Or create .env file (see .env.example)"
    )

# Дополнительные настройки
DEFAULT_NOTIFY_MODE = os.getenv("DEFAULT_NOTIFY_MODE", "hourly")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
DATABASE_PATH = os.getenv("DATABASE_PATH", "trendyol_bot.db")

print("✅ BOT_TOKEN loaded from environment")
```

### Шаг 3: Обновить requirements.txt

```
aiogram==3.4.1
requests==2.31.0
beautifulsoup4==4.12.2
apscheduler==3.10.4
matplotlib==3.8.0 
cloudscraper==1.2.71
python-dotenv==1.0.0  # ← Добавить
```

### Шаг 4: Очистить git историю (ВАЖНО!)

```bash
# Это удалит token из git истории
git filter-branch --force --index-filter \
  'git rm --cached --ignore-unmatch config.py' \
  --prune-empty --tag-name-filter cat -- --all

# Перезаписать все ветки
git push origin --force --all

# Удалить рефтаги
git push origin --force --tags

# Локально очистить
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

### Шаг 5: Обновить .gitignore

```bash
# .gitignore
.env
.env.local
config.py  # Если там есть secrets
*.db
*.log
logs/
venv/
__pycache__/
.pytest_cache/
*.pyc
.vscode/
.idea/
*.sqlite
*.sqlite3
trendyol_bot.db
savedlastcode.txt
```

---

## 2️⃣ FIX: Missing get_user_settings() implementation

Добавить эту функцию в `database.py`:

```python
# В database.py добавить:
from typing import Tuple

def get_user_settings(user_id: int) -> Tuple[str, int, int]:
    """
    Получает настройки пользователя с безопасными значениями по умолчанию.
    
    Returns:
        (language, notify_quiet_hours_start, notify_quiet_hours_end)
    
    Example:
        >>> lang, start, end = get_user_settings(12345)
        >>> # ('ru', 23, 7)
    """
    try:
        with sqlite3.connect(DB) as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT language, notify_quiet_hours_start, notify_quiet_hours_end
                FROM users WHERE user_id = ?
            """, (user_id,))
            row = cur.fetchone()
        
        if row:
            return row
        else:
            # Возвращаем безопасные значения по умолчанию
            return ("ru", 23, 7)
    except Exception as e:
        logger.exception(f"Error getting user settings for {user_id}: {e}")
        return ("ru", 23, 7)  # Fallback


def update_user_settings(user_id: int, **kwargs) -> None:
    """
    Обновляет настройки пользователя.
    
    Args:
        user_id: ID пользователя
        **kwargs: Поля для обновления (язык, quiet_hours_start, quiet_hours_end и т.д.)
    
    Example:
        >>> update_user_settings(12345, language='en', notify_quiet_hours_start=22)
    """
    allowed_fields = {
        'language',
        'notify_quiet_hours_start',
        'notify_quiet_hours_end'
    }
    
    update_dict = {k: v for k, v in kwargs.items() if k in allowed_fields}
    
    if not update_dict:
        logger.warning(f"No valid fields to update for user {user_id}")
        return
    
    try:
        with sqlite3.connect(DB) as conn:
            cur = conn.cursor()
            
            # Убедимся, что пользователь существует
            cur.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
            
            # Обновляем поля
            set_clause = ", ".join(f"{k} = ?" for k in update_dict.keys())
            values = list(update_dict.values()) + [user_id]
            
            cur.execute(f"UPDATE users SET {set_clause} WHERE user_id = ?", values)
            conn.commit()
            
            logger.info(f"Updated user {user_id} settings: {update_dict}")
    except Exception as e:
        logger.exception(f"Error updating user settings for {user_id}: {e}")
```

---

## 3️⃣ FIX: save_price_point() с дедупликацией

Добавить в `database.py`:

```python
def save_price_point(subscription_id: int, price: float, ts: int = None, max_points: int = 10000) -> Optional[int]:
    """
    Сохраняет точку цены для подписки с дедупликацией и лимитом.
    
    Args:
        subscription_id: ID подписки
        price: Цена товара
        ts: Timestamp (по умолчанию текущее время)
        max_points: Максимум точек в истории (старые удаляются)
    
    Returns:
        ID вставленной строки или None при ошибке
    """
    if ts is None:
        ts = int(time.time())
    
    try:
        with sqlite3.connect(DB) as conn:
            cur = conn.cursor()
            
            # Проверяем дубликат в последний час
            one_hour_ago = ts - 3600
            cur.execute("""
                SELECT id FROM price_history 
                WHERE subscription_id = ? 
                AND ts > ? 
                AND price = ?
                LIMIT 1
            """, (subscription_id, one_hour_ago, price))
            
            if cur.fetchone() is not None:
                logger.debug(f"Duplicate price point detected for sub {subscription_id}")
                return None
            
            # Вставляем новую точку
            cur.execute("""
                INSERT INTO price_history 
                (subscription_id, url, price, ts, source) 
                SELECT ?, url, ?, ?, 'collector'
                FROM subscriptions WHERE id = ?
            """, (subscription_id, price, ts, subscription_id))
            
            new_id = cur.lastrowid
            
            # Удаляем старые точки если превышен лимит
            cur.execute("""
                SELECT COUNT(*) FROM price_history 
                WHERE subscription_id = ?
            """, (subscription_id,))
            
            count = cur.fetchone()[0]
            if count > max_points:
                excess = count - max_points
                cur.execute("""
                    DELETE FROM price_history 
                    WHERE id IN (
                        SELECT id FROM price_history 
                        WHERE subscription_id = ?
                        ORDER BY ts ASC
                        LIMIT ?
                    )
                """, (subscription_id, excess))
                logger.info(f"Deleted {excess} old price points for sub {subscription_id}")
            
            conn.commit()
            return new_id
            
    except sqlite3.IntegrityError as e:
        logger.error(f"Integrity error saving price point: {e}")
        return None
    except Exception as e:
        logger.exception(f"Error saving price point for sub {subscription_id}: {e}")
        return None
```

---

## 4️⃣ FIX: Timeout для bot.send_photo() в scheduler

Обновить `bot.py` функцию `check_all()`:

```python
async def send_notification_safe(
    user_id: int, 
    text: str, 
    image: Optional[str] = None, 
    timeout: float = 10.0
) -> bool:
    """
    Безопасно отправляет уведомление с timeout.
    
    Args:
        user_id: ID получателя
        text: Основной текст
        image: URL изображения (опционально)
        timeout: Таймаут в секундах
    
    Returns:
        True если успешно, False если ошибка
    """
    try:
        if image:
            try:
                await asyncio.wait_for(
                    bot.send_photo(user_id, photo=image, caption=text),
                    timeout=timeout
                )
                logger.debug(f"Photo notification sent to {user_id}")
                return True
            except asyncio.TimeoutError:
                logger.warning(f"Photo send timeout for user {user_id}, falling back to text")
                # Fallback на текст
                await asyncio.wait_for(
                    bot.send_message(user_id, text),
                    timeout=timeout
                )
                return True
        else:
            await asyncio.wait_for(
                bot.send_message(user_id, text),
                timeout=timeout
            )
            logger.debug(f"Text notification sent to {user_id}")
            return True
            
    except asyncio.TimeoutError:
        logger.error(f"Notification timeout for user {user_id}")
        return False
    except aiogram.exceptions.TelegramForbiddenError:
        logger.warning(f"User {user_id} blocked the bot")
        return False
    except aiogram.exceptions.TelegramBadRequest as e:
        logger.warning(f"Bad request for user {user_id}: {e}")
        return False
    except Exception as e:
        logger.exception(f"Unexpected error sending notification to {user_id}: {e}")
        return False


# Использовать в check_all():
async def process(sub):
    # ... existing code ...
    
    if notification_needed and notification_text:
        success = await send_notification_safe(
            user_id,
            notification_text,
            image=image if image else None,
            timeout=10.0
        )
        
        if success:
            alerted_count += 1
            update_notify_time(sub_id)
        elif "blocked the bot" in str(e):  # Если заблокирован - удалить
            remove_subscriptions_by_user(user_id)
```

---

## 5️⃣ FIX: URL валидация

Обновить `bot.py`:

```python
import re

# Более строгий паттерн для URL
TRENDYOL_PRODUCT_URL_PATTERN = re.compile(
    r"^https?://(?:www\.)?trendyol\.com/.+?-p-\d+(?:[/?#].*)?$",
    re.IGNORECASE
)

def is_trendyol_product_url(url: str) -> bool:
    """
    Проверяет, является ли URL ссылкой на товар в Trendyol.
    
    Args:
        url: URL для проверки
    
    Returns:
        True если это валидный URL товара Trendyol, False иначе
    
    Examples:
        >>> is_trendyol_product_url("https://www.trendyol.com/roborock/q8-p-944315539")
        True
        >>> is_trendyol_product_url("https://www.trendyol.com/")
        False
    """
    if not url:
        return False
    
    url = url.strip()
    
    # Проверяем базовый формат
    if not TRENDYOL_PRODUCT_URL_PATTERN.match(url):
        return False
    
    # Дополнительная проверка: должна быть ссылка на конкретный товар
    if "/p-" not in url.lower():
        return False
    
    return True


def normalize_url(url: str) -> str:
    """
    Нормализует URL для сравнения и хранения.
    
    Args:
        url: Исходный URL
    
    Returns:
        Нормализованный URL без параметров сессии
    
    Examples:
        >>> normalize_url("https://www.trendyol.com/item-p-123?from=search")
        'https://www.trendyol.com/item-p-123'
    """
    if not url:
        return ""
    
    u = url.strip()
    
    # Добавляем https если отсутствует
    if not u.startswith(('http://', 'https://')):
        u = 'https://' + u
    
    # Удаляем якоры и параметры
    u = re.sub(r'[?#&].*$', '', u)
    
    # Удаляем trailing slash
    u = u.rstrip('/')
    
    return u.lower()
```

---

## 6️⃣ FIX: Кэширование в scheduler

Обновить `check_all()` в `bot.py`:

```python
async def check_all():
    logger.info("Scheduler job: checking subscriptions")
    subs = get_all_subscriptions()
    total = len(subs)
    logger.info("Found %d subscriptions to check", total)
    
    # ← ДОБАВИТЬ: Кэш для пользовательских настроек
    user_settings_cache = {}
    
    def get_cached_user_settings(user_id: int):
        """Возвращает настройки пользователя из кэша или БД."""
        if user_id not in user_settings_cache:
            user_settings_cache[user_id] = get_user_settings(user_id)
        return user_settings_cache[user_id]
    
    sem = asyncio.Semaphore(10)
    processed_count = 0
    alerted_count = 0

    async def process(sub):
        nonlocal processed_count, alerted_count
        (sub_id, user_id, url, mode, last_price, product_title, product_image,
         min_price, max_price, notify_percent, notify_interval, last_notify_time) = sub
            
        async with sem:
            try:
                # ← ИСПОЛЬЗОВАТЬ КЭШТОТ.
                lang, quiet_start, quiet_end = get_cached_user_settings(user_id)
                
                # ... rest of the function remains the same ...
```

---

## 7️⃣ FIX: Улучшенный парсинг дат

Обновить `bot.py`:

```python
from datetime import datetime
from typing import Optional

def parse_date_flexible(date_str: str) -> Optional[datetime]:
    """
    Гибкий парсер дат в различных форматах.
    
    Args:
        date_str: Строка с датой
    
    Returns:
        datetime объект или None если парсинг не удался
    
    Examples:
        >>> parse_date_flexible("20.09.2025")
        datetime.datetime(2025, 9, 20, 0, 0)
        >>> parse_date_flexible("2025-09-20 14:30:00")
        datetime.datetime(2025, 9, 20, 14, 30)
    """
    if not date_str:
        return None
    
    date_str = date_str.strip()
    
    # Список форматов для попытки парсинга (в порядке частоты)
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
    
    logger.debug(f"Could not parse date: {date_str}")
    return None


# Обновить send_history_plot():
async def send_history_plot(user_id: int, url: str, hist):
    """Отправляет график истории цен с улучшенным парсингом дат."""
    processed = []
    
    for d, p in hist:
        parsed_dt = None
        
        if isinstance(d, str):
            parsed_dt = parse_date_flexible(d)
        elif isinstance(d, datetime):
            parsed_dt = d
        
        if parsed_dt:
            processed.append((parsed_dt, float(p)))
        else:
            # Если не удалось распарсить дату, используем как есть
            logger.warning(f"Could not parse date: {d}")
            processed.append((d, float(p)))

    # ... rest remains the same ...
```

---

## 8️⃣ FIX: Улучшенная локализация

Обновить функцию `t()` в `bot.py`:

```python
def t(user_id: int, key: str, **format_kwargs) -> str:
    """
    Получает локализованную строку для пользователя.
    
    Args:
        user_id: ID пользователя (для определения языка)
        key: Ключ строки в локали
        **format_kwargs: Аргументы для форматирования строки
    
    Returns:
        Локализованная строка (или ключ если не найдена)
    
    Examples:
        >>> t(12345, "subscribed_now", price=99.99)
        'Вы подписались! Текущая цена: 99.99 TL'
    """
    try:
        lang = get_user_language(user_id) or "ru"
    except Exception:
        lang = "ru"
    
    # Получаем локали в порядке приоритета
    loc = LOCALES.get(lang, {})
    ru_loc = LOCALES.get("ru", {})
    
    # Ищем строку в порядке: user_lang → ru → fallback
    text = loc.get(key) or ru_loc.get(key) or f"[MISSING: {key}]"
    
    # Форматируем строку если переданы аргументы
    try:
        if format_kwargs:
            text = text.format(**format_kwargs)
    except KeyError as e:
        logger.warning(f"Missing format key in translation: {e}")
    except Exception as e:
        logger.exception(f"Error formatting translation key {key}: {e}")
    
    return text
```

---

## 📝 Чек-лист для применения всех исправлений

```bash
# 1. Создать файлы конфига
[ ] Создать .env.example
[ ] Создать .env с реальным токеном
[ ] Обновить .gitignore

# 2. Обновить код
[ ] Обновить config.py (удалить hardcoded token)
[ ] Добавить get_user_settings() в database.py
[ ] Добавить save_price_point() в database.py
[ ] Добавить send_notification_safe() в bot.py
[ ] Обновить is_trendyol_product_url()
[ ] Обновить normalize_url()
[ ] Обновить parse_date_flexible()
[ ] Обновить функцию t()
[ ] Добавить кэширование в check_all()

# 3. Зависимости
[ ] pip install python-dotenv

# 4. Тестирование
[ ] Запустить бота локально
[ ] Проверить подписку на товар
[ ] Проверить уведомления
[ ] Проверить историю цен
[ ] Проверить локализацию

# 5. Git очистка
[ ] Очистить историю от токена
[ ] Запушить изменения
```

---

**Готово к применению!** ✅
