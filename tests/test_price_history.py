import asyncio
import logging
from scraper import get_price_history_from_trendyol_async

logging.basicConfig(level=logging.DEBUG)

async def run_test():
                                                       
    test_urls = [
        "https://www.trendyol.com/cream-co/su-bazli-moisturizer-nemlendirici-aydinlatici-yuz-kremi-hyaluronik-asit-50-ml-tum-cilt-tipleri-p-318291787",
        "https://www.trendyol.com/roborock/q8-akilli-robot-supurge-siyah-10-000-pa-hyperforce-emis-gucu-p-944315539"
    ]
    
    for url in test_urls:
        print(f"\n{'='*60}")
        print(f"Тестирую: {url}")
        print('='*60)
        
        try:
            hist = await get_price_history_from_trendyol_async(url)
        except Exception as e:
            print("Ошибка вызова get_price_history_from_trendyol_async:", e)
            hist = None
        
        if hist:
            print(f"✅ Найдено {len(hist)} точек истории:")
            for i, (date, price) in enumerate(hist[:5]):                     
                print(f"  {i+1}. {date} -> {price} TL")
            if len(hist) > 5:
                print(f"  ... и еще {len(hist)-5} точек")
        else:
            print("❌ История не найдена")


if __name__ == '__main__':
    asyncio.run(run_test())
