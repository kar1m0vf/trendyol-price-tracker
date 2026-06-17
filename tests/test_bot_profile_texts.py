from tools.set_bot_profile_texts import (
    DESCRIPTION_LIMIT,
    LANGUAGES,
    SHORT_DESCRIPTION_LIMIT,
    iter_profile_payloads,
    validate_profile_texts,
)


def test_bot_profile_texts_fit_telegram_limits():
    validate_profile_texts()

    payloads = list(iter_profile_payloads())
    assert [language_code for language_code, _desc, _short in payloads] == [
        None,
        *LANGUAGES,
    ]
    for language_code, description, short_description in payloads:
        assert description.strip()
        assert short_description.strip()
        assert len(description) <= DESCRIPTION_LIMIT, language_code
        assert len(short_description) <= SHORT_DESCRIPTION_LIMIT, language_code
