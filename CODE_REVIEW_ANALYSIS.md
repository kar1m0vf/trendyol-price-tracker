# 📋 Профессиональный Code Review - Telegram Bot для Trendyol

**Дата:** 5 декабря 2025  
**Анализ:** Полный аудит проекта по стандартам production-качества

---

## 🎯 Общее впечатление

**Уровень:** Хороший любительский проект с элементами профессионального подхода  
**Статус:** Работоспособен, но требует критических исправлений перед production использованием

---

## 🔴 КРИТИЧЕСКИЕ ПРОБЛЕМЫ (Must Fix)

### 1. **Security: Hardcoded BOT_TOKEN в config.py**
**Файл:** `config.py` (строка 13)

```python
BOT_TOKEN = "<BOT_TOKEN_REDACTED>"
```

**Опасность:** 
- Токен виден в системе контроля версий (GitHub)
- Любой может использовать токен для компрометации бота
- Это нарушает все стандарты безопасности

**Решение:**
```python
# ❌ НИКОГДА не коммитьте в репозиторий
# ✅ Используйте только переменные окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не установлен. Set BOT_TOKEN env variable.")
```

**Действие:** Немедленно:
1. Удалить токен из git истории: `git filter-branch --force --index-filter 'git rm --cached --ignore-unmatch config.py'`
2. Сбросить токен в BotFather (@BotFather)
3. Добавить `config.py` в `.gitignore` (если там есть secrets)
4. Создать `.env.example` файл с примером

---

### 2. **Database Race Condition в save_price_point()**
**Файл:** `database.py` - функция не показана в коде, но используется

**Проблема:** Недостаточная информация о реализации `save_price_point()`. Нужно проверить:
- Есть ли дедупликация правильно реализована?
- Нет ли race condition при одновременных записях?

**Рекомендация:**
```python
def save_price_point(subscription_id: int, price: float, ts: int):
    """Сохраняет точку цены с предотвращением дубликатов."""
    with sqlite3.connect(DB) as conn:
        cur = conn.cursor()
        
        # Проверяем дубликат в последний час
        one_hour_ago = ts - 3600
        cur.execute("""
            SELECT COUNT(*) FROM price_history 
            WHERE subscription_id = ? AND ts > ? AND price = ?
        """, (subscription_id, one_hour_ago, price))
        
        if cur.fetchone()[0] == 0:  # Нет дубликата
            cur.execute("""
                INSERT INTO price_history 
                (subscription_id, url, price, ts, source) 
                SELECT ?, url, ?, ?, 'collector'
                FROM subscriptions WHERE id = ?
                LIMIT 1
            """, (subscription_id, price, ts, subscription_id))
            conn.commit()
            return cur.lastrowid
```

---

### 3. **Неправильная обработка None в get_user_settings()**
**Файл:** `bot.py` (строка ~946)

```python
lang, quiet_start, quiet_end = get_user_settings(user_id)
```

**Проблема:** `get_user_settings()` возвращает None если не найдена, но код это не обрабатывает → **TypeError**

**Решение:**
```python
# В database.py добавить функцию:
def get_user_settings(user_id: int) -> Tuple[str, int, int]:
    """Returns (language, quiet_hours_start, quiet_hours_end) with defaults."""
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
        return ("ru", 23, 7)  # Безопасные значения по умолчанию
```

---

### 4. **Missing index на URL в price_history**
**Файл:** `database.py` (строка ~208)

Индекс есть для `(subscription_id, ts DESC)`, но при поиске по URL в scheduler может быть slow query.

**Решение:** Добавить индекс
```python
cur.execute("CREATE INDEX IF NOT EXISTS idx_price_history_url_ts ON price_history(url, ts DESC)")
```

---

### 5. **No Error Handling в scheduler при сбое сети**
**Файл:** `bot.py` функция `check_all()` (строка ~960)

Если Trendyol недоступен → все 10 корутин зависают на timeout. Нет retry логики.

**Решение:**
```python
@async_retry(
    exceptions=(requests.RequestException, asyncio.TimeoutError),
    tries=2,
    delay=1,
    logger=logger
)
async def get_product_info_async(url: str):
    # ... existing code ...
```

---

## 🟠 СЕРЬЁЗНЫЕ ПРОБЛЕМЫ (Should Fix)

