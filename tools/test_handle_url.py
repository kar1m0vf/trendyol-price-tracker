import asyncio, importlib, sys
from pathlib import Path
# Ensure project root on sys.path
ROOT = str(Path(__file__).resolve().parents[1])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
bot = importlib.import_module('bot')

class FakeUser:
    def __init__(self, id):
        self.id = id

class FakeMessage:
    def __init__(self, text, user_id=111111):
        self.text = text
        self.from_user = FakeUser(user_id)
    async def answer(self, *args, **kwargs):
        print('answer called with', args[:1])

msg = FakeMessage('https://www.trendyol.com/apple/iphone-16-p-857296077')
asyncio.run(bot.handle_url(msg))
