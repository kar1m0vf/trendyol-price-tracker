# Найденные проблемы и недоработки

## 🔴 Критические проблемы (могут вызвать ошибки)

### 1. Несоответствие количества полей в `get_all_subscriptions()`
**Проблема**: Функция возвращает только 12 полей, но в `check_all()` ожидается 13 полей (с `price_alert`)

**Файл**: `database.py:437-440`
```python
# Текущий код возвращает только 12 полей:
SELECT id, user_id, url, notify_mode, last_price, product_title, product_image,
       min_price, max_price, notify_percent, notify_interval, last_notify_time
```

**Файл**: `bot.py:1474-1475`
```python
# Ожидается 13 полей:
(sub_id, user_id, url, mode, last_price, product_title, product_image,
 min_price, max_price, notify_percent, notify_interval, last_notify_time, price_alert) = sub
```

**Решение**: Добавить `price_alert` в SELECT запрос `get_all_subscriptions()`

### 2. Несоответствие в `get_user_subscriptions()`
**Проблема**: 
- Docstring указывает 13 полей (без `tags`)
- SELECT запрос возвращает 14 полей (с `tags`)
- В разных местах кода ожидается разное количество полей

**Файл**: `database.py:336-345`
```python
# Docstring говорит 13 полей, но SELECT возвращает 14:
SELECT id, user_id, url, notify_mode, last_price, product_title, product_image,
       min_price, max_price, notify_percent, notify_interval, last_notify_time, price_alert, tags
```

**Решение**: Обновить docstring и унифицировать распаковку во всех местах

### 3. `get_subscription_by_url()` не возвращает новые поля
**Проблема**: Функция возвращает только 12 полей (без `price_alert` и `tags`)

**Файл**: `database.py:288-291`
```python
SELECT id, user_id, url, notify_mode, last_price, product_title, product_image,
       min_price, max_price, notify_percent, notify_interval, last_notify_time
```

**Решение**: Добавить `price_alert` и `tags` в SELECT

## 🟡 Важные проблемы (работает, но неправильно)

### 4. Хардкод строк вместо локализации в командах
**Проблема**: Команды `/stats`, `/all_list`, `/top_drops` используют хардкод русских строк, хотя ключи уже есть в locales

**Файлы**: 
- `bot.py:810, 817, 829, 838-850` - команда `/stats`
- `bot.py:871, 911, 914, 916-924` - команды `/all_list` и `/top_drops`

**Пример**:
```python
# Текущий код:
await message.answer("ℹ️ Использование: /stats <ID>\nПример: /stats 5")
await message.answer("❌ Подписка не найдена")
await message.answer("📊 История цен еще не собрана. Попробуйте позже.")

# Должно быть:
await message.answer(t(message.from_user.id, "cmd_stats_usage"))
await message.answer(t(message.from_user.id, "subscription_not_found"))  # Нужно добавить ключ
await message.answer(t(message.from_user.id, "stats_no_history"))
```

**Решение**: Заменить все хардкод строки на вызовы `t()`, добавить недостающие ключи в locales

### 5. Неправильная валюта в уведомлении `price_alert`
**Проблема**: В сообщении о достижении целевой цены используется символ ₽ (рубли) вместо TL (турецкие лиры)

**Файл**: `bot.py:1542-1543`
```python
f"Целевая цена: {price_alert:.0f}₽\n"
f"Текущая цена: {price:.0f}₽\n"
```

**Решение**: Заменить ₽ на TL

### 6. Несоответствие docstring в `get_subscription()`
**Проблема**: Docstring говорит "13 fields", но функция возвращает 13 полей (с `price_alert`, без `tags`), что правильно, но может быть неясно

**Файл**: `database.py:463`
```python
"""Return canonical subscription tuple (13 fields) or None"""
```

**Решение**: Уточнить docstring: "13 fields: id, user_id, url, ..., price_alert (без tags)"

## 🟢 Мелкие проблемы (можно улучшить)

### 7. Импорт внутри функции
**Проблема**: В командах `/stats` и `/top_drops` используется импорт внутри функции

