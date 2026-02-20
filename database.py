import sqlite3
import time
import logging
import threading
from typing import List, Tuple, Optional, Dict, Any
from datetime import datetime

# Настройка логирования
logger = logging.getLogger('database')

DB = "trendyol_bot.db"

# Connection pooling for better performance
_connection_pool = {}
_pool_lock = threading.Lock()
_current_db = None

def get_connection():
    """Get database connection from pool or create new one"""
    thread_id = threading.get_ident()
    global _current_db
    # If DB path changed (tests may monkeypatch `database.DB`), reset pool
    if _current_db != DB:
        with _pool_lock:
            for conn in _connection_pool.values():
                try:
                    conn.close()
                except Exception:
                    pass
            _connection_pool.clear()
            _current_db = DB
    with _pool_lock:
        if thread_id not in _connection_pool:
            _connection_pool[thread_id] = sqlite3.connect(DB, timeout=30.0, check_same_thread=False)
            _connection_pool[thread_id].execute("PRAGMA journal_mode=WAL")
            _connection_pool[thread_id].execute("PRAGMA synchronous=NORMAL")
            _connection_pool[thread_id].execute("PRAGMA cache_size=10000")
            _connection_pool[thread_id].execute("PRAGMA temp_store=MEMORY")
        return _connection_pool[thread_id]

def close_all_connections():
    """Close all connections in the pool"""
    with _pool_lock:
        for conn in _connection_pool.values():
            try:
                conn.close()
            except Exception:
                pass
        _connection_pool.clear()

# Context manager for database operations with connection pooling
class DatabaseConnection:
    """Context manager for database operations using connection pooling"""
    def __enter__(self):
        self.conn = get_connection()
        return self.conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Connection stays in pool, just commit if needed
        if exc_type is None:
            self.conn.commit()
        else:
            self.conn.rollback()

def execute_batch(queries: List[Tuple[str, Tuple]], commit_every: int = 100):
    """Execute batch of queries with periodic commits for performance"""
    with DatabaseConnection() as conn:
        cur = conn.cursor()
        for i, (query, params) in enumerate(queries):
            cur.execute(query, params)
            if (i + 1) % commit_every == 0:
                conn.commit()
        conn.commit()

def save_price_points_batch(price_points: List[Tuple[int, float, int, str]]):
    """
    Batch save multiple price points efficiently.
    Format: [(subscription_id, price, timestamp, url), ...]
    """
    if not price_points:
        return

    queries = []
    current_time = int(time.time())

    for sub_id, price, ts, url in price_points:
        if ts is None:
            ts = current_time
        queries.append((
            """
            INSERT INTO price_history (subscription_id, price, ts, url, source)
            VALUES (?, ?, ?, ?, 'batch')
            """,
            (sub_id, price, ts, url)
        ))

    execute_batch(queries, commit_every=50)

