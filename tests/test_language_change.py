                      
"""
Тест для проверки работы изменения языка
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

                         
import sys
sys.path.insert(0, str(ROOT))
from localization import t, update_language_cache
from database import get_user_language, set_user_language

async def test_language_change():
    """Тестируем работу изменения языка"""
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN не найден в .env файле")
        return

    bot = Bot(token=BOT_TOKEN)
    admin_id = int(os.getenv("ADMIN_IDS", "975282591").split(",")[0])

    print("🌐 Тестируем функцию изменения языка...")
    print("=" * 50)

                                   
    current_lang = get_user_language(admin_id)
    print(f"📍 Текущий язык админа (ID: {admin_id}): {current_lang.upper()}")

                                       
    lang_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=t(admin_id, "lang_ru"), callback_data="lang:ru"),
            InlineKeyboardButton(text=t(admin_id, "lang_en"), callback_data="lang:en")
        ],
        [
            InlineKeyboardButton(text=t(admin_id, "lang_az"), callback_data="lang:az"),
            InlineKeyboardButton(text=t(admin_id, "lang_tr"), callback_data="lang:tr")
        ]
    ])

    print("✅ Клавиатура выбора языка создана")

                                                     
    try:
        await bot.send_message(
            chat_id=admin_id,
            text="🧪 Тест изменения языка\n\nНажмите на любую кнопку языка ниже:",
            reply_markup=lang_kb
        )
        print("✅ Тестовое сообщение с клавиатурой выбора языка отправлено")
        print("📱 Проверьте Telegram и нажмите на разные кнопки языка")
    except Exception as e:
        print(f"❌ Ошибка отправки сообщения: {e}")

                                          
    print("\n🔄 Тестируем программное изменение языка...")

    test_langs = ['ru', 'en', 'az', 'tr']
    for lang in test_langs:
        set_user_language(admin_id, lang)
        update_language_cache(admin_id, lang)                             
        new_lang = get_user_language(admin_id)

                                               
        help_btn_text = t(admin_id, "btn_detailed_help")
        start_text = t(admin_id, "start_text")[:50] + "..."

        print(f"  {lang.upper()} -> Получено: {new_lang.upper()}")
        print(f"    📖 Кнопка: '{help_btn_text}'")
        print(f"    📝 Старт: '{start_text}'")

                              
    set_user_language(admin_id, current_lang)
    print(f"\n🔙 Возвращен исходный язык: {current_lang.upper()}")

    print("\n🎉 Тестирование изменения языка завершено!")
    print("📱 В Telegram должно прийти сообщение с кнопками выбора языка")

    await bot.session.close()

if __name__ == "__main__":
    asyncio.run(test_language_change())
