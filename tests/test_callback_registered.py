"""Test that callback handlers are registered correctly."""
import asyncio
from aiogram import Dispatcher
from aiogram.types import CallbackQuery, User, Message, Chat


async def test_callback_registration():
    """Test that callback handlers are registered."""
    dp = Dispatcher()
    
                                             
    async def test_handler(cq: CallbackQuery):
        print(f"✅ Handler called with data: {cq.data}")
    
                          
    dp.callback_query.register(test_handler)
    
                                
    print(f"Callback query middleware: {dp.callback_query}")
    print(f"Callback query handlers: {dp.callback_query.handlers}")
    
                          
    handlers = dp.callback_query.handlers
    if handlers:
        print(f"✅ Found {len(handlers)} handler(s) for callback_query")
        for handler in handlers:
            print(f"  - Handler: {handler}")
    else:
        print("❌ No handlers found for callback_query")
    
    print("\n✅ Callback registration test completed!")


if __name__ == "__main__":
    asyncio.run(test_callback_registration())