def init_db():
    # Проверяем существующую схему и добавляем недостающие колонки
    with sqlite3.connect(DB) as conn:
        cur = conn.cursor()
        # Удалим возможные старые триггеры, оставшиеся в файле БД.
        # Эти триггеры могли быть созданы предыдущими версиями кода и могут
        # нежелательно модифицировать/удалять записи при UPDATE.
        try:
            cur.execute("DROP TRIGGER IF EXISTS update_subscription_timestamp")
            cur.execute("DROP TRIGGER IF EXISTS cleanup_old_subscriptions")
        except Exception:
            # если триггер отсутствует или база несовместима — продолжим
            logger.debug("No legacy triggers to drop or error during drop", exc_info=True)
        
        # Получаем список существующих колонок в таблице subscriptions
        try:
            cur.execute("SELECT * FROM subscriptions LIMIT 0")
            columns = [description[0] for description in cur.description]
        except sqlite3.OperationalError:
            columns = []
            
        # Добавляем недостающие колонки если таблица существует
        if columns:
            current_time = int(time.time())
            
            # Проверяем и добавляем каждую недостающую колонку
            missing_columns = {
                'updated_at': f"ALTER TABLE subscriptions ADD COLUMN updated_at INTEGER DEFAULT {current_time}",
                'created_at': f"ALTER TABLE subscriptions ADD COLUMN created_at INTEGER DEFAULT {current_time}",
                'product_title': "ALTER TABLE subscriptions ADD COLUMN product_title TEXT",
                'product_image': "ALTER TABLE subscriptions ADD COLUMN product_image TEXT",
                'min_price': "ALTER TABLE subscriptions ADD COLUMN min_price REAL",
                'max_price': "ALTER TABLE subscriptions ADD COLUMN max_price REAL", 
                'notify_percent': "ALTER TABLE subscriptions ADD COLUMN notify_percent REAL",
                'notify_interval': "ALTER TABLE subscriptions ADD COLUMN notify_interval INTEGER DEFAULT 60",
                'last_notify_time': "ALTER TABLE subscriptions ADD COLUMN last_notify_time INTEGER"
            }
            
            for col_name, alter_sql in missing_columns.items():
                if col_name not in columns:
                    try:
                        cur.execute(alter_sql)
                        logger.info(f"Added missing column: {col_name}")
                    except sqlite3.OperationalError as e:
                        logger.warning(f"Could not add column {col_name}: {e}")
            
            conn.commit()
        # Также проверим таблицу users на наличие колонок для тихих часов
        try:
            cur.execute("SELECT * FROM users LIMIT 0")
            user_columns = [description[0] for description in cur.description]
        except sqlite3.OperationalError:
            user_columns = []

        if user_columns:
            user_missing = {
                'notify_quiet_hours_start': "ALTER TABLE users ADD COLUMN notify_quiet_hours_start INTEGER DEFAULT 23",
                'notify_quiet_hours_end': "ALTER TABLE users ADD COLUMN notify_quiet_hours_end INTEGER DEFAULT 7"
            }
            for col_name, alter_sql in user_missing.items():
                if col_name not in user_columns:
                    try:
                        cur.execute(alter_sql)
                        logger.info(f"Added missing user column: {col_name}")
                    except sqlite3.OperationalError as e:
                        logger.warning(f"Could not add user column {col_name}: {e}")
            conn.commit()
    
    # Выполняем операции обслуживания базы данных
    with sqlite3.connect(DB) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")  # Временно отключаем для обслуживания
        conn.execute("VACUUM")  # Оптимизируем размер файла БД
        conn.execute("ANALYZE")  # Обновляем статистику для оптимизатора запросов
        
    # Теперь настраиваем основную конфигурацию
    with sqlite3.connect(DB) as conn:
        # Включаем поддержку внешних ключей
        conn.execute("PRAGMA foreign_keys = ON")
        
        # Оптимизация производительности
        conn.execute("PRAGMA journal_mode = WAL")  # Write-Ahead Logging
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA cache_size = -20000")  # Увеличиваем кэш (в килобайтах)
        conn.execute("PRAGMA temp_store = MEMORY")
        conn.execute("PRAGMA mmap_size = 30000000000")  # Используем memory-mapped I/O
        conn.execute("PRAGMA page_size = 4096")  # Оптимальный размер страницы
        
        cur = conn.cursor()
        
        # Создаем таблицы, если их нет
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            language TEXT DEFAULT 'ru',
            notify_quiet_hours_start INTEGER DEFAULT 23,
            notify_quiet_hours_end INTEGER DEFAULT 7,
            created_at INTEGER DEFAULT (strftime('%s', 'now'))
        )
        """)
        
        cur.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            url TEXT NOT NULL,
            product_title TEXT,
            product_image TEXT,
            notify_mode TEXT NOT NULL DEFAULT 'discount',
            last_price REAL,
            min_price REAL,
            max_price REAL,
            notify_percent REAL,
            notify_interval INTEGER DEFAULT 60,
            last_notify_time INTEGER,
            created_at INTEGER DEFAULT (CAST(strftime('%s', 'now') AS INTEGER)),
            updated_at INTEGER DEFAULT (CAST(strftime('%s', 'now') AS INTEGER)),
            FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
        )
        """)
        
        # Создаем оптимизированные индексы с учетом частых запросов
        # Основной индекс для поиска подписок пользователя с учетом сортировки
        cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_subscriptions_user_compound ON subscriptions(user_id, updated_at DESC)
        """)
        
        # Индекс для URL с учетом режима уведомлений
        cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_subscriptions_url_mode ON subscriptions(url, notify_mode)
        """)
        
        # Индекс для оптимизации выборки по времени уведомления
        cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_subscriptions_notify_time ON subscriptions(last_notify_time, notify_interval)
        """)
        
        # Индекс для языковых настроек пользователей
        cur.execute("CREATE INDEX IF NOT EXISTS idx_users_language ON users(language)")
        
        # NOTE: triggers that modify or delete rows on UPDATE caused
        # accidental deletions when business logic updated a subscription.
        # We'll avoid triggers that perform UPDATE/DELETE and instead update
        # `updated_at` from application code to keep behavior explicit and safe.
        conn.commit()
        
        # Подсказка оптимизатору по типичным размерам таблиц
        cur.execute("ANALYZE subscriptions")
        cur.execute("ANALYZE users")
        # Price history table to store collected price points for subscriptions
        cur.execute("""
        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subscription_id INTEGER NOT NULL,
            url TEXT NOT NULL,
            price REAL NOT NULL,
            ts INTEGER DEFAULT (CAST(strftime('%s', 'now') AS INTEGER)),
            source TEXT DEFAULT 'collector',
            FOREIGN KEY (subscription_id) REFERENCES subscriptions (id) ON DELETE CASCADE
        )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_price_history_sub_ts ON price_history(subscription_id, ts DESC)")
        # НОВЫЙ ИНДЕКС: для быстрого поиска по URL
        cur.execute("CREATE INDEX IF NOT EXISTS idx_price_history_url_ts ON price_history(url, ts DESC)")
        cur.execute("ANALYZE price_history")
        
        # Миграция: добавляем поле price_alert для отслеживания целевой цены
        try:
            cur.execute("ALTER TABLE subscriptions ADD COLUMN price_alert REAL")
            logger.info("Migration: Added price_alert column to subscriptions table")
        except sqlite3.OperationalError:
            pass  # Column already exists
        # Миграция: добавляем поле tags (комма-разделённый список меток)
        try:
            cur.execute("ALTER TABLE subscriptions ADD COLUMN tags TEXT")
            logger.info("Migration: Added tags column to subscriptions table")
        except sqlite3.OperationalError:
            pass  # Column already exists

        # Создаем таблицу рекомендуемых продуктов
        cur.execute("""
        CREATE TABLE IF NOT EXISTS recommended_products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            url TEXT NOT NULL UNIQUE,
            price TEXT,
            category TEXT,
            brand TEXT,
            reason_template TEXT,
            priority INTEGER DEFAULT 0,
            is_active BOOLEAN DEFAULT 1,
            created_at INTEGER DEFAULT (strftime('%s', 'now')),
            updated_at INTEGER DEFAULT (strftime('%s', 'now'))
        )
        """)

        # Глобальные тексты/настройки бота (например, текст рекомендаций)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS bot_texts (
            key TEXT NOT NULL,
            language TEXT NOT NULL DEFAULT '*',
            value TEXT NOT NULL,
            updated_at INTEGER DEFAULT (strftime('%s', 'now')),
            PRIMARY KEY (key, language)
        )
        """)

        # Дополнительные индексы для оптимизации производительности
        try:
            # Проверяем существующие индексы и создаем недостающие
            existing_indexes = set()
            cur.execute("SELECT name FROM sqlite_master WHERE type='index'")
            existing_indexes = {row[0] for row in cur.fetchall()}

            indexes_to_create = [
                ("idx_users_language", "CREATE INDEX idx_users_language ON users(language)"),
                ("idx_subscriptions_user_id", "CREATE INDEX idx_subscriptions_user_id ON subscriptions(user_id)"),
                ("idx_subscriptions_url", "CREATE INDEX idx_subscriptions_url ON subscriptions(url)"),
                ("idx_subscriptions_mode", "CREATE INDEX idx_subscriptions_mode ON subscriptions(notify_mode)"),
                ("idx_subscriptions_notify_time", "CREATE INDEX idx_subscriptions_notify_time ON subscriptions(last_notify_time)"),
                ("idx_subscriptions_url_mode", "CREATE INDEX idx_subscriptions_url_mode ON subscriptions(url, notify_mode)"),
                ("idx_price_history_ts", "CREATE INDEX idx_price_history_ts ON price_history(ts DESC)"),
                ("idx_price_history_source", "CREATE INDEX idx_price_history_source ON price_history(source)"),
            ]

            for index_name, create_sql in indexes_to_create:
                if index_name not in existing_indexes:
                    try:
                        cur.execute(create_sql)
                        logger.debug(f"Created index: {index_name}")
                    except Exception as idx_e:
                        logger.warning(f"Could not create index {index_name}: {idx_e}")

            logger.info("Database indexes verified/created")
        except Exception as e:
            logger.warning(f"Error managing indexes: {e}")

        conn.commit()
        logger.info("Database initialized with optimizations")

def add_user_if_not_exists(user_id: int, language: str = "ru") -> None:
    with DatabaseConnection() as conn:
        cur = conn.cursor()
        cur.execute("INSERT OR IGNORE INTO users (user_id, language) VALUES (?, ?)", (user_id, language))

def set_user_language(user_id: int, language: str) -> None:
    with DatabaseConnection() as conn:
        cur = conn.cursor()
        # IMPORTANT: avoid INSERT OR REPLACE because REPLACE deletes and recreates
        # the row, which resets other user settings (quiet hours, created_at, etc.).
        cur.execute("INSERT OR IGNORE INTO users (user_id, language) VALUES (?, ?)", (user_id, language))
        cur.execute("UPDATE users SET language = ? WHERE user_id = ?", (language, user_id))

def get_user_language(user_id: int) -> str:
    with DatabaseConnection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT language FROM users WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
    return row[0] if row else "en"

def add_subscription(
    user_id: int, 
    url: str, 
    mode: str = "discount", 
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    notify_percent: Optional[float] = None,
    notify_interval: int = 60,
    product_title: Optional[str] = None,
    product_image: Optional[str] = None
) -> int:
    """
    Добавляет новую подписку с расширенными параметрами.
    Возвращает ID новой подписки.
    """
    with DatabaseConnection() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO subscriptions (
                user_id, url, product_title, product_image, notify_mode, min_price, max_price, 
                notify_percent, notify_interval
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, url, product_title, product_image, mode, min_price, max_price, notify_percent, notify_interval))
        sub_id = cur.lastrowid
    return sub_id


def add_price_point(subscription_id: int, url: str, price: float, ts: int = None, source: str = 'collector') -> int:
    """Insert a price point for a subscription. Returns inserted id."""
    if ts is None:
        ts = int(time.time())
    with DatabaseConnection() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO price_history (subscription_id, url, price, ts, source) VALUES (?, ?, ?, ?, ?)",
                    (subscription_id, url, price, ts, source))
        return cur.lastrowid


def get_price_history(subscription_id: int, limit: int = 500, since_ts: int = None):
    """Return list of (ts, price) ordered ascending by ts (oldest first).
    If since_ts provided, only points with ts >= since_ts are returned.
    """
    with DatabaseConnection() as conn:
        cur = conn.cursor()
        if since_ts:
            cur.execute("SELECT ts, price FROM price_history WHERE subscription_id = ? AND ts >= ? ORDER BY ts ASC LIMIT ?",
                        (subscription_id, since_ts, limit))
        else:
            cur.execute("SELECT ts, price FROM price_history WHERE subscription_id = ? ORDER BY ts ASC LIMIT ?",
                        (subscription_id, limit))
        rows = cur.fetchall()
    return rows


def get_last_price_point(subscription_id: int):
    """Return (ts, price) for last stored point or None."""
    with DatabaseConnection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT ts, price FROM price_history WHERE subscription_id = ? ORDER BY ts DESC LIMIT 1", (subscription_id,))
        row = cur.fetchone()
    return row


def delete_price_history_for_subscription(subscription_id: int) -> int:
    """Delete history for a given subscription. Returns deleted count."""
    with DatabaseConnection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM price_history WHERE subscription_id = ?", (subscription_id,))
        cnt = cur.rowcount
    return cnt




def update_subscription_meta(sub_id: int, title: Optional[str], image: Optional[str]) -> None:
    """Обновляет кэш названия и изображения подписки."""
    with sqlite3.connect(DB) as conn:
        cur = conn.cursor()
        cur.execute("UPDATE subscriptions SET product_title = ?, product_image = ?, updated_at = ? WHERE id = ?",
                    (title, image, int(time.time()), sub_id))
        conn.commit()

def remove_subscription(sub_id: int) -> bool:
    """
    Удаляет подписку по ID.
    Возвращает True если подписка была удалена.
    """
    try:
        with sqlite3.connect(DB) as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM subscriptions WHERE id = ?", (sub_id,))
            deleted = cur.rowcount
            conn.commit()
            if deleted:
                logger.info("Removed subscription id=%s", sub_id)
            else:
                logger.debug("No subscription removed for id=%s (not found)", sub_id)
            return deleted > 0
    except sqlite3.Error as e:
        logger.exception("Error removing subscription %s: %s", sub_id, e)
        return False

def remove_subscriptions_by_user(user_id: int) -> int:
    """
    Удаляет все подписки пользователя.
    Возвращает количество удаленных подписок.
    """
    try:
        with sqlite3.connect(DB) as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM subscriptions WHERE user_id = ?", (user_id,))
            deleted_count = cur.rowcount
            conn.commit()
            logger.info("Removed %d subscription(s) for user=%s", deleted_count, user_id)
            return deleted_count
    except sqlite3.Error as e:
        logger.exception("Error removing subscriptions for user %s: %s", user_id, e)
        return 0

def get_user_subscriptions(user_id: int) -> List[Tuple]:
    """Returns rows in canonical order:
    (id, user_id, url, notify_mode, last_price, product_title, product_image,
     min_price, max_price, notify_percent, notify_interval, last_notify_time, price_alert, tags)
    """
    with DatabaseConnection() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, user_id, url, notify_mode, last_price, product_title, product_image,
                   min_price, max_price, notify_percent, notify_interval, last_notify_time, price_alert, tags
            FROM subscriptions
            WHERE user_id = ?
            ORDER BY updated_at DESC
        """, (user_id,))
        rows = cur.fetchall()
    return rows

