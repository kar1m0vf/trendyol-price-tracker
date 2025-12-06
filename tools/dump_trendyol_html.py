import sys
import os
from urllib.parse import urlparse

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scraper import SCRAPER, HEADERS
import requests


def fetch(url: str) -> str:
    try:
        if SCRAPER is not None:
            r = SCRAPER.get(url, headers=HEADERS, timeout=20)
        else:
            r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        return r.text
    except Exception as e:
        print('fetch error', e)
        return ''


def save(url: str, content: str):
    netloc = urlparse(url).netloc.replace(':', '_')
    path = urlparse(url).path.strip('/').replace('/', '_')
    if not path:
        path = 'index'
    fname = f"tools/html_{netloc}_{path}.html"
    with open(fname, 'w', encoding='utf-8') as f:
        f.write(content)
    print('Saved', fname)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python tools/dump_trendyol_html.py <url> [<url2> ...]')
        sys.exit(1)
    for u in sys.argv[1:]:
        print('Fetching', u)
        html = fetch(u)
        save(u, html)
