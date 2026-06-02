from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_database_backup_uses_configured_backup_dir(tmp_path, monkeypatch):
    from handlers import admin_handler

    backup_dir = tmp_path / "configured-backups"

    def fake_create_sqlite_backup(path: str) -> None:
        Path(path).write_bytes(b"sqlite backup")

    monkeypatch.setattr(admin_handler, "BACKUP_DIR", str(backup_dir))
    monkeypatch.setattr(admin_handler, "DB_BACKUP_KEEP_FILES", 7)
    monkeypatch.setattr(admin_handler, "create_sqlite_backup", fake_create_sqlite_backup)

    result = await admin_handler._create_database_backup(trigger="test")

    backup_path = Path(result["path"])
    assert backup_path.parent == backup_dir
    assert backup_path.exists()
    assert result["retained"] == 1
