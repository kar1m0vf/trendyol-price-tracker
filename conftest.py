# Ensure pytest-asyncio plugin is loaded and provide common fixtures if needed
pytest_plugins = ["pytest_asyncio"]

# You can add shared fixtures here if tests require setup

import gc
import asyncio
import warnings

import aiohttp


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
			# No running loop in this context; create a temporary one
			loop = asyncio.new_event_loop()
			asyncio.set_event_loop(loop)

		sessions = [obj for obj in gc.get_objects() if isinstance(obj, aiohttp.ClientSession)]
		for sess in sessions:
			try:
				if not sess.closed:
					loop.run_until_complete(sess.close())
			except Exception:
				# Best-effort cleanup; ignore failures
				pass
	except Exception:
		pass


def pytest_sessionfinish(session, exitstatus):
	# Ensure any aiohttp sessions are closed to avoid noisy warnings
	_close_aiohttp_sessions()

