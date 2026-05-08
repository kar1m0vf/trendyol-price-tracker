from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_activity_log_middleware_logs_received_and_success():
    from middleware import ActivityLogMiddleware

    event = SimpleNamespace(
        from_user=SimpleNamespace(id=12345, username="karim", first_name="Karim"),
        chat=SimpleNamespace(id=12345),
        text="/start",
    )
    handler = AsyncMock(return_value="ok")
    middleware = ActivityLogMiddleware(enabled=True, log_success=True)

    with patch("middleware.action_event") as action_event:
        result = await middleware(handler, event, {})

    assert result == "ok"
    assert action_event.call_count == 2
    assert action_event.call_args_list[0].args[:2] == ("IN", "message received")
    assert action_event.call_args_list[1].args[:2] == ("OK", "message handled")
    assert action_event.call_args_list[0].kwargs["command"] == "/start"


@pytest.mark.asyncio
async def test_activity_log_middleware_logs_errors_and_reraises():
    from middleware import ActivityLogMiddleware

    event = SimpleNamespace(
        from_user=SimpleNamespace(id=12345, username="karim", first_name="Karim"),
        chat=SimpleNamespace(id=12345),
        text="hello",
    )
    handler = AsyncMock(side_effect=RuntimeError("boom"))
    middleware = ActivityLogMiddleware(enabled=True, log_success=True)

    with patch("middleware.action_event") as action_event:
        with pytest.raises(RuntimeError):
            await middleware(handler, event, {})

    assert action_event.call_count == 2
    assert action_event.call_args_list[0].args[:2] == ("IN", "message received")
    assert action_event.call_args_list[1].args[:2] == ("ERROR", "message failed")
    assert action_event.call_args_list[1].kwargs["error"] == "RuntimeError"
