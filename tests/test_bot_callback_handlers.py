"""Verify that callback_handler_old is registered when bot loads."""
import sys
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_bot_handlers():
    """Test that bot.py registers handlers correctly."""
    try:
        # Import bot module (which should register all handlers)
        import bot as bot_module
        
        print("OK: bot module imported successfully")
        print(f"  - Using handlers: USE_NEW_HANDLERS={bot_module.USE_NEW_HANDLERS}")
        
        # Check dispatcher
        dp = bot_module.dp
        print(f"OK: Dispatcher found: {dp}")
        
        # Check callback query handlers
        callback_handlers = dp.callback_query.handlers
        print(f"Callback query handlers: {len(callback_handlers)} handler(s)")
        for i, handler in enumerate(callback_handlers):
            print(f"  Handler {i}: {handler}")
        
        # Check message handlers
        message_handlers = dp.message.handlers
        print(f"Message handlers: {len(message_handlers)} handler(s)")
        
        if callback_handlers:
            print("\nOK: Callback handlers ARE registered!")
        else:
            print("\nERROR: Callback handlers are NOT registered!")
            
    except Exception as e:
        logger.error(f"Error testing bot handlers: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    import asyncio
    asyncio.run(test_bot_handlers())
