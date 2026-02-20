"""
Localization utilities.
Separated from bot.py to avoid circular imports.
"""
import json
import logging
import time
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Load locales
def load_locale(lang_code: str) -> dict:
    try:
        with open(f"locales/{lang_code}.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("Locale load failed for %s: %s", lang_code, e)
        return {}

LOCALES = {
    "ru": load_locale("ru"),
    "en": load_locale("en"),
    "az": load_locale("az"),
    "tr": load_locale("tr")
}
_lang_cache: dict = {}
_LANG_CACHE_TTL = 60  # seconds

def _get_user_language_cached(user_id: int) -> str:
    """Return cached user language or query DB and cache result."""
    try:
        now = int(time.time())
    except Exception:
        now = 0

    entry = _lang_cache.get(user_id)
    if entry:
        lang, ts = entry
        if now - ts < _LANG_CACHE_TTL:
            return lang

    try:
        from database import get_user_language
        lang = get_user_language(user_id) or "en"
    except Exception:
        lang = "en"

    _lang_cache[user_id] = (lang, now)
    return lang


def t(user_id: int, key: str, **kwargs) -> str:
    """Translate text for user with optional formatting.

    Uses a short in-memory cache for user language to avoid DB lookup on every call.
    """
    lang = _get_user_language_cached(user_id)

    # If user's lang not supported, fall back to English
    if lang not in LOCALES:
        logger.debug("User lang '%s' not supported, falling back to 'en'", lang)
        lang = "en"

    loc = LOCALES.get(lang, {})
    text = loc.get(key)
    if text is None:
        # fallback to English
        en_loc = LOCALES.get("en", {})
        text = en_loc.get(key)
        if text is not None:
            logger.debug("Localization fallback: key='%s' lang='%s' -> 'en'", key, lang)
        else:
            # ultimate fallback: return key (but log once)
            logger.warning("Missing localization key '%s' for lang '%s' and 'en' fallback", key, lang)
            text = key

    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, ValueError):
            logger.exception("Localization formatting failed for key='%s' lang='%s' kwargs=%r", key, lang, kwargs)
            # return unformatted text to avoid crashing

    return text

def update_language_cache(user_id: int, language: str) -> None:
    """Update language cache for specific user with new language."""
    try:
        now = int(time.time())
    except Exception:
        now = 0

    _lang_cache[user_id] = (language, now)
    logger.debug("Language cache updated for user %s: %s", user_id, language)

def clear_language_cache(user_id: int) -> None:
    """Clear language cache for specific user."""
    if user_id in _lang_cache:
        del _lang_cache[user_id]
        logger.debug("Language cache cleared for user %s", user_id)

def get_user_language_safe(user_id: int) -> str:
    """Get user's language preference safely."""
    try:
        from database import get_user_language
        return get_user_language(user_id) or "en"
    except Exception as e:
        logger.exception("get_user_language_safe failed for user %s: %s", user_id, e)
        return "en"









