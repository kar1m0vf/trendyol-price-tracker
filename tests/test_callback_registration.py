                      
"""
Тест для проверки регистрации callback обработчиков.
"""
import os
import sys
import asyncio
from unittest.mock import MagicMock, AsyncMock

                                                                         
os.environ['USE_NEW_HANDLERS'] = 'true'

def test_callback_registration():
    """Тест что callback обработчики регистрируются правильно."""
    try:
        from aiogram import Dispatcher
        from handlers import CallbackHandler

                                 
        dp = MagicMock(spec=Dispatcher)
        dp.callback_query = MagicMock()

                            
        handler = CallbackHandler()

                      
        handler.register(dp)

                                                    
        assert dp.callback_query.register.called, "callback_query.register was not called"

                                                   
        call_count = dp.callback_query.register.call_count
        print(f"✅ callback_query.register was called {call_count} times")

                                                 
        calls = dp.callback_query.register.call_args_list
        for i, call in enumerate(calls):
            handler_func = call[0][0]                                        
            print(f"✅ Handler {i+1}: {handler_func.__name__}")

                                                                                              
        return
    except Exception as e:
        print(f"❌ Callback registration test failed: {e}")
        import traceback
        traceback.print_exc()
                                                                              
        raise

async def test_callback_execution():
    """Тест выполнения callback обработчика."""
    try:
        from handlers import CallbackHandler
        from aiogram.types import CallbackQuery

        handler = CallbackHandler()

                             
        mock_cq = MagicMock(spec=CallbackQuery)
        mock_cq.data = "lang:ru"
        mock_cq.from_user = MagicMock()
        mock_cq.from_user.id = 12345
        mock_cq.answer = AsyncMock()
        mock_cq.message = MagicMock()
        mock_cq.message.edit_text = AsyncMock()

                  
        mock_bot = MagicMock()
        handler._bot = mock_bot

                              
        await handler.handle_main_callback(mock_cq)

                                         
        mock_cq.answer.assert_called()
        print("✅ Callback execution works")

        return
    except Exception as e:
        print(f"❌ Callback execution test failed: {e}")
                                            
        raise

def main():
    """Запуск тестов."""
    print("🧪 Testing callback handler registration...")
    print("=" * 60)

    results = []

                      
    try:
        test_callback_registration()
        results.append(True)
    except Exception:
        results.append(False)

                     
    try:
        asyncio.run(test_callback_execution())
        results.append(True)
        print("✅ Callback execution test passed")
    except Exception as e:
        print(f"❌ Callback execution test failed: {e}")
        results.append(False)

    print("=" * 60)

    passed = sum(results)
    total = len(results)

    if passed == total:
        print(f"🎉 All callback tests passed! ({passed}/{total})")
        print("✅ Callback handlers are registered and working!")
        return 0
    else:
        print(f"⚠️  Some callback tests failed: {passed}/{total}")
        return 1

if __name__ == "__main__":
    sys.exit(main())












