#!/usr/bin/env python3
import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Callable, Dict, List, Tuple


BASE_DIR = Path(__file__).resolve().parents[2]

REQUIRED_FILES = [
    "bot.py",
    "config.py",
    "database.py",
    "scraper.py",
    "middleware.py",
    "keyboards.py",
    "utils.py",
    ".env.example",
]

REQUIRED_LOCALES = ("ru", "en", "az", "tr")

REQUIRED_COMMANDS = {
    "start",
    "help",
    "mysubs",
    "compare",
    "recommend",
    "settings",
    "language",
    "history",
    "alerts",
    "stats",
    "export",
    "about",
    "terms",
    "privacy",
    "support",
    "delete_me",
    "ping",
    "health",
    "bad_subs",
}


class CheckError(RuntimeError):
    pass


def _ok(msg: str) -> None:
    print(f"[OK] {msg}")


def _fail(msg: str) -> None:
    print(f"[FAIL] {msg}")


def _warn(msg: str) -> None:
    print(f"[WARN] {msg}")


def check_required_files() -> None:
    missing = [p for p in REQUIRED_FILES if not (BASE_DIR / p).exists()]
    if missing:
        raise CheckError(f"Missing required files: {', '.join(missing)}")
    _ok(f"Required files are present ({len(REQUIRED_FILES)})")


def check_env_and_token() -> None:
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        raise CheckError(".env is missing")

    env_text = env_path.read_text(encoding="utf-8", errors="ignore")
    token_line = None
    for raw_line in env_text.splitlines():
        line = raw_line.strip()
        if line.startswith("BOT_TOKEN="):
            token_line = line
            break

    if token_line is None:
        raise CheckError("BOT_TOKEN is missing in .env")

    token = token_line.split("=", 1)[1].strip()
    if not token:
        raise CheckError("BOT_TOKEN is empty")

    token_pattern = re.compile(r"^\d{8,10}:[A-Za-z0-9_-]{35}$")
    if not token_pattern.match(token):
        raise CheckError("BOT_TOKEN format looks invalid")

    _ok("BOT_TOKEN is present and matches Telegram format")


def check_config_import() -> None:
    sys.path.insert(0, str(BASE_DIR))
    try:
        from config import BOT_TOKEN, DATABASE_PATH, _check_bot_token
    except Exception as exc:
        raise CheckError(f"config import failed: {exc}") from exc

    if not BOT_TOKEN:
        raise CheckError("config.BOT_TOKEN is empty after import")

    if not DATABASE_PATH:
        raise CheckError("config.DATABASE_PATH is empty after import")

    try:
        _check_bot_token()
    except Exception as exc:
        raise CheckError(f"config token validation failed: {exc}") from exc

    _ok("config import and token validation passed")


def check_database_readiness() -> None:
    sys.path.insert(0, str(BASE_DIR))
    try:
        from config import DATABASE_PATH
        from database import get_subscriptions_count, init_db
    except Exception as exc:
        raise CheckError(f"database import failed: {exc}") from exc

    db_path = Path(DATABASE_PATH)
    db_full = db_path if db_path.is_absolute() else (BASE_DIR / db_path)
    db_full.parent.mkdir(parents=True, exist_ok=True)

    init_db(run_maintenance=False)
    _ = get_subscriptions_count()

    with sqlite3.connect(str(db_full), timeout=5) as conn:
        res = conn.execute("PRAGMA quick_check").fetchone()
    if not res or res[0] != "ok":
        raise CheckError(f"PRAGMA quick_check failed: {res}")

    _ok(f"database is reachable and healthy ({db_full})")


def check_locales() -> None:
    locale_sets: Dict[str, set] = {}
    for lang in REQUIRED_LOCALES:
        p = BASE_DIR / "locales" / f"{lang}.json"
        if not p.exists():
            raise CheckError(f"locale file is missing: {p}")
        data = json.loads(p.read_text(encoding="utf-8"))
        locale_sets[lang] = set(data.keys())

    base_lang = REQUIRED_LOCALES[0]
    base_keys = locale_sets[base_lang]
    for lang in REQUIRED_LOCALES[1:]:
        missing = sorted(base_keys - locale_sets[lang])
        extra = sorted(locale_sets[lang] - base_keys)
        if missing or extra:
            raise CheckError(
                f"locale key mismatch for {lang}: missing={len(missing)}, extra={len(extra)}"
            )

    _ok(f"locale keysets are aligned ({len(base_keys)} keys)")


def check_command_coverage() -> None:
    source_files = [BASE_DIR / "bot.py"]
    source_files.extend((BASE_DIR / "handlers").glob("*.py"))
    text = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for p in source_files
        if p.exists()
    )
    found = set(re.findall(r'Command\("([^"]+)"\)', text))

    missing = sorted(REQUIRED_COMMANDS - found)
    if missing:
        raise CheckError(
            "required commands are not registered in bot.py/handlers: "
            + ", ".join(missing)
        )

    _ok(f"required command coverage looks good ({len(REQUIRED_COMMANDS)})")


def check_runtime_artifacts_dirs() -> None:
    for rel in ("logs", "backups"):
        p = BASE_DIR / rel
        p.mkdir(parents=True, exist_ok=True)
        probe = p / ".write_test"
        try:
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
        except Exception as exc:
            raise CheckError(f"directory is not writable: {p} ({exc})") from exc
    _ok("logs/ and backups/ are writable")


def check_secret_patterns_in_docs() -> None:
    docs = BASE_DIR / "docs"
    if not docs.exists():
        _warn("docs/ is missing, skip secret pattern scan")
        return

    pattern = re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b")
    hits: List[str] = []
    for p in docs.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in {".md", ".txt"}:
            continue
        txt = p.read_text(encoding="utf-8", errors="ignore")
        if pattern.search(txt):
            hits.append(str(p.relative_to(BASE_DIR)))

    if hits:
        raise CheckError("token-like pattern found in docs: " + ", ".join(hits))

    _ok("no token-like patterns detected in docs")


def main() -> int:
    print("=== Deploy Smoke Check ===")
    checks: List[Tuple[str, Callable[[], None]]] = [
        ("required files", check_required_files),
        (".env and BOT_TOKEN", check_env_and_token),
        ("config import", check_config_import),
        ("database readiness", check_database_readiness),
        ("locales consistency", check_locales),
        ("command coverage", check_command_coverage),
        ("artifact directories", check_runtime_artifacts_dirs),
        ("docs secrets scan", check_secret_patterns_in_docs),
    ]

    failed = 0
    for name, fn in checks:
        print(f"- {name}")
        try:
            fn()
        except CheckError as exc:
            failed += 1
            _fail(str(exc))
        except Exception as exc:
            failed += 1
            _fail(f"unexpected error: {exc}")

    print("==========================")
    if failed:
        _fail(f"Smoke check finished with {failed} failed check(s)")
        return 1

    _ok("Smoke check passed")
    print("Manual post-deploy checks: see docs/guides/DEPLOY_SMOKE_CHECKLIST.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
