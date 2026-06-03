import os
import tempfile
import time
import sqlite3
import pytest

                                   
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import database

@pytest.fixture()
def temp_db_path(tmp_path, monkeypatch):
    db_file = tmp_path / "test_trendyol_bot.db"
                                      
    monkeypatch.setattr(database, 'DB', str(db_file))
                       
    database.init_db()
    return str(db_file)

def test_add_subscription_and_price_flow(temp_db_path):
                      
    user_id = 12345
    url = 'https://www.trendyol.com/test-product'
    sub_id = database.add_subscription(user_id, url, product_title='UT Test')
    assert isinstance(sub_id, int) and sub_id > 0

                           
    now = int(time.time())
    prices = [3000.0, 2900.0, 2800.0]
    for i, p in enumerate(prices):
        ts = now - (len(prices) - i) * 60
        pid = database.add_price_point(sub_id, url, p, ts)
        assert isinstance(pid, int) and pid > 0

                                                      
    stats = database.get_price_stats(sub_id)
    assert stats['count'] == len(prices)
    assert stats['min'] == min(prices)
    assert stats['max'] == max(prices)
    assert stats['current'] == prices[-1]

                                                   
    subs = database.get_user_subscriptions(user_id)
    assert any(s[0] == sub_id for s in subs)

                                                                 
    drops = database.get_top_price_drops(user_id, limit=5)
    assert any(d[0] == sub_id for d in drops)

             
    assert database.remove_subscription(sub_id) is True
                    
    assert database.get_subscription(sub_id) is None


def test_subscription_order_stays_stable_after_price_updates(temp_db_path, monkeypatch):
    user_id = 12345
    first_id = database.add_subscription(
        user_id,
        "https://www.trendyol.com/test-product-a",
        product_title="First product",
    )
    second_id = database.add_subscription(
        user_id,
        "https://www.trendyol.com/test-product-b",
        product_title="Second product",
    )

    monkeypatch.setattr(database.time, "time", lambda: 4102444800)
    database.update_last_price(first_id, 99.0)
    database.update_notify_time(first_id)

    subs = database.get_user_subscriptions(user_id)

    assert [sub[0] for sub in subs] == [second_id, first_id]


def test_paused_subscription_is_skipped_by_background_iterator(temp_db_path):
    user_id = 12345
    active_id = database.add_subscription(
        user_id,
        "https://www.trendyol.com/test-product-active",
        product_title="Active product",
    )
    paused_id = database.add_subscription(
        user_id,
        "https://www.trendyol.com/test-product-paused",
        product_title="Paused product",
    )

    assert database.get_subscription_active(paused_id) is True
    assert database.set_subscription_active(paused_id, False) is True
    assert database.get_subscription_active(paused_id) is False

    active_sub_ids = [row[0] for row in database.iter_all_subscriptions()]

    assert active_id in active_sub_ids
    assert paused_id not in active_sub_ids
    assert database.get_subscriptions_count() == 1

def test_price_history_functions_empty(temp_db_path):
                                                                       
    assert database.get_price_history(9999999) == []
    assert database.get_last_price_point(9999999) is None


def test_delete_user_data_removes_profile_subscriptions_and_history(temp_db_path):
    user_id = 12345
    other_user_id = 67890
    database.add_user_if_not_exists(user_id, language="en")
    database.add_user_if_not_exists(other_user_id, language="ru")

    first_id = database.add_subscription(
        user_id,
        "https://www.trendyol.com/delete-me-a-p-1",
        product_title="Delete me A",
    )
    second_id = database.add_subscription(
        user_id,
        "https://www.trendyol.com/delete-me-b-p-2",
        product_title="Delete me B",
    )
    other_id = database.add_subscription(
        other_user_id,
        "https://www.trendyol.com/keep-me-p-3",
        product_title="Keep me",
    )
    database.add_price_point(first_id, "https://www.trendyol.com/delete-me-a-p-1", 100.0, 1000)
    database.add_price_point(second_id, "https://www.trendyol.com/delete-me-b-p-2", 200.0, 2000)
    database.add_price_point(other_id, "https://www.trendyol.com/keep-me-p-3", 300.0, 3000)

    deleted = database.delete_user_data(user_id)

    assert deleted == {"users": 1, "subscriptions": 2, "price_history": 2}
    assert database.get_user_profile(user_id) is None
    assert database.get_user_subscriptions(user_id) == []
    assert database.get_price_history(first_id) == []
    assert database.get_price_history(second_id) == []
    assert database.get_user_profile(other_user_id) is not None
    assert len(database.get_user_subscriptions(other_user_id)) == 1
    assert len(database.get_price_history(other_id)) == 1


def test_user_access_grant_and_revoke_premium(temp_db_path):
    user_id = 12345

    assert database.get_user_access(user_id) == {
        "access_tier": "free",
        "premium_until": None,
    }

    assert database.grant_user_premium(user_id, premium_until=4102444800) == {
        "access_tier": "premium",
        "premium_until": 4102444800,
    }
    profile = database.get_user_profile(user_id)
    assert profile["access_tier"] == "premium"
    assert profile["premium_until"] == 4102444800

    assert database.revoke_user_premium(user_id) == {
        "access_tier": "free",
        "premium_until": None,
    }


def test_subscription_check_failure_tracking(temp_db_path):
    user_id = 12345
    url = "https://www.trendyol.com/test-product-p-1"
    sub_id = database.add_subscription(user_id, url, product_title="Broken Test")

    assert database.get_broken_subscriptions() == []

    database.record_subscription_check_failure(sub_id, "price_not_found", ts=111)
    database.record_subscription_check_failure(sub_id, "timeout_fetching_product_info", ts=222)

    broken = database.get_broken_subscriptions(limit=10)
    assert len(broken) == 1
    assert broken[0]["id"] == sub_id
    assert broken[0]["check_fail_count"] == 2
    assert broken[0]["last_check_error"] == "timeout_fetching_product_info"
    assert broken[0]["last_check_error_at"] == 222

    by_user = database.get_subscription_check_failures_for_user(user_id)
    assert by_user[sub_id]["check_fail_count"] == 2
    assert by_user[sub_id]["last_check_error"] == "timeout_fetching_product_info"

    database.clear_subscription_check_failure(sub_id)

    assert database.get_broken_subscriptions() == []
    assert database.get_subscription_check_failures_for_user(user_id) == {}


def test_paused_failed_subscription_is_hidden_from_admin_broken_list(temp_db_path):
    user_id = 12345
    sub_id = database.add_subscription(
        user_id,
        "https://www.trendyol.com/test-broken-paused-p-1",
        product_title="Paused Broken Test",
    )

    database.record_subscription_check_failure(sub_id, "price_not_found", ts=111)

    assert [row["id"] for row in database.get_broken_subscriptions(limit=10)] == [sub_id]
    assert database.set_subscription_active(sub_id, False) is True
    assert database.get_broken_subscriptions(limit=10) == []

    details = database.get_subscription_failure_details(sub_id)
    assert details["id"] == sub_id
    assert details["is_active"] == 0
    assert details["check_fail_count"] == 1

