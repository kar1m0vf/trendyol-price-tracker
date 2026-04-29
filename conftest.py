pytest_plugins = ["pytest_asyncio"]

import gc
import asyncio
import os
import sys
from pathlib import Path

import aiohttp

ROOT = Path(__file__).resolve().parent
ARTIFACTS_DIR = ROOT / "artifacts"
ARTIFACTS_DIR.mkdir(exist_ok=True)

if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

os.environ.setdefault("BOT_TOKEN", "1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")
os.environ.setdefault("ADMIN_IDS", "975282591")
os.environ.setdefault("DATABASE_PATH", str(ARTIFACTS_DIR / "pytest_trendyol_bot.db"))


def pytest_sessionstart(session):
	try:
		from database import init_db

		init_db(run_maintenance=False)
	except Exception as exc:
		raise RuntimeError(f"Failed to initialize test database: {exc}") from exc


def _close_aiohttp_sessions():
	"""Try to close any leftover aiohttp.ClientSession instances found by GC.

	This helps avoid 'Unclosed client session' warnings in test runs when
	some code creates sessions but doesn't close them properly.
	"""
	try:
		loop = None
		try:
			loop = asyncio.get_event_loop()
		except RuntimeError:
                                                            
			loop = asyncio.new_event_loop()
			asyncio.set_event_loop(loop)

		sessions = [obj for obj in gc.get_objects() if isinstance(obj, aiohttp.ClientSession)]
		for sess in sessions:
			try:
				if not sess.closed:
					loop.run_until_complete(sess.close())
			except Exception:
                                          
				pass
	except Exception:
		pass


def pytest_sessionfinish(session, exitstatus):
                                                                 
	_close_aiohttp_sessions()

