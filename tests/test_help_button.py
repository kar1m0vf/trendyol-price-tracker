                      
"""
Тест для проверки работы кнопки подробной справки
"""
import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

                                
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=ROOT / ".env")
BOT_TOKEN = os.getenv("BOT_TOKEN")

async def test_help_button():
    """Тестируем отправку сообщения с кнопкой подробной справки"""
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN не найден в .env файле")
        return

    bot = Bot(token=BOT_TOKEN)

                                                    
    help_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📖 Подробная справка", callback_data="help:full")]
    ])

    help_text = """❓ **Справка по боту**

Я слежу за ценами на Trendyol и уведомляю о скидках!

**Основные команды:**
• /start - запустить бота
• /mysubs - мои подписки
• /compare - сравнить цены
• /recommend - рекомендации
• /settings - настройки

**Как подписаться:**
1. Отправьте ссылку на товар Trendyol
2. Выберите режим уведомлений

💡 Для получения подробной информации нажмите кнопку ниже."""

    try:
                                                           
        await bot.send_message(chat_id=int(os.getenv("ADMIN_IDS", "975282591").split(",")[0]),
                              text=help_text,
                              reply_markup=help_keyboard,
                              parse_mode="Markdown")
        print("✅ Тестовое сообщение с кнопкой подробной справки отправлено!")
        print("📱 Проверьте Telegram - должно прийти сообщение с кнопкой")
    except Exception as e:
        print(f"❌ Ошибка отправки тестового сообщения: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(test_help_button())
