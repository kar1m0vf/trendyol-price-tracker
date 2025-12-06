#!/bin/bash
# Чек-лист перед запуском бота

echo "=========================================="
echo "Telegram Price Tracker Bot - Чек-лист"
echo "=========================================="
echo ""

# Проверка Python
echo "1. Проверка Python..."
python --version && echo "   ✅ Python установлен" || echo "   ❌ Python не найден"
echo ""

# Проверка virtual environment
echo "2. Проверка virtual environment..."
if [ -d "venv" ]; then
    echo "   ✅ venv существует"
else
    echo "   ❌ venv не найден"
    echo "   Создайте: python -m venv venv"
fi
echo ""

# Проверка .env файла
echo "3. Проверка .env файла..."
if [ -f ".env" ]; then
    echo "   ✅ .env файл существует"
    if grep -q "BOT_TOKEN=" .env; then
        echo "   ✅ BOT_TOKEN присутствует"
    else
        echo "   ❌ BOT_TOKEN не найден в .env"
    fi
else
    echo "   ❌ .env файл не найден"
    echo "   Скопируйте из .env.example или создайте новый"
fi
echo ""

# Проверка dependencies
echo "4. Проверка зависимостей..."
if [ -f "requirements.txt" ]; then
    echo "   ✅ requirements.txt существует"
    echo "   Убедитесь что все установлены:"
    echo "   python -m pip install -r requirements.txt"
else
    echo "   ❌ requirements.txt не найден"
fi
echo ""

# Проверка основных файлов
echo "5. Проверка основных файлов..."
for file in bot.py config.py database.py scraper.py middleware.py keyboards.py utils.py
do
    if [ -f "$file" ]; then
        echo "   ✅ $file существует"
    else
        echo "   ❌ $file не найден"
    fi
done
echo ""

# Проверка БД
echo "6. Проверка базы данных..."
if [ -f "trendyol_bot.db" ]; then
    echo "   ✅ trendyol_bot.db существует"
else
    echo "   ℹ️  БД будет создана при первом запуске"
fi
echo ""

echo "=========================================="
echo "Команда для запуска бота:"
echo ""
echo "  python bot.py"
echo ""
echo "Команда для проверки готовности:"
echo ""
echo "  python check_bot_ready.py"
echo ""
echo "=========================================="
