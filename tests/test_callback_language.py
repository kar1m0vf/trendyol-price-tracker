                      
"""
Тест для проверки callback'ов изменения языка
"""
import asyncio
import os
from dotenv import load_dotenv
from aiogram import Bot
from aiogram.types import CallbackQuery, User

                                
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

                                    
import sys
sys.path.append('.')
from localization import t, update_language_cache
from database import get_user_language, set_user_language

class MockCallbackQuery:
    """Mock CallbackQuery для тестирования"""
    def __init__(self, user_id: int, data: str):
        self.from_user = User(id=user_id, is_bot=False, first_name="Test")
        self.data = data
        self.message = MockMessage()

    async def answer(self, text=None, **kwargs):
        print(f"✅ Callback answered: {text}")

class MockMessage:
    """Mock Message для тестирования"""
    async def edit_text(self, text, **kwargs):
        print(f"📝 Message edited: {text[:50]}...")

class MockBot:
    """Mock Bot для тестирования"""
    async def send_message(self, chat_id, text, **kwargs):
        print(f"📤 Message sent to {chat_id}: {text[:50]}...")

async def test_callback_language_change():
    """Тестируем callback изменения языка"""
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN не найден в .env файле")
        return

    bot = MockBot()
    admin_id = int(os.getenv("ADMIN_IDS", "975282591").split(",")[0])

    print("🧪 Тестируем callback изменения языка...")
    print("=" * 50)

                             
    original_lang = get_user_language(admin_id)
    print(f"📍 Исходный язык: {original_lang.upper()}")

                                         
    test_langs = ['tr', 'az', 'en', 'ru']                                                   

    for lang in test_langs:
        print(f"\n🔄 Меняем на {lang.upper()}...")

                            
        cq = MockCallbackQuery(admin_id, f"lang:{lang}")

                                             
        await cq.answer()
        lang_code = cq.data.split(":", 1)[1]
        set_user_language(admin_id, lang_code)
        update_language_cache(admin_id, lang_code)

                             
        new_lang = get_user_language(admin_id)
        cached_lang = update_language_cache                              

                               
        detailed_help = t(admin_id, "btn_detailed_help")
        start_text = t(admin_id, "start_text")[:60] + "..."
        lang_changed = t(admin_id, "lang_changed")

        print(f"  ✅ База данных: {new_lang.upper()}")
        print(f"  📖 Кнопка справки: '{detailed_help}'")
        print(f"  📝 Сообщение изменения: '{lang_changed}'")
        print(f"  🎉 Стартовый текст: '{start_text}'")

                                      
        try:
            await bot.send_message(admin_id, t(admin_id, "start_text"))
            await cq.message.edit_text(t(admin_id, "lang_changed"))
        except Exception as e:
            print(f"  ❌ Ошибка: {e}")

                              
    set_user_language(admin_id, original_lang)
    update_language_cache(admin_id, original_lang)
    print(f"\n🔙 Возвращен исходный язык: {original_lang.upper()}")

    print("\n🎉 Тестирование callback'ов завершено!")
    print("Если все работает правильно, локализация должна меняться мгновенно.")

if __name__ == "__main__":
    asyncio.run(test_callback_language_change())
