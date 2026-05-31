import sqlite3
import time
import logging
import threading
import os
from typing import List, Tuple, Optional, Dict, Any, Iterator
from datetime import datetime

                       
logger = logging.getLogger('database')

                                                                
                                                         
DB = os.getenv("DATABASE_PATH", "trendyol_bot.db")

                                           
_connection_pool = {}
_pool_lock = threading.Lock()
_current_db = None

def get_connection():
    """Get database connection from pool or create new one"""
    thread_id = threading.get_ident()
    global _current_db
                                                                          
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

                                                                 
class DatabaseConnection:
    """Context manager for database operations using connection pooling"""
    def __enter__(self):
        self.conn = get_connection()
        return self.conn

    def __exit__(self, exc_type, exc_val, exc_tb):
                                                         
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

def create_sqlite_backup(backup_path: str) -> None:
    """Create a consistent SQLite backup using native backup API."""
    src_conn = None
    dst_conn = None
    try:
        src_conn = sqlite3.connect(DB, timeout=30.0)
        src_conn.execute("PRAGMA busy_timeout = 5000")
        dst_conn = sqlite3.connect(backup_path, timeout=30.0)
        src_conn.backup(dst_conn)
        dst_conn.commit()
    finally:
        if dst_conn is not None:
            try:
                dst_conn.close()
            except Exception:
                pass
        if src_conn is not None:
            try:
                src_conn.close()
            except Exception:
                pass

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

