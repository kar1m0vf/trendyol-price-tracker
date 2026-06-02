import pytest


@pytest.fixture(autouse=True)
def clear_heavy_command_rate_limit_state():
    try:
        import bot
        from services.trending_service import TREND_SEARCH_AWAIT, TRENDING_RESULT_CACHE
    except Exception:
        yield
        return

    bot.heavy_command_last_used.clear()
    TREND_SEARCH_AWAIT.clear()
    TRENDING_RESULT_CACHE.clear()
    yield
    bot.heavy_command_last_used.clear()
    TREND_SEARCH_AWAIT.clear()
    TRENDING_RESULT_CACHE.clear()