def set_subscription_tags(sub_id: int, tags: List[str]) -> bool:
    """Set comma-separated tags for a subscription. Tags should be list of strings."""
    try:
        tags_clean = ",".join([t.strip() for t in tags if t and t.strip()])
        with sqlite3.connect(DB) as conn:
            cur = conn.cursor()
            cur.execute("UPDATE subscriptions SET tags = ? WHERE id = ?", (tags_clean, sub_id))
            conn.commit()
            return cur.rowcount > 0
    except Exception as e:
        logger.exception("Error setting tags for sub %s: %s", sub_id, e)
        return False


def get_subscription_tags(sub_id: int) -> List[str]:
    with sqlite3.connect(DB) as conn:
        cur = conn.cursor()
        cur.execute("SELECT tags FROM subscriptions WHERE id = ?", (sub_id,))
        row = cur.fetchone()
        if not row or row[0] is None:
            return []
        return [t for t in (row[0] or "").split(',') if t]


def get_user_subscriptions_by_tag(user_id: int, tag: str) -> List[Tuple]:
    """Return subscriptions for user that have the given tag (exact match in comma-separated tags)."""
    with sqlite3.connect(DB) as conn:
        cur = conn.cursor()
        # Match as substring with separators to avoid partial matches
        cur.execute("""
            SELECT id, user_id, url, notify_mode, last_price, product_title, product_image,
                   min_price, max_price, notify_percent, notify_interval, last_notify_time, price_alert, tags
            FROM subscriptions
            WHERE user_id = ? AND (',' || IFNULL(tags, '') || ',') LIKE ?
            ORDER BY updated_at DESC
        """, (user_id, '%,' + tag + ',%'))
        return cur.fetchall()


