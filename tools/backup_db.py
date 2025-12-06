"""
Simple DB backup script: copies `trendyol_bot.db` into `backups/` with timestamp.
Run: python tools/backup_db.py
"""
import os
import shutil
from datetime import datetime

DB = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'trendyol_bot.db')
BACKUP_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'backups')

os.makedirs(BACKUP_DIR, exist_ok=True)

if not os.path.exists(DB):
    print(f"DB not found at {DB}")
    raise SystemExit(1)

ts = datetime.now().strftime('%Y%m%d_%H%M%S')
backup_name = f"db_backup_{ts}.db"
backup_path = os.path.join(BACKUP_DIR, backup_name)

shutil.copy2(DB, backup_path)
print(f"Backup created: {backup_path}")
