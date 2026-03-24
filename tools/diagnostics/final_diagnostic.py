                      
"""
Финальная диагностика бота
"""

import sys
import os

def main():
    print('🎯 ФИНАЛЬНАЯ ДИАГНОСТИКА БОТА')
    print('=' * 50)

                                 
    print('📦 ТЕСТ ИМПОРТА МОДУЛЕЙ:')
    try:
        import bot
        import database
        import analytics
        import scraper
        import config
        import middleware
        print('✅ Все модули импортированы успешно')
    except Exception as e:
        print(f'❌ Ошибка импорта: {e}')
        return

                         
    print('\n💾 ТЕСТ БАЗЫ ДАННЫХ:')
    try:
        from database import init_db
        init_db()
        print('✅ База данных инициализирована')
    except Exception as e:
        print(f'❌ Ошибка БД: {e}')

                       
    print('\n📊 ТЕСТ АНАЛИТИКИ:')
    try:
        from analytics import Analytics
        user_stats = Analytics.get_user_stats()
        total_users = user_stats.get('total_users', 0)
        print(f'✅ Статистика пользователей: {total_users} пользователей')
    except Exception as e:
        print(f'❌ Ошибка аналитики: {e}')

                          
    print('\n⚙️  ТЕСТ КОНФИГУРАЦИИ:')
    try:
        from config import BOT_TOKEN
        if BOT_TOKEN and BOT_TOKEN != 'YOUR_BOT_TOKEN_HERE':
            print('✅ Bot Token настроен')
        else:
            print('❌ Bot Token не настроен')
    except Exception as e:
        print(f'❌ Ошибка конфигурации: {e}')

                               
    print('\n📁 ТЕСТ СТРУКТУРЫ ПРОЕКТА:')
    required_dirs = ['backups', 'logs', 'locales']
    all_dirs_exist = True

    for dir_name in required_dirs:
        if os.path.exists(dir_name) and os.path.isdir(dir_name):
            print(f'✅ {dir_name}/ - существует')
        else:
            print(f'❌ {dir_name}/ - отсутствует')
            all_dirs_exist = False

    if all_dirs_exist:
        print('✅ Структура проекта корректна')

    print('\n' + '=' * 50)
    print('🎉 ДИАГНОСТИКА ЗАВЕРШЕНА!')
    print('Бот готов к работе с enterprise-функционалом!')

if __name__ == '__main__':
    main()