**Файлы**: 
- `bot.py:825`: `from database import get_price_stats`
- `bot.py:906`: `from database import get_top_price_drops`

**Решение**: Вынести импорты в начало файла

### 8. Неиспользуемая функция `get_subscription_by_url()`
**Проблема**: Функция определена, но нигде не используется

**Файл**: `database.py:284-294`

**Решение**: Либо использовать, либо удалить

### 9. Неполная обработка ошибок в команде `/stats`
**Проблема**: При ошибке показывается техническое сообщение пользователю

**Файл**: `bot.py:857`
```python
await message.answer(f"❌ Ошибка: {e}")
```

**Решение**: Использовать общее сообщение об ошибке из локализации

### 10. Отсутствие проверки на None в `/stats`
**Проблема**: При обращении к `sub[2]` нет проверки, что `sub` не None (хотя есть проверка выше)

**Файл**: `bot.py:841`
```python
🔗 {sub[2][:50]}...
```

**Решение**: Добавить проверку или использовать более безопасный доступ

### 11. Несоответствие формата в `/all_list`
**Проблема**: Используется хардкод "ID  | Режим      | Цена    | Статус" вместо локализации

**Файл**: `bot.py:872`

**Решение**: Вынести в локализацию

### 12. Несоответствие валюты в `/top_drops`
**Проблема**: Используется "TL" в хардкод строках, но это правильно. Однако лучше использовать локализацию

**Файл**: `bot.py:924`

## 📋 Резюме проблем

### Критические (нужно исправить немедленно):
1. ✅ **ИСПРАВЛЕНО** `get_all_subscriptions()` - добавлен `price_alert` в SELECT
2. ✅ **ИСПРАВЛЕНО** `get_subscription_by_url()` - добавлены `price_alert` и `tags`
3. ✅ **ИСПРАВЛЕНО** Унифицированы docstrings для всех функций получения подписок

### Важные (исправить в ближайшее время):
4. ✅ **ИСПРАВЛЕНО** Локализация команд `/stats`, `/all_list`, `/top_drops`
5. ✅ **ИСПРАВЛЕНО** Исправлена валюта в уведомлении `price_alert` (₽ → TL)
6. ✅ **ИСПРАВЛЕНО** Импорты вынесены из функций в начало файла

### Мелкие (можно отложить):
7. ✅ **ИСПРАВЛЕНО** Улучшена обработка ошибок (все сообщения используют локализацию)
8. ✅ Удалить неиспользуемую функцию или использовать её
9. ✅ **ИСПРАВЛЕНО** Добавлены недостающие ключи локализации во все языки (en, az, tr)

## 🔧 Быстрые исправления

### Исправление 1: `get_all_subscriptions()` в `database.py`
```python
# Строка 437-440, заменить на:
cur.execute("""
    SELECT id, user_id, url, notify_mode, last_price, product_title, product_image,
           min_price, max_price, notify_percent, notify_interval, last_notify_time, price_alert
    FROM subscriptions
    ORDER BY COALESCE(last_notify_time, 0) ASC
""")
```

### Исправление 2: `get_subscription_by_url()` в `database.py`
```python
# Строка 288-291, заменить на:
cur.execute("""
    SELECT id, user_id, url, notify_mode, last_price, product_title, product_image,
           min_price, max_price, notify_percent, notify_interval, last_notify_time, price_alert, tags
    FROM subscriptions WHERE url = ? LIMIT 1
""", (url,))
```

### Исправление 3: Валюта в `bot.py`
```python
# Строка 1542-1543, заменить на:
f"Целевая цена: {price_alert:.0f} TL\n"
f"Текущая цена: {price:.0f} TL\n"
```

### Исправление 4: Локализация в `/stats`
```python
# Заменить все хардкод строки на:
await message.answer(t(message.from_user.id, "cmd_stats_usage"))
await message.answer(t(message.from_user.id, "subscription_not_found"))  # Нужно добавить в locales
await message.answer(t(message.from_user.id, "stats_no_history"))
text = t(message.from_user.id, "stats_header").format(...)
```