def init_db(run_maintenance: bool = True):
                                                                  
    with sqlite3.connect(DB) as conn:
        cur = conn.cursor()
                                                                  
                                                                           
                                                                
        try:
            cur.execute("DROP TRIGGER IF EXISTS update_subscription_timestamp")
            cur.execute("DROP TRIGGER IF EXISTS cleanup_old_subscriptions")
        except Exception:
                                                                        
            logger.debug("No legacy triggers to drop or error during drop", exc_info=True)
        
                                                                      
        try:
            cur.execute("SELECT * FROM subscriptions LIMIT 0")
            columns = [description[0] for description in cur.description]
        except sqlite3.OperationalError:
            columns = []
            
                                                               
        if columns:
            current_time = int(time.time())
            
                                                              
            missing_columns = {
                'updated_at': f"ALTER TABLE subscriptions ADD COLUMN updated_at INTEGER DEFAULT {current_time}",
                'created_at': f"ALTER TABLE subscriptions ADD COLUMN created_at INTEGER DEFAULT {current_time}",
                'product_title': "ALTER TABLE subscriptions ADD COLUMN product_title TEXT",
                'product_image': "ALTER TABLE subscriptions ADD COLUMN product_image TEXT",
                'min_price': "ALTER TABLE subscriptions ADD COLUMN min_price REAL",
                'max_price': "ALTER TABLE subscriptions ADD COLUMN max_price REAL", 
                'notify_percent': "ALTER TABLE subscriptions ADD COLUMN notify_percent REAL",
                'notify_interval': "ALTER TABLE subscriptions ADD COLUMN notify_interval INTEGER DEFAULT 60",
                'last_notify_time': "ALTER TABLE subscriptions ADD COLUMN last_notify_time INTEGER",
                'check_fail_count': "ALTER TABLE subscriptions ADD COLUMN check_fail_count INTEGER DEFAULT 0",
                'last_check_error': "ALTER TABLE subscriptions ADD COLUMN last_check_error TEXT",
                'last_check_error_at': "ALTER TABLE subscriptions ADD COLUMN last_check_error_at INTEGER",
            }
            
            for col_name, alter_sql in missing_columns.items():
                if col_name not in columns:
                    try:
                        cur.execute(alter_sql)
                        logger.info(f"Added missing column: {col_name}")
                    except sqlite3.OperationalError as e:
                        logger.warning(f"Could not add column {col_name}: {e}")
            
            conn.commit()
                                                                         
        try:
            cur.execute("SELECT * FROM users LIMIT 0")
            user_columns = [description[0] for description in cur.description]
        except sqlite3.OperationalError:
            user_columns = []

        if user_columns:
            now_ts = int(time.time())
            user_missing = {
                'notify_quiet_hours_start': "ALTER TABLE users ADD COLUMN notify_quiet_hours_start INTEGER DEFAULT 23",
                'notify_quiet_hours_end': "ALTER TABLE users ADD COLUMN notify_quiet_hours_end INTEGER DEFAULT 7",
                'created_at': f"ALTER TABLE users ADD COLUMN created_at INTEGER DEFAULT {now_ts}",
                'username': "ALTER TABLE users ADD COLUMN username TEXT",
                'first_name': "ALTER TABLE users ADD COLUMN first_name TEXT",
                'last_name': "ALTER TABLE users ADD COLUMN last_name TEXT",
                'telegram_language_code': "ALTER TABLE users ADD COLUMN telegram_language_code TEXT",
                'is_premium': "ALTER TABLE users ADD COLUMN is_premium INTEGER DEFAULT 0",
                'last_seen_at': f"ALTER TABLE users ADD COLUMN last_seen_at INTEGER DEFAULT {now_ts}",
            }
            for col_name, alter_sql in user_missing.items():
                if col_name not in user_columns:
                    try:
                        cur.execute(alter_sql)
                        logger.info(f"Added missing user column: {col_name}")
                    except sqlite3.OperationalError as e:
                        logger.warning(f"Could not add user column {col_name}: {e}")
            conn.commit()
    
                                                       
    if run_maintenance:
        with sqlite3.connect(DB) as conn:
            conn.execute("PRAGMA foreign_keys = OFF")                                       
            conn.execute("VACUUM")                                
            conn.execute("ANALYZE")                                                  
        
                                              
    with sqlite3.connect(DB) as conn:
                                           
        conn.execute("PRAGMA foreign_keys = ON")
        
                                        
        conn.execute("PRAGMA journal_mode = WAL")                       
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA cache_size = -20000")                                  
        conn.execute("PRAGMA temp_store = MEMORY")
        conn.execute("PRAGMA mmap_size = 30000000000")                                
        conn.execute("PRAGMA page_size = 4096")                               
        
        cur = conn.cursor()
        
                                      
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            language TEXT DEFAULT 'ru',
            notify_quiet_hours_start INTEGER DEFAULT 23,
            notify_quiet_hours_end INTEGER DEFAULT 7,
            created_at INTEGER DEFAULT (strftime('%s', 'now')),
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            telegram_language_code TEXT,
            is_premium INTEGER DEFAULT 0,
            last_seen_at INTEGER DEFAULT (strftime('%s', 'now'))
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
            check_fail_count INTEGER DEFAULT 0,
            last_check_error TEXT,
            last_check_error_at INTEGER,
            created_at INTEGER DEFAULT (CAST(strftime('%s', 'now') AS INTEGER)),
            updated_at INTEGER DEFAULT (CAST(strftime('%s', 'now') AS INTEGER)),
            FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
        )
        """)
        
                                                                   
                                                                              
        cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_subscriptions_user_compound ON subscriptions(user_id, updated_at DESC)
        """)

        cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_subscriptions_user_order ON subscriptions(user_id, id DESC)
        """)
        
                                                    
        cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_subscriptions_url_mode ON subscriptions(url, notify_mode)
        """)
        
                                                               
        cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_subscriptions_notify_time ON subscriptions(last_notify_time, notify_interval)
        """)
        
                                                    
        cur.execute("CREATE INDEX IF NOT EXISTS idx_users_language ON users(language)")
        
                                                                    
                                                                          
                                                                            
                                                                                
        conn.commit()
        
                                                            
        cur.execute("ANALYZE subscriptions")
        cur.execute("ANALYZE users")
                                                                               
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
                                                  
        cur.execute("CREATE INDEX IF NOT EXISTS idx_price_history_url_ts ON price_history(url, ts DESC)")
        cur.execute("ANALYZE price_history")
        
                                                                            
        try:
            cur.execute("ALTER TABLE subscriptions ADD COLUMN price_alert REAL")
            logger.info("Migration: Added price_alert column to subscriptions table")
        except sqlite3.OperationalError:
            pass                         
                                                                        
        try:
            cur.execute("ALTER TABLE subscriptions ADD COLUMN tags TEXT")
            logger.info("Migration: Added tags column to subscriptions table")
        except sqlite3.OperationalError:
            pass                         

        check_failure_columns = {
            "check_fail_count": "ALTER TABLE subscriptions ADD COLUMN check_fail_count INTEGER DEFAULT 0",
            "last_check_error": "ALTER TABLE subscriptions ADD COLUMN last_check_error TEXT",
            "last_check_error_at": "ALTER TABLE subscriptions ADD COLUMN last_check_error_at INTEGER",
        }
        for col_name, alter_sql in check_failure_columns.items():
            try:
                cur.execute(alter_sql)
                logger.info("Migration: Added %s column to subscriptions table", col_name)
            except sqlite3.OperationalError:
                pass

                                                 
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

                                                                         
        cur.execute("""
        CREATE TABLE IF NOT EXISTS bot_texts (
            key TEXT NOT NULL,
            language TEXT NOT NULL DEFAULT '*',
            value TEXT NOT NULL,
            updated_at INTEGER DEFAULT (strftime('%s', 'now')),
            PRIMARY KEY (key, language)
        )
        """)

                                                                   
        try:
                                                                  
            existing_indexes = set()
            cur.execute("SELECT name FROM sqlite_master WHERE type='index'")
            existing_indexes = {row[0] for row in cur.fetchall()}

            indexes_to_create = [
                ("idx_users_language", "CREATE INDEX idx_users_language ON users(language)"),
                ("idx_subscriptions_user_id", "CREATE INDEX idx_subscriptions_user_id ON subscriptions(user_id)"),
                ("idx_subscriptions_user_order", "CREATE INDEX idx_subscriptions_user_order ON subscriptions(user_id, id DESC)"),
                ("idx_subscriptions_url", "CREATE INDEX idx_subscriptions_url ON subscriptions(url)"),
                ("idx_subscriptions_mode", "CREATE INDEX idx_subscriptions_mode ON subscriptions(notify_mode)"),
                ("idx_subscriptions_notify_time", "CREATE INDEX idx_subscriptions_notify_time ON subscriptions(last_notify_time)"),
                ("idx_subscriptions_url_mode", "CREATE INDEX idx_subscriptions_url_mode ON subscriptions(url, notify_mode)"),
                ("idx_subscriptions_check_failures", "CREATE INDEX idx_subscriptions_check_failures ON subscriptions(check_fail_count, last_check_error_at)"),
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

def save_user_profile(user: Any) -> None:
    """Persist Telegram profile fields from an aiogram user-like object."""
    if user is None:
        return

    user_id = getattr(user, "id", None)
    if not user_id:
        return

    now_ts = int(time.time())
    username = getattr(user, "username", None)
    first_name = getattr(user, "first_name", None)
    last_name = getattr(user, "last_name", None)
    telegram_language_code = getattr(user, "language_code", None)
    is_premium = 1 if getattr(user, "is_premium", False) else 0

    with DatabaseConnection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT OR IGNORE INTO users (user_id, language, created_at, last_seen_at)
            VALUES (?, ?, ?, ?)
            """,
            (int(user_id), "ru", now_ts, now_ts),
        )
        cur.execute(
            """
            UPDATE users
            SET username = ?,
                first_name = ?,
                last_name = ?,
                telegram_language_code = ?,
                is_premium = ?,
                last_seen_at = ?
            WHERE user_id = ?
            """,
            (
                username,
                first_name,
                last_name,
                telegram_language_code,
                is_premium,
                now_ts,
                int(user_id),
            ),
        )

