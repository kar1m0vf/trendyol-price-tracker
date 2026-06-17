"""Apply localized Telegram bot profile texts.

By default this script only prints the texts that would be sent. Use --apply to
update the live bot through Telegram Bot API.
"""

from __future__ import annotations

import argparse
import sys
from typing import Iterable

import requests

from config import BOT_TOKEN
from localization import LOCALES


DESCRIPTION_KEY = "bot_profile_description"
SHORT_DESCRIPTION_KEY = "bot_profile_short_description"
DESCRIPTION_LIMIT = 512
SHORT_DESCRIPTION_LIMIT = 120
LANGUAGES = ("en", "ru", "az", "tr")
DEFAULT_LANGUAGE = "en"


def _locale_text(lang: str, key: str) -> str:
    text = str(LOCALES.get(lang, {}).get(key, "")).strip()
    if not text:
        raise ValueError(f"Missing locale text: lang={lang} key={key}")
    return text


def validate_profile_texts(languages: Iterable[str] = LANGUAGES) -> None:
    errors: list[str] = []
    for lang in languages:
        description = _locale_text(lang, DESCRIPTION_KEY)
        short_description = _locale_text(lang, SHORT_DESCRIPTION_KEY)
        if len(description) > DESCRIPTION_LIMIT:
            errors.append(
                f"{lang}:{DESCRIPTION_KEY} is {len(description)} chars, max {DESCRIPTION_LIMIT}"
            )
        if len(short_description) > SHORT_DESCRIPTION_LIMIT:
            errors.append(
                f"{lang}:{SHORT_DESCRIPTION_KEY} is {len(short_description)} chars, "
                f"max {SHORT_DESCRIPTION_LIMIT}"
            )
    if errors:
        raise ValueError("\n".join(errors))


def iter_profile_payloads(languages: Iterable[str] = LANGUAGES):
    default_description = _locale_text(DEFAULT_LANGUAGE, DESCRIPTION_KEY)
    default_short_description = _locale_text(DEFAULT_LANGUAGE, SHORT_DESCRIPTION_KEY)
    yield None, default_description, default_short_description

    for lang in languages:
        yield (
            lang,
            _locale_text(lang, DESCRIPTION_KEY),
            _locale_text(lang, SHORT_DESCRIPTION_KEY),
        )


def _post_telegram_method(method: str, payload: dict) -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set")

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    response = requests.post(url, json=payload, timeout=20)
    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(f"{method} returned non-JSON response: HTTP {response.status_code}") from exc

    if not data.get("ok"):
        description = data.get("description") or response.text
        raise RuntimeError(f"{method} failed: HTTP {response.status_code}: {description}")


def apply_profile_texts(*, dry_run: bool) -> None:
    validate_profile_texts()

    for language_code, description, short_description in iter_profile_payloads():
        label = language_code or "default"
        if dry_run:
            print(f"[DRY-RUN] {label}: description={len(description)} chars")
            print(description)
            print(f"[DRY-RUN] {label}: short_description={len(short_description)} chars")
            print(short_description)
            print()
            continue

        description_payload = {"description": description}
        short_description_payload = {"short_description": short_description}
        if language_code:
            description_payload["language_code"] = language_code
            short_description_payload["language_code"] = language_code

        _post_telegram_method("setMyDescription", description_payload)
        _post_telegram_method("setMyShortDescription", short_description_payload)
        print(f"[OK] Applied profile texts for {label}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Set localized Telegram bot profile texts.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Update the live Telegram bot. Without this flag only a dry-run is printed.",
    )
    args = parser.parse_args(argv)

    apply_profile_texts(dry_run=not args.apply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
