                      
"""
Тест для проверки работы многоязычности и функции изменения языка
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
from localization import t

async def test_language_functionality():
    """Тестируем работу многоязычности и изменения языка"""
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN не найден в .env файле")
        return

    bot = Bot(token=BOT_TOKEN)
    admin_id = int(os.getenv("ADMIN_IDS", "975282591").split(",")[0])

    print("🌐 Тестируем многоязычность бота...")
    print("=" * 50)

    languages = ['ru', 'en', 'az', 'tr']
    test_results = {}

    for lang in languages:
        print(f"\n📋 Тестируем язык: {lang.upper()}")
        user_id = {'ru': 975282591, 'en': 123456789, 'az': 987654321, 'tr': 111111111}[lang]

                                            
        detailed_help_text = t(user_id, "btn_detailed_help")
        print(f"  ✅ Кнопка подробной справки: '{detailed_help_text}'")

                                 
        help_text = t(user_id, "help_text")
        help_full = t(user_id, "help_full")
        print(f"  ✅ Краткая справка: {len(help_text)} символов")
        print(f"  ✅ Полная справка: {len(help_full)} символов")

                                           
        lang_kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=t(user_id, "lang_ru"), callback_data="lang:ru"),
                InlineKeyboardButton(text=t(user_id, "lang_en"), callback_data="lang:en")
            ],
            [
                InlineKeyboardButton(text=t(user_id, "lang_az"), callback_data="lang:az"),
                InlineKeyboardButton(text=t(user_id, "lang_tr"), callback_data="lang:tr")
            ]
        ])

        print(f"  ✅ Клавиатура выбора языка создана")

        test_results[lang] = {
            'detailed_help': detailed_help_text,
            'help_text_len': len(help_text),
            'help_full_len': len(help_full)
        }

    print("\n" + "=" * 50)
    print("📊 РЕЗУЛЬТАТЫ ТЕСТИРОВАНИЯ:")
    print("=" * 50)

    for lang, results in test_results.items():
        print(f"{lang.upper()}:")
        print(f"  📖 Подробная справка: {results['detailed_help']}")
        print(f"  📝 Краткая справка: {results['help_text_len']} симв.")
        print(f"  📚 Полная справка: {results['help_full_len']} симв.")
        print()

                                                             
    print("📤 Отправляем тестовые сообщения с кнопками...")

    for lang in languages:
        user_id = {'ru': admin_id, 'en': admin_id, 'az': admin_id, 'tr': admin_id}[lang]

        help_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t(user_id, "btn_detailed_help"), callback_data="help:full")]
        ])

        try:
            await bot.send_message(
                chat_id=admin_id,
                text=f"🧪 Тест локализации - {lang.upper()}\n\n{t(user_id, 'help_text')[:100]}...",
                reply_markup=help_keyboard
            )
            print(f"  ✅ Сообщение на {lang.upper()} отправлено")
        except Exception as e:
            print(f"  ❌ Ошибка отправки {lang.upper()}: {e}")

    print("\n🎉 Тестирование завершено!")
    print("📱 Проверьте Telegram - должны прийти тестовые сообщения на всех языках")

    await bot.session.close()

if __name__ == "__main__":
    asyncio.run(test_language_functionality())
