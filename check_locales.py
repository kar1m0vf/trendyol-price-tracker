"""
Check localization files for missing keys and duplicate keys.
"""

import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

LOCALES_DIR = Path(__file__).parent / "locales"
LANGUAGES = ["ru", "en", "az", "tr"]


def load_locale(lang: str) -> tuple[dict, list[str]]:
    """Load locale file and collect duplicate keys before JSON overwrites them."""
    filepath = LOCALES_DIR / f"{lang}.json"
    duplicates: list[str] = []

    def object_pairs_hook(pairs):
        data = {}
        seen = set()
        for key, value in pairs:
            if key in seen:
                duplicates.append(key)
            seen.add(key)
            data[key] = value
        return data

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f, object_pairs_hook=object_pairs_hook)

    return data, duplicates


def main():
    print("=" * 70)
    print("LOCALIZATION FILES CHECK")
    print("=" * 70)

    locales = {}
    duplicate_issues = {}
    for lang in LANGUAGES:
        locale_data, duplicates = load_locale(lang)
        locales[lang] = locale_data
        if duplicates:
            duplicate_issues[lang] = sorted(set(duplicates))

    all_keys_set = set()
    for lang_data in locales.values():
        all_keys_set.update(lang_data.keys())

    all_keys = sorted(all_keys_set)

    print(f"\nTotal unique keys: {len(all_keys)}\n")

    if duplicate_issues:
        print("DUPLICATE KEYS")
        for lang, duplicates in duplicate_issues.items():
            print(f"  {lang.upper()}: {len(duplicates)} duplicate key(s)")
            for key in duplicates:
                print(f"   - {key}")
        print()

    missing_issues = {}
    for lang in LANGUAGES:
        lang_data = locales[lang]
        missing = all_keys_set - set(lang_data.keys())

        if missing:
            missing_issues[lang] = list(missing)
            print(f"\n[FAIL] {lang.upper()}: Missing {len(missing)} key(s):")
            for key in sorted(missing)[:10]:
                print(f"   - {key}")
            if len(missing) > 10:
                print(f"   ... and {len(missing) - 10} more")
        else:
            print(f"[OK] {lang.upper()}: All keys present ({len(lang_data)} keys)")

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    for lang in LANGUAGES:
        count = len(locales[lang])
        print(f"  {lang.upper()}: {count} keys", end="")
        parts = []
        if lang in missing_issues:
            parts.append(f"Missing: {len(missing_issues[lang])}")
        if lang in duplicate_issues:
            parts.append(f"Duplicates: {len(duplicate_issues[lang])}")
        if parts:
            print(f" [FAIL] {', '.join(parts)}")
        else:
            print(" [OK]")

    if missing_issues:
        print("\n" + "=" * 70)
        print("MISSING KEYS BY LANGUAGE")
        print("=" * 70)

        for key in all_keys:
            langs_missing = [lang for lang in LANGUAGES if key not in locales[lang]]
            if langs_missing:
                print(f"\n{key}:")
                print(f"  Missing in: {', '.join(langs_missing)}")

    return 0 if not missing_issues and not duplicate_issues else 1


if __name__ == "__main__":
    sys.exit(main())
