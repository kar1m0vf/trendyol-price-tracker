import requests
from bs4 import BeautifulSoup
import re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.trendyol.com/",
}


def extract_listing_ids(html):
    ids = set()
    # ищем все listingId поля в HTML
    for m in re.finditer(r'"listingId"\s*:\s*"([0-9a-f]{16,32})"', html, flags=re.I):
        ids.add(m.group(1))
    # также ищем itemNumber/listing patterns
    for m in re.finditer(r'listingId\s*[:=]\s*"([0-9a-f]{16,32})"', html, flags=re.I):
        ids.add(m.group(1))
    return list(ids)


def try_with_session(url):
    s = requests.Session()
    r = s.get(url, headers=HEADERS, timeout=15)
    print('Status page:', r.status_code)
    ids = extract_listing_ids(r.text)
    print('Found listing ids:', ids[:10])
    # Try calling santral with cookies and headers
    api = 'https://apigw.trendyol.com/discovery-pdp-websfxpricehistory-santral'
    for lid in ids[:10]:
        params = {'listingId': lid}
        h = dict(HEADERS)
        h.update({
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'Origin': 'https://www.trendyol.com',
            'X-Requested-With': 'XMLHttpRequest'
        })
        print('Calling GET', api, 'with', params)
        rg = s.get(api, params=params, headers=h, timeout=15)
        print('GET', rg.status_code, rg.headers.get('content-type'))
        try:
            print('Body snippet:', rg.text[:200])
        except Exception as e:
            print('Could not print body', e)
        print('Calling POST')
        rp = s.post(api, json={'listingId': lid}, headers=h, timeout=15)
        print('POST', rp.status_code, rp.headers.get('content-type'))
        print('Body snippet:', rp.text[:200])
        print('---')


if __name__ == '__main__':
    urls = [
        'https://www.trendyol.com/cream-co/su-bazli-moisturizer-nemlendirici-aydinlatici-yuz-kremi-hyaluronik-asit-50-ml-tum-cilt-tipleri-p-318291787',
        'https://www.trendyol.com/roborock/q8-akilli-robot-supurge-siyah-10-000-pa-hyperforce-emis-gucu-p-944315539'
    ]
    for u in urls:
        print('====', u)
        try:
            try_with_session(u)
        except Exception as e:
            print('Error', e)
