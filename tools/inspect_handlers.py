import importlib
import sys
from pathlib import Path
from pprint import pprint

                                    
ROOT = str(Path(__file__).resolve().parents[1])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

bot = importlib.import_module('bot')
print('Imported bot module')
print('Dispatcher:', bot.dp)

mh = getattr(bot.dp, 'message', None)
if mh is None:
    print('No message observer')
else:
    handlers = getattr(mh, 'handlers', None)
    print('Handlers count:', len(handlers) if handlers is not None else None)
    if handlers:
        for i, h in enumerate(handlers):
            print('--- Handler', i)
                                                                        
            for attr in ('func', 'callback', 'handler', 'filters', 'filters_chain'):
                if hasattr(h, attr):
                    print('  ', attr, '=>', getattr(h, attr))
                            
            print('  repr:', repr(h))

                                           
names = [n for n in dir(bot) if n.lower().startswith('cmd_') or n.lower().startswith('handle_')]
print('Possible handler function names in bot module:', names)

                                                   
for n in names:
    try:
        obj = getattr(bot, n)
        print(n, '->', getattr(obj, '__name__', str(obj)))
    except Exception:
        pass
