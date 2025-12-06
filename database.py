import sqlite3
import time
import logging
from typing import List, Tuple, Optional
from datetime import datetime

# Настройка логирования
logger = logging.getLogger('database')

DB = "trendyol_bot.db"

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

def add_user_if_not_exists(user_id: int, language: str = "ru") -> None:
    with sqlite3.connect(DB) as conn:
        cur = conn.cursor()
        cur.execute("INSERT OR IGNORE INTO users (user_id, language) VALUES (?, ?)", (user_id, language))
        conn.commit()

def set_user_language(user_id: int, language: str) -> None:
    with sqlite3.connect(DB) as conn:
        cur = conn.cursor()
        cur.execute("INSERT OR REPLACE INTO users (user_id, language) VALUES (?, ?)", (user_id, language))
        conn.commit()

def get_user_language(user_id: int) -> str:
    with sqlite3.connect(DB) as conn:
        cur = conn.cursor()
        cur.execute("SELECT language FROM users WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
    return row[0] if row else "ru"

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
    with sqlite3.connect(DB) as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO subscriptions (
                user_id, url, product_title, product_image, notify_mode, min_price, max_price, 
                notify_percent, notify_interval
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, url, product_title, product_image, mode, min_price, max_price, notify_percent, notify_interval))
        conn.commit()
        sub_id = cur.lastrowid
    return sub_id


def add_price_point(subscription_id: int, url: str, price: float, ts: int = None, source: str = 'collector') -> int:
    """Insert a price point for a subscription. Returns inserted id."""
    if ts is None:
        ts = int(time.time())
    with sqlite3.connect(DB) as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO price_history (subscription_id, url, price, ts, source) VALUES (?, ?, ?, ?, ?)",
                    (subscription_id, url, price, ts, source))
        conn.commit()
        return cur.lastrowid


def get_price_history(subscription_id: int, limit: int = 500, since_ts: int = None):
    """Return list of (ts, price) ordered ascending by ts (oldest first).
    If since_ts provided, only points with ts >= since_ts are returned.
    """
    with sqlite3.connect(DB) as conn:
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
    with sqlite3.connect(DB) as conn:
        cur = conn.cursor()
        cur.execute("SELECT ts, price FROM price_history WHERE subscription_id = ? ORDER BY ts DESC LIMIT 1", (subscription_id,))
        row = cur.fetchone()
    return row


def delete_price_history_for_subscription(subscription_id: int) -> int:
    """Delete history for a given subscription. Returns deleted count."""
    with sqlite3.connect(DB) as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM price_history WHERE subscription_id = ?", (subscription_id,))
        cnt = cur.rowcount
        conn.commit()
    return cnt


