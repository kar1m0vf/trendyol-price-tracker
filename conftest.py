                                                                              
pytest_plugins = ["pytest_asyncio"]

                                                         

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