### 6. **Потенциальная SQL Injection в normalize_url() → get_subscription_by_url()**
**Файл:** `bot.py` + `database.py`

Хотя используются параметризованные запросы, нормализация URL может быть неполной.

**Рекомендация:**
```python
def normalize_url(url: str) -> str:
    """Нормализует URL для сравнения, удаляя параметры сессии."""
    if not url:
        return ""
    
    u = url.strip().lower()
    
    # Удаляем якоря и параметры (но сохраняем важные)
    u = re.sub(r'[?#].*$', '', u)
    
    # Удаляем trailing slash
    u = u.rstrip('/')
    
    # Валидация базового URL
    if not u.startswith(('http://', 'https://')):
        u = 'https://' + u
    
    return u
```

---

### 7. **Не закрыто соединение sqlite при исключении**
**Файл:** `database.py` - множество функций

SQLite обычно автоматически закрывает соединение в `with` блоке, но лучше добавить явную обработку:

```python
def add_price_point(subscription_id: int, url: str, price: float, ts: int = None, source: str = 'collector') -> int:
    """Insert a price point for a subscription. Returns inserted id."""
    if ts is None:
        ts = int(time.time())
    
    try:
        with sqlite3.connect(DB) as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO price_history (subscription_id, url, price, ts, source) 
                VALUES (?, ?, ?, ?, ?)
            """, (subscription_id, url, price, ts, source))
            conn.commit()
            return cur.lastrowid
    except sqlite3.IntegrityError as e:
        logger.error(f"Integrity error adding price point: {e}")
        return -1
    except Exception as e:
        logger.exception(f"Failed to add price point: {e}")
        return -1
```

---

### 8. **Неправильная обработка datetime в send_history_plot()**
**Файл:** `bot.py` (строка ~103-140)

```python
if isinstance(d, str):
    ds = d.strip()
    try:
        parsed_dt = datetime.strptime(ds, "%d.%m.%Y")  # ❌ Не учитывает время!
    except ValueError:
        # ... other formats
```

**Проблема:** Если дата имеет формат "20.09.2025 14:30", парсер упадёт

**Решение:**
```python
def parse_date_flexible(date_str: str) -> Optional[datetime]:
    """Парсит дату в разных форматах."""
    formats = [
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y %H:%M",
        "%d.%m.%Y",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    
    return None
```

---

### 9. **Scheduler может пропустить проверки если bot.send_photo() зависает**
**Файл:** `bot.py` (строка ~1018)

```python
await bot.send_photo(user_id, photo=image or None, caption=caption)
```

**Проблема:** Если фото долго загружается → все уведомления в очереди задерживаются

**Решение:**
```python
async def send_notification_safe(user_id: int, text: str, image: Optional[str] = None, timeout: float = 10.0):
    """Отправляет уведомление с timeout."""
    try:
        if image:
            await asyncio.wait_for(
                bot.send_photo(user_id, photo=image, caption=text),
                timeout=timeout
            )
        else:
            await asyncio.wait_for(
                bot.send_message(user_id, text),
                timeout=timeout
            )
    except asyncio.TimeoutError:
        logger.warning(f"Notification send timeout for user {user_id}")
        # Fallback to text-only
        try:
            await bot.send_message(user_id, text)
        except Exception as e:
            logger.exception(f"Failed to send fallback message: {e}")
    except Exception as e:
        logger.exception(f"Notification send error for user {user_id}: {e}")
```

---

## 🟡 СРЕДНИЕ ПРОБЛЕМЫ & УЛУЧШЕНИЯ

### 10. **Множественные запросы к БД в цикле scheduler**
**Файл:** `bot.py` функция `check_all()` (строка ~960)

```python
for sub in subs:
    # Каждый раз вызывается
    get_user_settings(user_id)  # 1 запрос
    get_subscription(sid)        # 1 запрос
    ...
```

**Проблема:** Если 1000 подписок → 2000+ запросов за цикл!

**Решение:** Кэшировать в памяти
```python
async def check_all():
    user_cache = {}  # {user_id: (lang, quiet_start, quiet_end)}
    
    def get_cached_user_settings(uid):
        if uid not in user_cache:
            user_cache[uid] = get_user_settings(uid)
        return user_cache[uid]
    
    # ... использовать get_cached_user_settings() везде
```