def export_user_subscriptions(user_id: int) -> List[dict]:
    """Return list of subscription dicts for export (all fields)."""
    rows = get_user_subscriptions(user_id)
    out = []
    for r in rows:
        # r expected to be (id,user_id,url,mode,last_price,product_title,product_image,min_price,max_price,notify_percent,notify_interval,last_notify_time,price_alert,tags)
        try:
            (sub_id, uid, url, mode, last_price, product_title, product_image,
             min_price, max_price, notify_percent, notify_interval, last_notify_time, price_alert, tags) = r
        except ValueError:
            # Fallback for older rows
            vals = list(r)
            while len(vals) < 14:
                vals.append(None)
            (sub_id, uid, url, mode, last_price, product_title, product_image,
             min_price, max_price, notify_percent, notify_interval, last_notify_time, price_alert, tags) = vals[:14]
        out.append({
            'id': sub_id,
            'user_id': uid,
            'url': url,
            'mode': mode,
            'last_price': last_price,
            'product_title': product_title,
            'product_image': product_image,
            'min_price': min_price,
            'max_price': max_price,
            'notify_percent': notify_percent,
            'notify_interval': notify_interval,
            'last_notify_time': last_notify_time,
            'price_alert': price_alert,
            'tags': (tags or "")
        })
    return out

