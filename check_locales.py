#!/usr/bin/env python3
"""
Script to check localization files for missing keys and differences.
"""
import json
import sys
from pathlib import Path

LOCALES_DIR = Path(__file__).parent / "locales"
LANGUAGES = ["ru", "en", "az", "tr"]

def load_locale(lang: str) -> dict:
    """Load locale file."""
    filepath = LOCALES_DIR / f"{lang}.json"
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)

def main():
    print("=" * 70)
    print("LOCALIZATION FILES CHECK")
    print("=" * 70)
    
    # Load all locales
    locales = {lang: load_locale(lang) for lang in LANGUAGES}
    
    # Get all keys from all locales
    all_keys_set = set()
    for lang_data in locales.values():
        all_keys_set.update(lang_data.keys())
    
    all_keys = sorted(list(all_keys_set))
    
    print(f"\nTotal unique keys: {len(all_keys)}\n")
    
    # Check each language
    issues = {}
    for lang in LANGUAGES:
        lang_data = locales[lang]
        missing = all_keys_set - set(lang_data.keys())
        
        if missing:
            issues[lang] = list(missing)
            print(f"\n🔴 {lang.upper()}: Missing {len(missing)} key(s):")
            for key in sorted(missing)[:10]:  # Show first 10
                print(f"   - {key}")
            if len(missing) > 10:
                print(f"   ... and {len(missing) - 10} more")
        else:
            print(f"✅ {lang.upper()}: All keys present ({len(lang_data)} keys)")
    
    # Print summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    for lang in LANGUAGES:
        count = len(locales[lang])
        print(f"  {lang.upper()}: {count} keys", end="")
        if lang in issues:
            print(f" ❌ Missing: {len(issues[lang])}")
        else:
            print(" ✅")
    
    # Show which keys are missing in which languages
    if issues:
        print("\n" + "=" * 70)
        print("MISSING KEYS BY LANGUAGE")
        print("=" * 70)
        
        for key in all_keys:
            langs_missing = [lang for lang in LANGUAGES if key not in locales[lang]]
            if langs_missing:
                print(f"\n{key}:")
                print(f"  Missing in: {', '.join(langs_missing)}")
    
    return 0 if not issues else 1

if __name__ == "__main__":
    sys.exit(main())