---

### 11. **Отсутствует валидация URL перед добавлением подписки**
**Файл:** `bot.py` (строка ~835)

Функция `is_trendyol_product_url()` проверяет только presence `/p/`, но не валидирует формат.

```python
def is_trendyol_product_url(u: str) -> bool:
    ul = (u or "").lower()
    # ❌ Это слишком простая проверка!
    return ("trendyol.com" in ul) and ("/p/" in ul or "-p-" in ul)
```

**Улучшение:**
```python
TRENDYOL_URL_PATTERN = re.compile(
    r"https?://(?:www\.)?trendyol\.com/.+?-p-\d+(?:[/?].*)?$",
    re.IGNORECASE
)

def is_trendyol_product_url(url: str) -> bool:
    """Проверяет формат Trendyol product URL."""
    return TRENDYOL_URL_PATTERN.match((url or "").strip()) is not None
```

---

### 12. **Нет логирования при удалении подписок по блокировке бота**
**Файл:** `bot.py` (строка ~1025)

```python
except (aiogram.exceptions.TelegramForbiddenError, aiogram.exceptions.TelegramBadRequest) as e:
    logger.warning("User %d blocked the bot or chat not found. Removing subscriptions.", user_id)
    remove_subscriptions_by_user(user_id)
```

**Проблема:** Нет логирования сколько подписок удалено

**Решение:**
```python
except (aiogram.exceptions.TelegramForbiddenError, aiogram.exceptions.TelegramBadRequest) as e:
    count = len(get_user_subscriptions(user_id))
    logger.warning(f"User {user_id} blocked the bot. Removing {count} subscriptions.")
    remove_subscriptions_by_user(user_id)
```

---

### 13. **Asymmetric behavior: "hourly" режим не учитывает интервалы**
**Файл:** `bot.py` (строка ~1000)

```python
if mode == "hourly":
    notification_needed = True  # ❌ Игнорирует notify_interval!
```

**Проблема:** "hourly" режим отправляет каждые 60 минут проверки, но это не обязательно "hourly"

**Решение:**
```python
if mode == "hourly":
    # Проверяем интервал, даже для hourly
    if notify_interval and last_notify_time:
        if int(time.time()) - last_notify_time < notify_interval * 60:
            notification_needed = False
        else:
            notification_needed = True
    else:
        notification_needed = True
    
    if notification_needed:
        notification_text = t(user_id, "hourly_msg").format(price=price, url=url)
```

---

### 14. **Нет timeout при get_price() запросе**
**Файл:** `scraper.py` (строка ~100)

```python
r = requests.get(url, headers=HEADERS, timeout=15)  # ✅ Есть timeout
```

Хорошо, но для async версии нужно проверить.

---

### 15. **Локали не все ключи имеют fallback**
**Файл:** `bot.py` функция `t()` (строка ~79)

```python
def t(user_id: int, key: str) -> str:
    """Return localized string for user; fallback to ru or key."""
    # ...
    return loc.get(key, key)  # ❌ Возвращает сам ключ если нет перевода!
```

**Проблема:** Если ключ отсутствует в JSON → показывается "history_chart_title" вместо текста

**Решение:**
```python
def t(user_id: int, key: str, default: str = None) -> str:
    """Return localized string for user; fallback to ru or key."""
    try:
        lang = get_user_language(user_id) or "ru"
    except Exception:
        lang = "ru"
    
    loc = LOCALES.get(lang, LOCALES.get("ru", {}))
    ru_loc = LOCALES.get("ru", {})
    
    # Приоритет: user_lang → ru → default → key
    return loc.get(key) or ru_loc.get(key) or default or f"[{key}]"
```

---

## 🟢 ПОЗИТИВНЫЕ МОМЕНТЫ

### ✅ Хорошие практики, которые уже есть:

1. **Async/await архитектура** - правильно используется asyncio + aiogram 3.x
2. **Rate limiting** - реализован RateLimiter в utils.py
3. **Anti-spam middleware** - защита от spam в bot.py
4. **Database schema** - хорошие индексы и PRAGMA оптимизации
5. **Retry logic** - декораторы @retry и @async_retry в utils.py
6. **Graceful error handling** - большинство функций обёрнуты в try/except
7. **Локализация** - поддержка 4 языков
8. **Structured logging** - использование logging с RotatingFileHandler
9. **Connection pooling** - SQLite с оптимальными PRAGMA настройками
10. **Graceful shutdown** - корректное удаление webhook перед polling