def get_user_profile(user_id: int) -> Optional[Dict[str, Any]]:
    with DatabaseConnection() as conn:
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        finally:
            conn.row_factory = None

    return dict(row) if row else None

def set_user_language(user_id: int, language: str) -> None:
    with DatabaseConnection() as conn:
        cur = conn.cursor()
                                                                                  
                                                                                    
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
            ORDER BY id DESC
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
                                                                     
        cur.execute("""
            SELECT id, user_id, url, notify_mode, last_price, product_title, product_image,
                   min_price, max_price, notify_percent, notify_interval, last_notify_time, price_alert, tags
            FROM subscriptions
            WHERE user_id = ? AND (',' || IFNULL(tags, '') || ',') LIKE ?
            ORDER BY id DESC
        """, (user_id, '%,' + tag + ',%'))
        return cur.fetchall()


def export_user_subscriptions(user_id: int) -> List[dict]:
    """Return list of subscription dicts for export (all fields)."""
    rows = get_user_subscriptions(user_id)
    out = []
    for r in rows:
                                                                                                                                                                            
        try:
            (sub_id, uid, url, mode, last_price, product_title, product_image,
             min_price, max_price, notify_percent, notify_interval, last_notify_time, price_alert, tags) = r
        except ValueError:
                                     
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

def get_subscriptions_count() -> int:
    """Return total number of subscriptions."""
    with sqlite3.connect(DB) as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM subscriptions")
        row = cur.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def iter_all_subscriptions(batch_size: int = 1000) -> Iterator[Tuple[int, int, str, str, Optional[float]]]:
    """
    Stream subscriptions in DB batches to avoid loading everything into memory.
    """
    with sqlite3.connect(DB) as conn:
        cur = conn.cursor()
                                                  
                                                                                 
                                                                    
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
            for row in rows:
                yield row


def get_all_subscriptions(batch_size: int = 1000) -> List[Tuple[int, int, str, str, Optional[float]]]:
    """
    Backward-compatible helper that returns all subscriptions as a list.
    """
    return list(iter_all_subscriptions(batch_size=batch_size))

