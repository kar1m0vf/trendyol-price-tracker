1) Открой VS Code, открой папку trendyol_bot.
2) Создай виртуальное окружение:
   python -m venv venv

3) Открой терминал в VS Code и активируй venv:
   Вариант безопасный (Windows): переключить терминал на 'Command Prompt' и выполнить:
     venv\Scripts\activate.bat

   (Или в PowerShell, если хочешь, но там нужно менять ExecutionPolicy.)

4) Установи зависимости:
   pip install -r requirements.txt

   Примечание: в requirements добавлен пакет `cloudscraper` чтобы обходить защиту Cloudflare при парсинге Trendyol.

5) Открой config.py и вставь BOT_TOKEN (от BotFather).

6) Запусти:
   python bot.py

7) В Telegram найди бота по username и отправь /start.
