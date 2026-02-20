#!/usr/bin/env python3
"""
Тест запуска бота для диагностики проблем.
"""
import asyncio
import sys
import os

async def test_bot_start():
    """Тестируем запуск бота без polling."""
    try:
        print("🔍 Testing bot startup...")

        # Импортируем основные компоненты
        from config import BOT_TOKEN, _check_bot_token, USE_NEW_HANDLERS
        print(f"✅ Config loaded: USE_NEW_HANDLERS={USE_NEW_HANDLERS}")

        from aiogram import Bot, Dispatcher
        bot = Bot(token=BOT_TOKEN)
        dp = Dispatcher()
        print("✅ Bot and Dispatcher created")

        # Проверяем регистрацию обработчиков
        from middleware import AntiSpamMiddleware
        dp.message.middleware(AntiSpamMiddleware())
        dp.callback_query.middleware(AntiSpamMiddleware())
        print("✅ Middleware registered")

        # Проверяем регистрацию хендлеров
        use_new_handlers = USE_NEW_HANDLERS
        if use_new_handlers:
            print("🔄 Testing new handlers registration...")
            try:
                from handlers import BasicHandler, SubscriptionHandler
                basic_handler = BasicHandler()
                basic_handler.register(dp)
                print("✅ BasicHandler registered")

                subscription_handler = SubscriptionHandler()
                subscription_handler.register(dp)
                print("✅ SubscriptionHandler registered")
            except Exception as e:
                print(f"❌ New handlers failed: {e}")
                use_new_handlers = False

        if not use_new_handlers:
            print("🔄 Testing old handlers registration...")
            # Регистрируем старые обработчики
            from bot import cmd_start_old, cmd_help_old, cmd_mysubs_cmd_old, cmd_unsubscribe_old, handle_url_old
            from aiogram.filters import Command

            dp.message.register(cmd_start_old, Command("start"))
            dp.message.register(cmd_help_old, Command("help"))
            dp.message.register(cmd_mysubs_cmd_old, Command("mysubs"))
            dp.message.register(cmd_unsubscribe_old, Command("unsubscribe"))
            dp.message.register(handle_url_old, lambda m: m.text and ('trendyol.com' in (m.text or '').lower() or 'ty.gl/' in (m.text or '').lower()))
            print("✅ Old handlers registered")

        # Проверяем webhook deletion
        try:
            await bot.delete_webhook(drop_pending_updates=True)
            print("✅ Webhook deleted")
        except Exception as e:
            print(f"⚠️  Webhook deletion failed (may be OK): {e}")

        print("🎉 Bot startup test completed successfully!")
        return True

    except Exception as e:
        print(f"❌ Bot startup test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(test_bot_start())
    sys.exit(0 if success else 1)