def get_all_subscriptions(batch_size: int = 1000) -> List[Tuple[int, int, str, str, Optional[float]]]:
    """
    Получает все подписки с поддержкой пакетной обработки.
    :param batch_size: размер пакета для обработки
    """
    all_rows = []
    with sqlite3.connect(DB) as conn:
        cur = conn.cursor()
        # Используем курсор для пакетной обработки
        # SQLite does not support the NULLS FIRST/NULLS LAST syntax; use COALESCE
        # to provide deterministic ordering when values may be NULL.
        cur.execute("""
            SELECT id, user_id, url, notify_mode, last_price, product_title, product_image,
                   min_price, max_price, notify_percent, notify_interval, last_notify_time, price_alert
            FROM subscriptions
            ORDER BY COALESCE(last_notify_time, 0) ASC
        """)
        while True:
            rows = cur.fetchmany(batch_size)
            if not rows:
                break
            all_rows.extend(rows)
    return all_rows

def update_last_price(sub_id: int, price: float) -> None:
    with sqlite3.connect(DB) as conn:
        cur = conn.cursor()
        cur.execute("UPDATE subscriptions SET last_price = ?, updated_at = ? WHERE id = ?", (price, int(time.time()), sub_id))
        conn.commit()

def update_mode(sub_id: int, mode: str) -> None:
    with sqlite3.connect(DB) as conn:
        cur = conn.cursor()
        cur.execute("UPDATE subscriptions SET notify_mode = ?, updated_at = ? WHERE id = ?", (mode, int(time.time()), sub_id))
        conn.commit()

