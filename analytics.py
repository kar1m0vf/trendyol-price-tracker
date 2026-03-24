"""
Аналитика и статистика для телеграм бота
"""

import sqlite3
import time
import logging
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timedelta
from collections import defaultdict

from database import DB, get_connection

logger = logging.getLogger('analytics')

class Analytics:
    """Класс для сбора и анализа статистики бота"""

    @staticmethod
    def get_user_stats() -> Dict:
        """Получить статистику пользователей"""
        with get_connection() as conn:
            cur = conn.cursor()

                                               
            cur.execute("PRAGMA table_info(users)")
            columns = cur.fetchall()
            column_names = [col[1] for col in columns]
            has_created_at = 'created_at' in column_names

                                            
            cur.execute("SELECT COUNT(*) FROM users")
            total_users = cur.fetchone()[0]

                                                  
            cur.execute("SELECT COUNT(DISTINCT user_id) FROM subscriptions")
            active_users = cur.fetchone()[0]

                                                    
            new_users_week = 0
            if has_created_at:
                week_ago = int(time.time()) - 7*24*3600
                cur.execute("SELECT COUNT(*) FROM users WHERE created_at > ?", (week_ago,))
                new_users_week = cur.fetchone()[0]

                                     
            cur.execute("SELECT language, COUNT(*) FROM users GROUP BY language")
            language_stats = dict(cur.fetchall())

            return {
                'total_users': total_users,
                'active_users': active_users,
                'inactive_users': total_users - active_users,
                'new_users_week': new_users_week,
                'language_distribution': language_stats
            }

    @staticmethod
    def get_subscription_stats() -> Dict:
        """Получить статистику подписок"""
        with get_connection() as conn:
            cur = conn.cursor()

                                       
            cur.execute("SELECT COUNT(*) FROM subscriptions")
            total_subs = cur.fetchone()[0]

                                                  
            cur.execute("SELECT notify_mode, COUNT(*) FROM subscriptions GROUP BY notify_mode")
            mode_stats = dict(cur.fetchall())

                                                         
            avg_subs_per_user = total_subs / max(Analytics.get_user_stats()['active_users'], 1)

                                                         
            cur.execute("SELECT COUNT(*) FROM subscriptions WHERE price_alert IS NOT NULL")
            subs_with_alerts = cur.fetchone()[0]

                                        
            cur.execute("SELECT COUNT(*) FROM subscriptions WHERE min_price IS NOT NULL OR max_price IS NOT NULL")
            subs_with_ranges = cur.fetchone()[0]

                                        
            cur.execute("""
                SELECT
                    CASE
                        WHEN url LIKE '%trendyol.com%' THEN 'Trendyol'
                        ELSE 'Other'
                    END as domain,
                    COUNT(*) as count
                FROM subscriptions
                GROUP BY domain
                ORDER BY count DESC
                LIMIT 10
            """)
            domain_stats = dict(cur.fetchall())

            return {
                'total_subscriptions': total_subs,
                'mode_distribution': mode_stats,
                'avg_subs_per_user': avg_subs_per_user,
                'subs_with_price_alerts': subs_with_alerts,
                'subs_with_price_ranges': subs_with_ranges,
                'domain_distribution': domain_stats
            }

    @staticmethod
    def get_price_history_stats(days: int = 30) -> Dict:
        """Получить статистику истории цен"""
        with get_connection() as conn:
            cur = conn.cursor()

            since_time = int(time.time()) - days * 24 * 3600

                                         
            cur.execute("SELECT COUNT(*) FROM price_history WHERE ts > ?", (since_time,))
            total_points = cur.fetchone()[0]

                                                  
            cur.execute("""
                SELECT AVG(point_count) FROM (
                    SELECT COUNT(*) as point_count
                    FROM price_history
                    WHERE ts > ?
                    GROUP BY subscription_id
                )
            """, (since_time,))
            avg_points_per_sub = cur.fetchone()[0] or 0

                                         
            cur.execute("SELECT source, COUNT(*) FROM price_history WHERE ts > ? GROUP BY source", (since_time,))
            source_stats = dict(cur.fetchall())

                                                                              
            cur.execute("""
                SELECT
                    COUNT(CASE WHEN ph1.price < ph2.price THEN 1 END) as price_drops,
                    COUNT(CASE WHEN ph1.price > ph2.price THEN 1 END) as price_increases,
                    COUNT(*) as total_changes
                FROM price_history ph1
                JOIN price_history ph2 ON ph1.subscription_id = ph2.subscription_id
                    AND ph1.ts > ph2.ts
                    AND ph1.ts = (
                        SELECT MIN(ts) FROM price_history
                        WHERE subscription_id = ph1.subscription_id AND ts > ph2.ts
                    )
                WHERE ph1.ts > ?
            """, (since_time,))
            changes = cur.fetchone()
            price_drops, price_increases, total_changes = changes if changes else (0, 0, 0)

                                                         
            cur.execute("""
                SELECT
                    s.id,
                    s.url,
                    ph_current.price as current_price,
                    ph_prev.price as previous_price,
                    ((ph_prev.price - ph_current.price) / ph_prev.price * 100) as drop_percent
                FROM subscriptions s
                JOIN price_history ph_current ON s.id = ph_current.subscription_id
                JOIN price_history ph_prev ON s.id = ph_prev.subscription_id
                    AND ph_prev.ts = (
                        SELECT MAX(ts) FROM price_history
                        WHERE subscription_id = s.id AND ts < ph_current.ts
                    )
                WHERE ph_current.ts > ?
                    AND ph_prev.price > ph_current.price
                ORDER BY drop_percent DESC
                LIMIT 10
            """, (since_time,))
            top_drops = cur.fetchall()

            return {
                'total_price_points': total_points,
                'avg_points_per_subscription': avg_points_per_sub,
                'source_distribution': source_stats,
                'price_changes': {
                    'drops': price_drops,
                    'increases': price_increases,
                    'total': total_changes
                },
                'top_price_drops': top_drops[:5]         
            }

    @staticmethod
    def get_performance_stats(hours: int = 24) -> Dict:
        """Получить статистику производительности"""
        with get_connection() as conn:
            cur = conn.cursor()

            since_time = int(time.time()) - hours * 3600

                                    
            cur.execute("SELECT COUNT(*) FROM subscriptions WHERE last_notify_time > ?", (since_time,))
            notifications_sent = cur.fetchone()[0]

                                                                                         
            cur.execute("""
                SELECT
                    COUNT(DISTINCT ph.subscription_id) as successful_parses,
                    COUNT(DISTINCT s.id) as total_subs
                FROM subscriptions s
                LEFT JOIN price_history ph ON s.id = ph.subscription_id AND ph.ts > ?
            """, (since_time,))

            parse_stats = cur.fetchone()
            successful_parses, total_subs = parse_stats if parse_stats else (0, 0)
            parse_success_rate = (successful_parses / max(total_subs, 1)) * 100

            return {
                'notifications_sent': notifications_sent,
                'parse_success_rate': parse_success_rate,
                'successful_parses': successful_parses,
                'total_subscriptions_checked': total_subs
            }

    @staticmethod
    def get_health_metrics() -> Dict:
        """Получить метрики здоровья системы"""
        try:
            import psutil
            import os

                    
            memory = psutil.virtual_memory()
            memory_usage = memory.percent

                  
            disk = psutil.disk_usage('/')
            disk_usage = disk.percent

                 
            cpu_usage = psutil.cpu_percent(interval=1)

                         
            db_size = os.path.getsize(DB) if os.path.exists(DB) else 0
            db_size_mb = db_size / (1024 * 1024)

            return {
                'memory_usage_percent': memory_usage,
                'disk_usage_percent': disk_usage,
                'cpu_usage_percent': cpu_usage,
                'database_size_mb': db_size_mb
            }
        except Exception as e:
            logger.exception("Error getting health metrics: %s", e)
            return {
                'memory_usage_percent': 0,
                'disk_usage_percent': 0,
                'cpu_usage_percent': 0,
                'database_size_mb': 0
            }

    @staticmethod
    def get_full_report() -> str:
        """Получить полный отчет по статистике"""
        try:
            user_stats = Analytics.get_user_stats()
            sub_stats = Analytics.get_subscription_stats()
            price_stats = Analytics.get_price_history_stats()
            perf_stats = Analytics.get_performance_stats()
            health_stats = Analytics.get_health_metrics()

            report = f"""
📊 <b>ПОЛНЫЙ ОТЧЕТ ПО СТАТИСТИКЕ БОТА</b>

👥 <b>ПОЛЬЗОВАТЕЛИ</b>
• Всего: {user_stats['total_users']}
• Активных: {user_stats['active_users']} ({user_stats['active_users']/max(user_stats['total_users'],1)*100:.1f}%)
• Новых за неделю: {user_stats['new_users_week']}

🌐 <b>ЯЗЫКИ</b>
"""

            for lang, count in user_stats['language_distribution'].items():
                report += f"• {lang.upper()}: {count}\n"

            report += f"""
📦 <b>ПОДПИСКИ</b>
• Всего: {sub_stats['total_subscriptions']}
• Среднее на пользователя: {sub_stats['avg_subs_per_user']:.1f}
• С ценовыми алертами: {sub_stats['subs_with_price_alerts']}
• С диапазонами цен: {sub_stats['subs_with_price_ranges']}

🔔 <b>РЕЖИМЫ УВЕДОМЛЕНИЙ</b>
"""
            for mode, count in sub_stats['mode_distribution'].items():
                report += f"• {mode}: {count}\n"

            report += f"""
💰 <b>ИСТОРИЯ ЦЕН (30 дней)</b>
• Точек цены: {price_stats['total_price_points']}
• Среднее на подписку: {price_stats['avg_points_per_subscription']:.1f}
• Изменения цен: {price_stats['price_changes']['total']}
  • Падения: {price_stats['price_changes']['drops']}
  • Рост: {price_stats['price_changes']['increases']}

⚡ <b>ПРОИЗВОДИТЕЛЬНОСТЬ (24ч)</b>
• Уведомлений отправлено: {perf_stats['notifications_sent']}
• Успешность парсинга: {perf_stats['parse_success_rate']:.1f}%

🖥️ <b>СИСТЕМА</b>
• CPU: {health_stats['cpu_usage_percent']:.1f}%
• Память: {health_stats['memory_usage_percent']:.1f}%
• Диск: {health_stats['disk_usage_percent']:.1f}%
• БД: {health_stats['database_size_mb']:.1f} MB
"""

            return report

        except Exception as e:
            logger.exception("Error generating full report: %s", e)
            return "❌ Ошибка при генерации отчета"
