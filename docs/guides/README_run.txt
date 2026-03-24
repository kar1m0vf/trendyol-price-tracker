1) Открой VS Code, открой папку trendyol_bot.
2) Создай виртуальное окружение (если еще не создано):
   python -m venv venv

3) Активируй виртуальное окружение:
   Windows (PowerShell): .\venv\Scripts\Activate.ps1
   Windows (Command Prompt): venv\Scripts\activate.bat
   Linux/Mac: source venv/bin/activate

4) Установи зависимости в виртуальное окружение:
   pip install -r requirements.txt

   Примечание: в requirements добавлен пакет `cloudscraper` чтобы обходить защиту Cloudflare при парсинге Trendyol.

5) Создай файл .env в корне проекта со следующим содержимым:
   BOT_TOKEN=ваш_токен_от_BotFather
   ADMIN_IDS=ваш_telegram_user_id
   DATABASE_PATH=trendyol_bot.db

6) Запусти:
   python bot.py

7) В Telegram найди бота по username и отправь /start.

---

## 🗂️ ПЕРЕНОС БОТА НА ДРУГОЙ СЕРВЕР

Все зависимости изолированы в виртуальном окружении `venv/`.
Для переноса достаточно скопировать всю папку проекта.

### Что копировать:
- ✅ Вся папка `telegrambot/`
- ✅ Включая `venv/` (виртуальное окружение с зависимостями)
- ✅ Включая `.env` (конфигурация)

### Что НЕ копировать (опционально):
- ❌ `*.db` файлы (база данных - можно создать заново)
- ❌ `logs/` (логи - создадутся автоматически)

### Запуск на новом сервере:
```bash
cd telegrambot
# venv уже содержит все зависимости
./venv/Scripts/python.exe bot.py  # Windows
# или
./venv/bin/python bot.py         # Linux/Mac
```