def get_subscription(sub_id: int):
    """Return canonical subscription tuple (13 fields) or None"""
    with sqlite3.connect(DB) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, user_id, url, notify_mode, last_price, product_title, product_image,
                   min_price, max_price, notify_percent, notify_interval, last_notify_time, price_alert
            FROM subscriptions WHERE id = ?
        """, (sub_id,))
        row = cur.fetchone()
    return row

def update_subscription_settings(sub_id: int, **kwargs):
    """Обновляет настройки подписки"""
    allowed_fields = {
        'min_price', 'max_price', 'notify_percent', 
        'notify_interval', 'notify_mode', 'price_alert'
    }
    
    if not kwargs or not any(k in allowed_fields for k in kwargs):
        return
        
    with sqlite3.connect(DB) as conn:
        cur = conn.cursor()
        sets = []
        params = []
        for k, v in kwargs.items():
            if k in allowed_fields:
                sets.append(f"{k} = ?")
                params.append(v)
        if not sets:
            return
        # Always update updated_at explicitly to reflect changes
        sets.append("updated_at = ?")
        params.append(int(time.time()))
        params.append(sub_id)
        query = f"UPDATE subscriptions SET {', '.join(sets)} WHERE id = ?"
        cur.execute(query, params)
        conn.commit()
        
def update_notify_time(sub_id: int):
    """Обновляет время последнего уведомления"""
    now = int(time.time())
    with sqlite3.connect(DB) as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE subscriptions SET last_notify_time = ?, updated_at = ? WHERE id = ?",
            (now, now, sub_id)
        )
        conn.commit()

def get_user_settings(user_id: int):
    """Получает настройки пользователя"""
    try:
        with sqlite3.connect(DB) as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT language, notify_quiet_hours_start, notify_quiet_hours_end
                FROM users WHERE user_id = ?
            """, (user_id,))
            row = cur.fetchone()
        if not row:
            return ("ru", 23, 7)
        # Нормализуем возвращаемые значения
        lang = row[0] if row and row[0] else "ru"
        try:
            start = int(row[1]) if row and row[1] is not None else 23
        except Exception:
            start = 23
        try:
            end = int(row[2]) if row and row[2] is not None else 7
        except Exception:
            end = 7
        return (lang, start, end)
    except sqlite3.Error as e:
        logger.warning("get_user_settings failed, returning defaults: %s", e)
        return ("ru", 23, 7)

def update_user_settings(user_id: int, **kwargs):
    """Обновляет настройки пользователя"""
    allowed_fields = {
        'language',
        'notify_quiet_hours_start',
        'notify_quiet_hours_end'
    }
    
    if not kwargs or not any(k in allowed_fields for k in kwargs):
        return
        
    with sqlite3.connect(DB) as conn:
        cur = conn.cursor()
        # Гарантируем существование пользователя перед обновлением.
        cur.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        sets = []
        params = []
        for k, v in kwargs.items():
            if k in allowed_fields:
                sets.append(f"{k} = ?")
                params.append(v)
        if not sets:
            return
        params.append(user_id)
        query = f"UPDATE users SET {', '.join(sets)} WHERE user_id = ?"
        cur.execute(query, params)
        conn.commit()


def get_local_price_history(subscription_id: int, days: int = 90):
    """
    Возвращает список (iso_date, price) за последние `days` дней, отсортированных по возрастанию ts.
    """
    try:
        now = int(time.time())
        since = now - int(days) * 24 * 3600
        with sqlite3.connect(DB) as conn:
            cur = conn.cursor()
            cur.execute("SELECT ts, price FROM price_history WHERE subscription_id = ? AND ts >= ? ORDER BY ts ASC",
                        (subscription_id, since))
            rows = cur.fetchall()
        out = []
        for ts, price in rows:
            try:
                out.append((datetime.utcfromtimestamp(int(ts)).isoformat(), float(price)))
            except Exception:
                try:
                    out.append((int(ts), float(price)))
                except Exception:
                    continue
        return out
    except Exception as e:
        logger.exception("get_local_price_history error: %s", e)
        return []


