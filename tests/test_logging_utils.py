from types import SimpleNamespace

from logging_utils import actor_label, short_value


def test_actor_label_prefers_id_and_username():
    user = SimpleNamespace(id=12345, username="karim", first_name="Karim", last_name="Test")

    assert actor_label(user) == "12345 @karim"


def test_actor_label_falls_back_to_name():
    user = SimpleNamespace(id=12345, username=None, first_name="Karim", last_name="Test")

    assert actor_label(user) == "12345 Karim Test"


def test_short_value_single_line_truncates():
    assert short_value("hello\nworld", 20) == "hello world"
    assert short_value("x" * 20, 10) == "xxxxxxx..."