def get_subscription_by_url(url: str):
    """Return subscription row by exact url match, canonical tuple or None."""
    with sqlite3.connect(DB) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, user_id, url, notify_mode, last_price, product_title, product_image,
                   min_price, max_price, notify_percent, notify_interval, last_notify_time
            FROM subscriptions WHERE url = ? LIMIT 1
        """, (url,))
        row = cur.fetchone()
    return row


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
            conn.commit()
            return cur.rowcount > 0
    except sqlite3.Error as e:
        logger.error(f"Error removing subscription {sub_id}: {e}")
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
            return deleted_count
    except sqlite3.Error as e:
        logger.error(f"Error removing subscriptions for user {user_id}: {e}")
        return 0

def get_user_subscriptions(user_id: int) -> List[Tuple]:
    """Returns rows in canonical order:
    (id, user_id, url, notify_mode, last_price, product_title, product_image,
     min_price, max_price, notify_percent, notify_interval, last_notify_time, price_alert)
    """
    with sqlite3.connect(DB) as conn:
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
                   min_price, max_price, notify_percent, notify_interval, last_notify_time
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
    allowed_fields = {'notify_quiet_hours_start', 'notify_quiet_hours_end'}
    
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
        params.append(user_id)
        query = f"UPDATE users SET {', '.join(sets)} WHERE user_id = ?"
        cur.execute(query, params)
        conn.commit()


def save_price_point(subscription_id: int, price: float, timestamp: int = None) -> Optional[int]:
    """
    Сохраняет точку цены с дедупликацией и ограничением количества точек по подписке.
    Правила:
      - Не сохранять, если последняя цена == текущая и прошло < 1 часа
      - Ограничение точек: если точек > 500, удалить самые старые
    Возвращает id вставленной записи или None, если запись не добавлена.
    """
    try:
        if timestamp is None:
            timestamp = int(time.time())
        with sqlite3.connect(DB) as conn:
            cur = conn.cursor()
            # Проверяем последнюю точку
            cur.execute("SELECT id, ts, price FROM price_history WHERE subscription_id = ? ORDER BY ts DESC LIMIT 1", (subscription_id,))
            last = cur.fetchone()
            if last:
                last_id, last_ts, last_price = last
                try:
                    if float(last_price) == float(price) and (int(timestamp) - int(last_ts)) < 3600:
                        # Считаем дубликатом — не сохраняем
                        return None
                except Exception:
                    pass

            # Вставляем новую точку
            cur.execute("INSERT INTO price_history (subscription_id, url, price, ts, source) VALUES (?, ?, ?, ?, ?)",
                        (subscription_id, '', float(price), int(timestamp), 'collector'))
            inserted_id = cur.lastrowid

            # Ограничение количества точек (cap = 500)
            cur.execute("SELECT COUNT(1) FROM price_history WHERE subscription_id = ?", (subscription_id,))
            cnt = cur.fetchone()[0]
            if cnt > 500:
                to_delete = cnt - 500
                # Удаляем самые старые записи — используем подзапрос по id
                cur.execute("SELECT id FROM price_history WHERE subscription_id = ? ORDER BY ts ASC LIMIT ?", (subscription_id, to_delete))
                ids = [r[0] for r in cur.fetchall()]
                if ids:
                    q = ','.join('?' for _ in ids)
                    cur.execute(f"DELETE FROM price_history WHERE id IN ({q})", ids)

            conn.commit()
            return inserted_id
    except Exception as e:
        logger.exception("save_price_point error: %s", e)
        return None


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


def get_user_settings(user_id: int):
    """
    Получает настройки пользователя с безопасными значениями по умолчанию.
    
    Returns:
        Tuple[str, int, int]: (language, notify_quiet_hours_start, notify_quiet_hours_end)
        Возвращает значения по умолчанию если пользователь не найден
    """
    try:
        with sqlite3.connect(DB) as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT language, notify_quiet_hours_start, notify_quiet_hours_end
                FROM users WHERE user_id = ?
            """, (user_id,))
            row = cur.fetchone()
        
        if row:
            return row
        else:
            # Возвращаем безопасные значения по умолчанию
            return ("ru", 23, 7)
    except Exception as e:
        logger.exception(f"Error getting user settings for {user_id}: {e}")
        return ("ru", 23, 7)


def update_user_settings(user_id: int, **kwargs) -> None:
    """
    Обновляет настройки пользователя.
    
    Args:
        user_id: ID пользователя
        **kwargs: Поля для обновления (language, notify_quiet_hours_start, notify_quiet_hours_end)
    """
    allowed_fields = {
        'language',
        'notify_quiet_hours_start',
        'notify_quiet_hours_end'
    }
    
    update_dict = {k: v for k, v in kwargs.items() if k in allowed_fields}
    
    if not update_dict:
        logger.warning(f"No valid fields to update for user {user_id}")
        return
    
    try:
        with sqlite3.connect(DB) as conn:
            cur = conn.cursor()
            
            # Убедимся, что пользователь существует
            cur.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
            
            # Обновляем поля
            set_clause = ", ".join(f"{k} = ?" for k in update_dict.keys())
            values = list(update_dict.values()) + [user_id]
            
            cur.execute(f"UPDATE users SET {set_clause} WHERE user_id = ?", values)
            conn.commit()
            
            logger.info(f"Updated user {user_id} settings: {update_dict}")
    except Exception as e:
        logger.exception(f"Error updating user settings for {user_id}: {e}")


def save_price_point(subscription_id: int, price: float, ts: int = None, max_points: int = 10000) -> int:
    """
    Сохраняет точку цены для подписки с дедупликацией.
    
    Args:
        subscription_id: ID подписки
        price: Цена товара
        ts: Timestamp (по умолчанию текущее время)
        max_points: Максимум точек в истории (старые удаляются)
    
    Returns:
        ID вставленной строки или -1 при ошибке
    """
    if ts is None:
        ts = int(time.time())
    
    try:
        with sqlite3.connect(DB) as conn:
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