---

## 📋 РЕКОМЕНДАЦИИ ПО СТРУКТУРЕ

### Предложенная новая структура для growth:

```
telegrambot/
├── config/
│   ├── __init__.py
│   ├── settings.py          # Все конфиги здесь
│   └── .env.example         # Пример переменных окружения
├── src/
│   ├── __init__.py
│   ├── bot.py              # Только main() и dispatcher
│   ├── handlers/
│   │   ├── __init__.py
│   │   ├── user_handlers.py
│   │   ├── admin_handlers.py
│   │   └── callback_handlers.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── scraper_service.py
│   │   ├── notification_service.py
│   │   └── scheduler_service.py
│   ├── models/
│   │   ├── __init__.py
│   │   └── subscription.py
│   └── utils/
│       ├── __init__.py
│       ├── validators.py
│       ├── formatters.py
│       └── decorators.py
├── locales/                 # Оставить как есть
├── logs/                    # Автогенерируется
├── tests/
│   ├── test_scraper.py
│   ├── test_database.py
│   └── test_handlers.py
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml
├── requirements.txt
├── .gitignore
├── .env.example
└── README.md
```

---

## 🚀 ПЛАН МИГРАЦИИ НА PRODUCTION

### Phase 1: Immediate (Сегодня)
- [ ] Удалить hardcoded BOT_TOKEN
- [ ] Добавить .env.example
- [ ] Исправить get_user_settings() fallback

### Phase 2: Short-term (1-2 недели)
- [ ] Добавить unit тесты для scraper
- [ ] Добавить integration тесты для scheduler
- [ ] Реализовать кэширование user_settings в check_all()
- [ ] Добавить timeout для bot.send_photo()

### Phase 3: Medium-term (1 месяц)
- [ ] Рефакторинг bot.py на handlers (разделить на файлы)
- [ ] Добавить Docker support
- [ ] Настроить мониторинг (Sentry или другое)
- [ ] Добавить graceful shutdown для scheduler

### Phase 4: Long-term (3+ месяцев)
- [ ] Миграция с SQLite на PostgreSQL
- [ ] Добавить Redis для кэширования
- [ ] Implement webhook вместо polling
- [ ] Добавить admin панель

---

## 📊 Метрики качества кода

| Аспект | Оценка | Комментарий |
|--------|--------|-----------|
| Security | 4/10 | Hardcoded token - КОД В GITHUB! |
| Performance | 6/10 | N+1 запросы в scheduler |
| Maintainability | 7/10 | Хороший, но нужна модуляризация |
| Testing | 3/10 | Почти нет тестов |
| Error Handling | 7/10 | Хороший, но есть пробелы |
| Documentation | 5/10 | Нужны docstrings и README |
| Database Design | 8/10 | Хорошие индексы и оптимизации |
| API Design | 7/10 | Консистентно, но немного многословно |

**Общий Score: 6.1/10** ⚠️ Требует доработки перед production

---

## 🔧 Команды для быстрого старта исправлений

```bash
# 1. Создать .env файл
cp .env.example .env
# Отредактировать .env и добавить реальный BOT_TOKEN

# 2. Обновить config.py
# (см. решение выше)

# 3. Создать .gitignore (если нет)
echo ".env" >> .gitignore
echo "*.db" >> .gitignore
echo "logs/" >> .gitignore
echo "venv/" >> .gitignore

# 4. Запустить тесты (добавить в requirements.txt: pytest)
pip install pytest pytest-asyncio
pytest tests/

# 5. Запустить линтер
pip install pylint
pylint src/ --max-line-length=120
```

---

## 📞 Вопросы для обсуждения

1. **Сколько пользователей планируете?** (влияет на выбор БД)
2. **Нужна ли история цен более 30 дней?** (требует оптимизации хранения)
3. **Будет ли admin панель?** (требует auth слоя)
4. **Нужна ли интеграция с Stripe/PayPal?** (требует payment обработки)

---

**Дата написания:** 5 декабря 2025  
**Версия:** 1.0  
**Автор анализа:** GitHub Copilot Code Review

