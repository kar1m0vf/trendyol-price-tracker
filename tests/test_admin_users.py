import asyncio
import sys
sys.path.append('.')

async def test_admin_users():
    print('Тест команды /admin users')
    try:
        from unittest.mock import MagicMock, AsyncMock
        from bot import admin_users

        message = MagicMock()
        message.from_user.id = 975282591
        message.text = '/admin users'
        message.answer = AsyncMock()

        await admin_users(message)

        if message.answer.called:
            print('✅ Команда выполнена успешно!')
            call_args = message.answer.call_args
            if call_args:
                text = call_args[0][0] if call_args[0] else ''
                if 'error' in text.lower() or 'ошибка' in text.lower():
                    print('❌ Есть ошибка:', text[:100])
                else:
                    print('✅ Ошибок нет!')
        else:
            print('❌ Ответ не отправлен')

    except Exception as e:
        print('❌ Ошибка:', str(e))

if __name__ == '__main__':
    asyncio.run(test_admin_users())