def save_price_point(
    subscription_id: int,
    price: float,
    ts: int = None,
    max_points: int = 10000,
    timestamp: int = None,
) -> int:
    """
    Сохраняет точку цены для подписки с дедупликацией.
    
    Args:
        subscription_id: ID подписки
        price: Цена товара
        ts: Timestamp (по умолчанию текущее время)
        max_points: Максимум точек в истории (старые удаляются)
        timestamp: Совместимость со старым именем аргумента
    
    Returns:
        ID вставленной строки или -1 при ошибке
    """
    if timestamp is not None and ts is None:
        ts = timestamp
    if ts is None:
        ts = int(time.time())

    try:
        with DatabaseConnection() as conn:
            cur = conn.cursor()
            
            # Проверяем дубликат в последний час
            one_hour_ago = ts - 3600
            cur.execute("""
                SELECT id FROM price_history 
                WHERE subscription_id = ? 
                AND ts > ? 
                AND price = ?
                LIMIT 1
            """, (subscription_id, one_hour_ago, price))
            
            if cur.fetchone() is not None:
                logger.debug(f"Duplicate price point detected for sub {subscription_id}")
                return -1
            
            # Вставляем новую точку
            cur.execute("""
                INSERT INTO price_history 
                (subscription_id, url, price, ts, source) 
                SELECT ?, url, ?, ?, 'collector'
                FROM subscriptions WHERE id = ?
            """, (subscription_id, price, ts, subscription_id))
            
            new_id = cur.lastrowid
            
            # Удаляем старые точки если превышен лимит
            cur.execute("""
                SELECT COUNT(*) FROM price_history 
                WHERE subscription_id = ?
            """, (subscription_id,))
            
            count = cur.fetchone()[0]
            if count > max_points:
                excess = count - max_points
                cur.execute("""
                    DELETE FROM price_history 
                    WHERE id IN (
                        SELECT id FROM price_history 
                        WHERE subscription_id = ?
                        ORDER BY ts ASC
                        LIMIT ?
                    )
                """, (subscription_id, excess))
                logger.info(f"Deleted {excess} old price points for sub {subscription_id}")
            
            
            conn.commit()
            return new_id
            
    except sqlite3.IntegrityError as e:
        logger.error(f"Integrity error saving price point: {e}")
        return -1
    except Exception as e:
        logger.exception(f"Error saving price point for sub {subscription_id}: {e}")
        return -1

# === ВОЛНА 2: Функции анализа цен ===

def get_price_stats(subscription_id: int) -> dict:
    """Получить статистику цен по подписке: мин/макс/среднее/тренд"""
    with sqlite3.connect(DB) as conn:
        cur = conn.cursor()
        # Получаем последние 90 дней истории
        now = int(time.time())
        since_ts = now - (90 * 24 * 3600)
        
        cur.execute("""
            SELECT 
                MIN(price) as min_price,
                MAX(price) as max_price,
                AVG(price) as avg_price,
                COUNT(*) as count
            FROM price_history 
            WHERE subscription_id = ? AND ts >= ?
        """, (subscription_id, since_ts))
        
        row = cur.fetchone()
        if not row or not row[3]:  # Нет истории или count=0
            return {
                'min': None, 'max': None, 'avg': None, 'current': None, 
                'trend': 'unknown', 'days': 0, 'count': 0
            }
        
        min_price, max_price, avg_price, count = row
        
        # Получаем текущую цену (последняя точка)
        cur.execute("""
            SELECT price FROM price_history 
            WHERE subscription_id = ? 
            ORDER BY ts DESC LIMIT 1
        """, (subscription_id,))
        
        current_row = cur.fetchone()
        current_price = current_row[0] if current_row else None
        
        # Определяем тренд: сравниваем среднюю цену за последние 7 дней с общей средней
        week_ago = now - (7 * 24 * 3600)
        cur.execute("""
            SELECT AVG(price) FROM price_history 
            WHERE subscription_id = ? AND ts >= ?
        """, (subscription_id, week_ago))
        
        week_avg_row = cur.fetchone()
        week_avg = week_avg_row[0] if week_avg_row and week_avg_row[0] else avg_price
        
        if week_avg and avg_price:
            if week_avg < avg_price * 0.98:  # На 2% ниже
                trend = '📉 Падает'
            elif week_avg > avg_price * 1.02:  # На 2% выше
                trend = '📈 Растет'
            else:
                trend = '➡️ Стабильна'
        else:
            trend = 'unknown'
        
        return {
            'min': min_price,
            'max': max_price,
            'avg': avg_price,
            'current': current_price,
            'trend': trend,
            'days': 90,
            'count': count
        }

