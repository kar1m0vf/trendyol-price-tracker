#!/usr/bin/env python3
"""
Тест для проверки установки меню команд бота
"""
import asyncio
import os
import pytest
from dotenv import load_dotenv
from aiogram import Bot
from aiogram.types import BotCommand
from aiogram.utils.token import TokenValidationError, validate_token

# Загружаем переменные окружения
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

async def test_set_commands_menu():
    """Тестируем установку меню команд"""
    if not BOT_TOKEN:
        pytest.skip("BOT_TOKEN не найден в .env файле")

    try:
        validate_token(BOT_TOKEN)
    except TokenValidationError:
        pytest.skip("BOT_TOKEN имеет невалидный формат для aiogram")

    bot = Bot(token=BOT_TOKEN)

    commands = [
        BotCommand(command="start", description="🚀 Start the bot"),
        BotCommand(command="help", description="❓ Help and commands"),
        BotCommand(command="mysubs", description="📃 My subscriptions"),
        BotCommand(command="compare", description="⚖️ Compare prices"),
        BotCommand(command="recommend", description="💡 Recommendations"),
        BotCommand(command="settings", description="⚙️ Bot settings"),
        BotCommand(command="language", description="🌐 Change language"),
        BotCommand(command="history", description="📈 Price history"),
        BotCommand(command="alerts", description="🔔 Manage alerts"),
        BotCommand(command="stats", description="📊 Statistics"),
        BotCommand(command="export", description="📤 Export data"),
        BotCommand(command="about", description="ℹ️ About the bot"),
        BotCommand(command="ping", description="🏓 Check bot response"),
        BotCommand(command="health", description="💚 Bot health status"),
    ]

    try:
        await bot.set_my_commands(commands)
        print("✅ Меню команд успешно обновлено!")
        print("📋 Установлены команды (без админ панели):")
        for cmd in commands:
            print(f"  /{cmd.command} - {cmd.description}")
        print(f"\n📊 Всего команд: {len(commands)}")
    except Exception as e:
        print(f"❌ Ошибка установки меню команд: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(test_set_commands_menu())
