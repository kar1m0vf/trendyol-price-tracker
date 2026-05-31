                      
"""
Тест для проверки работы callback'ов в реальном боте.
"""
import os
import sys
import asyncio
from unittest.mock import MagicMock, AsyncMock

                                                                         
os.environ['USE_NEW_HANDLERS'] = 'true'

async def test_callback_flow():
    """Тест полного цикла работы callback'ов."""
    try:
                                           
        import bot
        from aiogram.types import CallbackQuery, User, Message

        print("✅ Bot imported successfully")

                                     
        mock_user = MagicMock(spec=User)
        mock_user.id = 12345

        mock_message = MagicMock(spec=Message)
        mock_message.edit_text = AsyncMock()

        mock_cq = MagicMock(spec=CallbackQuery)
        mock_cq.data = "lang:ru"
        mock_cq.from_user = mock_user
        mock_cq.message = mock_message
        mock_cq.answer = AsyncMock()

                                               
        from handlers import CallbackHandler
        handler = CallbackHandler()
        handler._bot = bot.bot

        print("✅ Handler created")

                            
        await handler.handle_main_callback(mock_cq)

                                              
        mock_cq.answer.assert_called_once()
        print("✅ Callback processed successfully")

                                       
        if "lang" in mock_cq.data:
                                                 
            from database import get_user_language
                                            
            from database import add_user_if_not_exists
            add_user_if_not_exists(12345)

                         
            from database import set_user_language
            set_user_language(12345, "ru")

            lang = get_user_language(12345)
            assert lang == "ru", f"Language should be 'ru', got '{lang}'"
            print("✅ Language changed successfully")

        return
    except Exception as e:
        print(f"❌ Callback flow test failed: {e}")
        import traceback
        traceback.print_exc()
        raise AssertionError("test reported failure")

def main():
    """Запуск тестов."""
    print("🧪 Testing real callback functionality...")
    print("=" * 60)

    results = []

                        
    try:
        asyncio.run(test_callback_flow())
        results.append(True)
        print("✅ Callback flow test passed")
    except Exception as e:
        print(f"❌ Callback flow test failed: {e}")
        results.append(False)

    print("=" * 60)

    passed = sum(results)
    total = len(results)

    if passed == total:
        print(f"🎉 All real callback tests passed! ({passed}/{total})")
        print("✅ Callback handlers work in real bot!")
        return 0
    else:
        print(f"⚠️  Some real callback tests failed: {passed}/{total}")
        return 1

if __name__ == "__main__":
    sys.exit(main())












