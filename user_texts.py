from typing import Any, Callable


def _display_name_from_user(user: Any) -> str:
    if user is None:
        return ""
    first_name = (getattr(user, "first_name", None) or "").strip()
    if first_name:
        return first_name
    username = (getattr(user, "username", None) or "").strip()
    return f"@{username}" if username else ""


def _escape_markdown(value: str) -> str:
    escaped = value.replace("\\", "\\\\")
    for char in ("_", "*", "`", "["):
        escaped = escaped.replace(char, f"\\{char}")
    return escaped


def format_start_text(user_id: int, user: Any, translate: Callable[[int, str], str]) -> str:
    name = _display_name_from_user(user)
    if not name:
        return translate(user_id, "start_text")

    try:
        template = translate(user_id, "start_text_named")
    except Exception:
        return translate(user_id, "start_text")

    return template.format(name=_escape_markdown(name))
