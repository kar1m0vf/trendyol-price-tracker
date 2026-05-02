from types import SimpleNamespace

from user_texts import format_start_text


def test_format_start_text_uses_first_name():
    user = SimpleNamespace(first_name="Karim", username="karim")
    translations = {
        "start_text_named": "Hi, {name}!",
        "start_text": "Hi!",
    }

    text = format_start_text(123, user, lambda _uid, key: translations[key])

    assert text == "Hi, Karim!"


def test_format_start_text_escapes_markdown_name():
    user = SimpleNamespace(first_name="A_B*Test", username=None)
    translations = {
        "start_text_named": "Hi, {name}!",
        "start_text": "Hi!",
    }

    text = format_start_text(123, user, lambda _uid, key: translations[key])

    assert text == "Hi, A\\_B\\*Test!"


def test_format_start_text_falls_back_without_name():
    user = SimpleNamespace(first_name="", username=None)
    translations = {
        "start_text_named": "Hi, {name}!",
        "start_text": "Hi!",
    }

    text = format_start_text(123, user, lambda _uid, key: translations[key])

    assert text == "Hi!"