def get_top_price_drops(user_id: int, limit: int = 10) -> List[tuple]:
    """Получить топ товаров с наибольшим падением цены для пользователя
    Возвращает список (sub_id, url, product_title, current_price, min_price, drop_percent)
    """
    with sqlite3.connect(DB) as conn:
        cur = conn.cursor()
        now = int(time.time())
        month_ago = now - (30 * 24 * 3600)
        
        # Для каждой подписки пользователя находим цену месяц назад и сейчас
        cur.execute("""
            WITH user_subs AS (
                SELECT id, url, product_title, last_price
                FROM subscriptions
                WHERE user_id = ?
            ),
            price_range AS (
                SELECT 
                    ph.subscription_id,
                    (SELECT price FROM price_history ph2 
                     WHERE ph2.subscription_id = ph.subscription_id 
                     AND ph2.ts >= ? ORDER BY ts ASC LIMIT 1) as price_month_ago,
                    (SELECT price FROM price_history ph2 
                     WHERE ph2.subscription_id = ph.subscription_id 
                     ORDER BY ts DESC LIMIT 1) as current_price,
                    MIN(ph.price) as min_price
                FROM price_history ph
                WHERE ph.ts >= ?
                GROUP BY ph.subscription_id
            )
            SELECT 
                us.id,
                us.url,
                us.product_title,
                pr.current_price,
                pr.min_price,
                CASE 
                    WHEN pr.price_month_ago IS NOT NULL AND pr.price_month_ago > 0
                    THEN ROUND(((pr.current_price - pr.price_month_ago) / pr.price_month_ago) * 100, 1)
                    ELSE 0
                END as drop_percent
            FROM user_subs us
            LEFT JOIN price_range pr ON us.id = pr.subscription_id
            WHERE pr.current_price IS NOT NULL AND pr.min_price IS NOT NULL
            ORDER BY drop_percent ASC
            LIMIT ?
        """, (user_id, month_ago, month_ago, limit))

        return cur.fetchall()

# --- Recommended Products Management ---

def add_recommended_product(title: str, url: str, price: str = "",
                          category: str = "", brand: str = "",
                          reason_template: str = "", priority: int = 0) -> bool:
    """Добавить рекомендуемый продукт"""
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO recommended_products
                (title, url, price, category, brand, reason_template, priority)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (title, url, price, category, brand, reason_template, priority))
            conn.commit()
            return True
    except Exception as e:
        logger.error(f"Error adding recommended product: {e}")
        return False

def remove_recommended_product(product_id: int) -> bool:
    """Удалить рекомендуемый продукт"""
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM recommended_products WHERE id = ?", (product_id,))
            conn.commit()
            return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Error removing recommended product: {e}")
        return False

def get_recommended_products() -> List[Dict[str, Any]]:
    """Получить все рекомендуемые продукты"""
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, title, url, price, category, brand, reason_template, priority, is_active
                FROM recommended_products
                WHERE is_active = 1
                ORDER BY priority DESC, created_at DESC
            """)
            rows = cur.fetchall()

            return [{
                "id": row[0],
                "title": row[1],
                "url": row[2],
                "price": row[3] or "Цена не указана",
                "category": row[4] or "other",
                "brand": row[5] or "",
                "reason_template": row[6] or "Рекомендуемый товар",
                "priority": row[7],
                "is_active": bool(row[8])
            } for row in rows]
    except Exception as e:
        logger.error(f"Error getting recommended products: {e}")
        return []

def update_recommended_product_priority(product_id: int, priority: int) -> bool:
    """Обновить приоритет рекомендуемого продукта"""
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE recommended_products
                SET priority = ?, updated_at = strftime('%s', 'now')
                WHERE id = ?
            """, (priority, product_id))
            conn.commit()
            return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Error updating recommended product priority: {e}")
        return False

# --- Bot text settings ---

def get_bot_text(key: str, language: Optional[str] = None) -> Optional[str]:
    """Получить кастомный текст по ключу (с fallback на '*' язык)."""
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            if language:
                cur.execute(
                    "SELECT value FROM bot_texts WHERE key = ? AND language = ?",
                    (key, language),
                )
                row = cur.fetchone()
                if row and row[0]:
                    return row[0]
            cur.execute(
                "SELECT value FROM bot_texts WHERE key = ? AND language = '*'",
                (key,),
            )
            row = cur.fetchone()
            return row[0] if row else None
    except Exception as e:
        logger.error(f"Error getting bot text: {e}")
        return None


def set_bot_text(key: str, value: str, language: Optional[str] = None) -> None:
    """Установить кастомный текст по ключу. Пустое значение удаляет запись."""
    lang = (language or "*").strip() or "*"
    text = (value or "").strip()
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            if not text:
                cur.execute(
                    "DELETE FROM bot_texts WHERE key = ? AND language = ?",
                    (key, lang),
                )
                conn.commit()
                return
            cur.execute(
                """
                INSERT OR REPLACE INTO bot_texts (key, language, value, updated_at)
                VALUES (?, ?, ?, strftime('%s', 'now'))
                """,
                (key, lang, text),
            )
            conn.commit()
    except Exception as e:
        logger.error(f"Error setting bot text: {e}")
