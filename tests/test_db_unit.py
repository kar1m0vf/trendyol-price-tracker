import os
import tempfile
import time
import sqlite3
import pytest

# Ensure project root is importable
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import database

@pytest.fixture()
def temp_db_path(tmp_path, monkeypatch):
    db_file = tmp_path / "test_trendyol_bot.db"
    # Point database module to temp DB
    monkeypatch.setattr(database, 'DB', str(db_file))
    # initialize schema
    database.init_db()
    return str(db_file)

def test_add_subscription_and_price_flow(temp_db_path):
    # Add subscription
    user_id = 12345
    url = 'https://www.trendyol.com/test-product'
    sub_id = database.add_subscription(user_id, url, product_title='UT Test')
    assert isinstance(sub_id, int) and sub_id > 0

    # Add some price points
    now = int(time.time())
    prices = [3000.0, 2900.0, 2800.0]
    for i, p in enumerate(prices):
        ts = now - (len(prices) - i) * 60
        pid = database.add_price_point(sub_id, url, p, ts)
        assert isinstance(pid, int) and pid > 0

    # get_price_stats should return counts and min/max
    stats = database.get_price_stats(sub_id)
    assert stats['count'] == len(prices)
    assert stats['min'] == min(prices)
    assert stats['max'] == max(prices)
    assert stats['current'] == prices[-1]

    # get_user_subscriptions should include our sub
    subs = database.get_user_subscriptions(user_id)
    assert any(s[0] == sub_id for s in subs)

    # top drops for user should return at least this subscription
    drops = database.get_top_price_drops(user_id, limit=5)
    assert any(d[0] == sub_id for d in drops)

    # cleanup
    assert database.remove_subscription(sub_id) is True
    # Ensure removed
    assert database.get_subscription(sub_id) is None

def test_price_history_functions_empty(temp_db_path):
    # For non-existing subscription, functions should behave gracefully
    assert database.get_price_history(9999999) == []
    assert database.get_last_price_point(9999999) is None

