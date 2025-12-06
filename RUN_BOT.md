# Запуск Telegram бота

## Предварительные условия

1. ✅ Python 3.11+ установлен
2. ✅ Virtual environment создан (`venv/`)
3. ✅ Зависимости установлены (`pip install -r requirements.txt`)
4. ✅ `.env` файл создан с `BOT_TOKEN`

## Проверка конфигурации

### Убедитесь что .env файл существует:
```bash
Test-Path .env
```

### Проверьте что BOT_TOKEN установлен:
```bash
.\venv\Scripts\python.exe -c "from config import BOT_TOKEN; print(f'BOT_TOKEN loaded: {bool(BOT_TOKEN)}')"
```

Вывод должен быть: `BOT_TOKEN loaded: True`

## Запуск бота

### Простой запуск (на переднем плане):
```bash
.\venv\Scripts\python.exe bot.py
```

### Запуск с логированием:
```bash
.\venv\Scripts\python.exe bot.py 2>&1 | Tee-Object bot.log
```

## Проверка что всё работает

Перед запуском бота используйте эту команду для проверки:
```bash
.\venv\Scripts\python.exe -c "from bot import bot, dp, check_all; from database import init_db; from config import _check_bot_token; _check_bot_token(); print('All imports and validations successful'); print('Bot is ready to run')"
```

## Что делает бот?

1. **Инициализирует базу данных** SQLite при запуске
2. **Запускает планировщик** APScheduler для проверки цен каждые 60 минут
3. **Слушает команды** от пользователей в Telegram
4. **Обрабатывает подписки** на отслеживание цен товаров

## Основные команды бота

- `/start` - Начать работу с ботом
- `/subscribe` - Подписаться на отслеживание цены
- `/unsubscribe` - Отписаться от отслеживания
- `/trending` - Получить тренды
- `/history` - История цен
- `/settings` - Настройки уведомлений

## Шаги исправления

### Исправления уже выполнены:
1. ✅ Перемещён BOT_TOKEN в `.env` файл для безопасности
2. ✅ Добавлена валидация токена перед инициализацией бота
3. ✅ Улучшены функции базы данных (кэширование, безопасность)
4. ✅ Добавлены улучшения обработки ошибок и таймаутов
5. ✅ Установлены все зависимости включая `python-dotenv`

## Возможные проблемы и решения

### Ошибка: "No module named 'dotenv'"
**Решение:** Переустановите зависимости
```bash
.\venv\Scripts\pip install -r requirements.txt
```

### Ошибка: "BOT_TOKEN не установлен"
**Решение:** Создайте файл `.env` с вашим токеном
```
BOT_TOKEN=<BOT_TOKEN_REDACTED>
```

### Бот не запускается с "Exit code 1"
**Решение:** Проверьте все импорты
```bash
.\venv\Scripts\python.exe -m py_compile bot.py config.py database.py
```

## Дополнительная информация

- 📄 Документация находится в файлах: `CODE_REVIEW_ANALYSIS.md`, `FIXES_APPLIED.md`
- 🔒 Не коммитьте `.env` файл в git (см. `.gitignore`)
- 📊 База данных находится в `trendyol_bot.db`
- 📝 Логи находятся в папке `logs/`

## Контакт

Если у вас есть вопросы по запуску бота, проверьте:
1. Правильность BOT_TOKEN в `.env`
2. Наличие всех файлов конфигурации
3. Установку всех зависимостей из `requirements.txt`

