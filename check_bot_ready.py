"""
Readiness check script for bot startup.
Checks only critical local prerequisites.
"""

import sys
from pathlib import Path


def check_env_file() -> bool:
    env_path = Path(".env")
    if not env_path.exists():
        print("FAIL: .env file not found")
        return False

    content = env_path.read_text(encoding="utf-8", errors="ignore")
    if "BOT_TOKEN=" not in content:
        print("FAIL: BOT_TOKEN is missing in .env")
        return False

    print("OK: .env file found and BOT_TOKEN is present")
    return True


def check_dotenv_installed() -> bool:
    try:
        import dotenv  # noqa: F401
        print("OK: python-dotenv is installed")
        return True
    except ImportError:
        print("FAIL: python-dotenv is not installed")
        print("Hint: pip install python-dotenv")
        return False


def check_config_import() -> bool:
    try:
        from config import BOT_TOKEN  # noqa: F401
        print(f"OK: config.py import succeeded (BOT_TOKEN loaded: {bool(BOT_TOKEN)})")
        return bool(BOT_TOKEN)
    except Exception as exc:
        print(f"FAIL: config.py import failed: {exc}")
        return False


def check_token_validation() -> bool:
    try:
        from config import _check_bot_token
        _check_bot_token()
        print("OK: BOT_TOKEN validation passed")
        return True
    except Exception as exc:
        print(f"FAIL: BOT_TOKEN validation failed: {exc}")
        return False


def check_bot_initialization() -> bool:
    try:
        from bot import create_app, router, check_all  # noqa: F401
        if not callable(create_app):
            raise RuntimeError("create_app is not callable")
        if router is None:
            raise RuntimeError("router is not available")
        print("OK: bot.py imported, runtime factory and router handlers are available")
        return True
    except Exception as exc:
        print(f"FAIL: bot.py initialization failed: {exc}")
        return False


def check_database() -> bool:
    try:
        from database import init_db, get_user_settings, update_user_settings, save_price_point  # noqa: F401
        print("OK: database.py imported and critical functions are available")
        return True
    except Exception as exc:
        print(f"FAIL: database import failed: {exc}")
        return False


def main() -> int:
    print("=" * 60)
    print("Bot readiness check")
    print("=" * 60)

    checks = [
        ("env file", check_env_file),
        ("python-dotenv", check_dotenv_installed),
        ("config import", check_config_import),
        ("token validation", check_token_validation),
        ("bot init", check_bot_initialization),
        ("database import", check_database),
    ]

    passed = 0
    for name, fn in checks:
        print(f"\nCheck: {name}")
        try:
            if fn():
                passed += 1
        except Exception as exc:
            print(f"FAIL: unexpected error in '{name}': {exc}")

    print("\n" + "=" * 60)
    print(f"Result: {passed}/{len(checks)} checks passed")

    if passed == len(checks):
        print("SUCCESS: bot is ready to start")
        print("Run: python bot.py")
        return 0

    print("FAILURE: fix issues above before deployment")
    return 1


if __name__ == "__main__":
    sys.exit(main())
