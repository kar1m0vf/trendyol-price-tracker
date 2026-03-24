import pytest
import asyncio
from types import SimpleNamespace
from services.notification_service import NotificationService


class DummyBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, user_id, text):
        self.sent.append(('msg', user_id, text))

    async def send_photo(self, user_id, photo, caption=None):
        self.sent.append(('photo', user_id, photo, caption))


@pytest.mark.asyncio
async def test_send_history_plot_not_enough_data(monkeypatch):
    bot = DummyBot()
    svc = NotificationService(bot)

                                                                                
    hist = [("20.09.2025", 3000.0)]

    await svc.send_history_plot(123, "https://trendyol.com/p-1", hist)

                                                            
    assert any(item[0] == 'msg' for item in bot.sent)


@pytest.mark.asyncio
async def test_send_history_plot_with_matplotlib(monkeypatch):
                                                             
    class DummyPlt:
        class FuncFormatter:
            def __init__(self, fn):
                pass

        def subplots(self, figsize=(10,6)):
            class Fig:
                def __init__(self):
                    pass
            class Ax:
                def plot(self, *a, **k):
                    pass
                def xaxis(self):
                    pass
                def set_title(self, *a, **k):
                    pass
                def set_ylabel(self, *a, **k):
                    pass
                def set_xlabel(self, *a, **k):
                    pass
                def grid(self, *a, **k):
                    pass
            return (Fig(), Ax())

        def FuncFormatter(self, fn):
            return lambda x, p: f"{x:.0f}"

        def tight_layout(self):
            pass

        def close(self, fig):
            pass

                                                                                        
    monkeypatch.setitem(__import__('sys').modules, 'matplotlib.pyplot', DummyPlt())
    monkeypatch.setitem(__import__('sys').modules, 'matplotlib.dates', SimpleNamespace(DateFormatter=lambda f: None, DayLocator=lambda interval: None))

    bot = DummyBot()
    svc = NotificationService(bot)

                                                                                                       
    hist = [("20.09.2025", 3000.0), ("21.09.2025", 2900.0)]

    await svc.send_history_plot(123, "https://trendyol.com/p-1", hist)

                                               
    assert any(item[0] in ('photo', 'msg') for item in bot.sent)
