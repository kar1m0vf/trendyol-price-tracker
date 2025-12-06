import asyncio
import logging
import sys
import os

# Ensure project root is on sys.path so local imports work when running from tools/
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scraper import get_price_history_from_akakce_async, get_price_history_from_trendyol_async

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('test')

URLS = [
    "https://www.trendyol.com/cream-co/su-bazli-moisturizer-nemlendirici-aydinlatici-yuz-kremi-hyaluronik-asit-50-ml-tum-cilt-tipleri-p-318291787",
    "https://www.trendyol.com/roborock/q8-akilli-robot-supurge-siyah-10-000-pa-hyperforce-emis-gucu-p-944315539?boutiqueId=678155&merchantId=968",
]

async def run():
    for url in URLS:
        print('\n--- Testing URL:', url)
        try:
            print('\nTry Akakce fallback...')
            hist = await get_price_history_from_akakce_async(url)
            print('Akakce result:', hist)
        except Exception as e:
            print('Akakce exception:', e)

        try:
            print('\nTry Trendyol direct...')
            hist2 = await get_price_history_from_trendyol_async(url)
            print('Trendyol result:', hist2)
        except Exception as e:
            print('Trendyol exception:', e)

if __name__ == '__main__':
    asyncio.run(run())