def update_last_price(sub_id: int, price: float) -> None:
    with sqlite3.connect(DB) as conn:
        cur = conn.cursor()
        cur.execute("UPDATE subscriptions SET last_price = ?, updated_at = ? WHERE id = ?", (price, int(time.time()), sub_id))
        conn.commit()


def record_subscription_check_failure(sub_id: int, reason: str, ts: Optional[int] = None) -> None:
    """Remember a failed price check without changing the public subscription tuple."""
    if ts is None:
        ts = int(time.time())
    reason_text = (reason or "price_check_failed").strip()[:200]
    with sqlite3.connect(DB) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE subscriptions
            SET check_fail_count = COALESCE(check_fail_count, 0) + 1,
                last_check_error = ?,
                last_check_error_at = ?
            WHERE id = ?
            """,
            (reason_text, int(ts), sub_id),
        )
        conn.commit()


def clear_subscription_check_failure(sub_id: int) -> None:
    """Clear stored price-check failure state after a successful price read."""
    with sqlite3.connect(DB) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE subscriptions
            SET check_fail_count = 0,
                last_check_error = NULL,
                last_check_error_at = NULL
            WHERE id = ?
              AND (
                COALESCE(check_fail_count, 0) != 0
                OR last_check_error IS NOT NULL
                OR last_check_error_at IS NOT NULL
              )
            """,
            (sub_id,),
        )
        conn.commit()


def get_broken_subscriptions(limit: int = 50, min_fail_count: int = 1) -> List[Dict[str, Any]]:
    """Return subscriptions with recent consecutive price-check failures."""
    safe_limit = max(1, min(int(limit or 50), 500))
    safe_min_fail_count = max(1, int(min_fail_count or 1))
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                s.id,
                s.user_id,
                s.url,
                s.notify_mode,
                s.last_price,
                s.product_title,
                s.product_image,
                COALESCE(s.check_fail_count, 0) AS check_fail_count,
                s.last_check_error,
                s.last_check_error_at,
                u.username,
                u.first_name,
                u.last_name
            FROM subscriptions s
            LEFT JOIN users u ON u.user_id = s.user_id
            WHERE COALESCE(s.check_fail_count, 0) >= ?
            ORDER BY COALESCE(s.check_fail_count, 0) DESC,
                     COALESCE(s.last_check_error_at, 0) DESC,
                     s.id DESC
            LIMIT ?
            """,
            (safe_min_fail_count, safe_limit),
        )
        rows = cur.fetchall()
    return [dict(row) for row in rows]


def get_subscription_check_failures_for_user(
    user_id: int,
    min_fail_count: int = 1,
) -> Dict[int, Dict[str, Any]]:
    """Return current price-check failure state for one user's subscriptions."""
    safe_min_fail_count = max(1, int(min_fail_count or 1))
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                id,
                COALESCE(check_fail_count, 0) AS check_fail_count,
                last_check_error,
                last_check_error_at
            FROM subscriptions
            WHERE user_id = ?
              AND COALESCE(check_fail_count, 0) >= ?
            """,
            (user_id, safe_min_fail_count),
        )
        rows = cur.fetchall()
    return {int(row["id"]): dict(row) for row in rows}


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
            
                                   
            cur.execute("""
                INSERT INTO price_history 
                (subscription_id, url, price, ts, source) 
                SELECT ?, url, ?, ?, 'collector'
                FROM subscriptions WHERE id = ?
            """, (subscription_id, price, ts, subscription_id))
            
            new_id = cur.lastrowid
            
                                                      
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

                                      

def get_price_stats(subscription_id: int) -> dict:
    """Получить статистику цен по подписке: мин/макс/среднее/тренд"""
    with sqlite3.connect(DB) as conn:
        cur = conn.cursor()
                                            
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
        if not row or not row[3]:                           
            return {
                'min': None, 'max': None, 'avg': None, 'current': None, 
                'trend': 'unknown', 'days': 0, 'count': 0
            }
        
        min_price, max_price, avg_price, count = row
        
                                                 
        cur.execute("""
            SELECT price FROM price_history 
            WHERE subscription_id = ? 
            ORDER BY ts DESC LIMIT 1
        """, (subscription_id,))
        
        current_row = cur.fetchone()
        current_price = current_row[0] if current_row else None
        
                                                                                       
        week_ago = now - (7 * 24 * 3600)
        cur.execute("""
            SELECT AVG(price) FROM price_history 
            WHERE subscription_id = ? AND ts >= ?
        """, (subscription_id, week_ago))
        
        week_avg_row = cur.fetchone()
        week_avg = week_avg_row[0] if week_avg_row and week_avg_row[0] else avg_price
        
        if week_avg and avg_price:
            if week_avg < avg_price * 0.98:              
                trend = '📉 Падает'
            elif week_avg > avg_price * 1.02:              
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
