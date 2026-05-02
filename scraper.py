            
import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime
from urllib.parse import quote_plus
from typing import List, Tuple, Optional, Dict, Any
import asyncio
import json
import time
from utils import setup_logger, retry, async_retry, RateLimiter, AsyncRateLimiter
from database import get_subscription                               
from localization import t                                  
try:
    import cloudscraper
    SCRAPER = cloudscraper.create_scraper()
except Exception:
    SCRAPER = None

                       
logger = setup_logger('scraper', 'scraper.log')

                                                                      
TRENDYOL_LIMITER = RateLimiter(max_requests=30, time_window=60)
ASYNC_TRENDYOL_LIMITER = AsyncRateLimiter(max_requests=30, time_window=60)

                                                                   
SEARCH_CACHE = {}
CACHE_EXPIRY = 3600         
TRENDING_CACHE_TTL = 600
TRENDING_STALE_TTL = 6 * 3600
TRENDING_CACHE: Dict[str, Tuple[List[Tuple[str, Optional[float], str]], float]] = {}


def _get_cache_key(query: str, source: str) -> str:
    """Генерирует ключ кэша для запроса."""
    return f"{source}:{hash(query)}"


def _get_cached_result(cache_key: str):
    """Получает результат из кэша если он ещё актуален."""
    if cache_key in SEARCH_CACHE:
        cached_data, timestamp = SEARCH_CACHE[cache_key]
        if time.time() - timestamp < CACHE_EXPIRY:
            return cached_data
        else:
                                      
            del SEARCH_CACHE[cache_key]
    return None


def _set_cached_result(cache_key: str, data):
    """Сохраняет результат в кэш."""
    SEARCH_CACHE[cache_key] = (data, time.time())

    if len(SEARCH_CACHE) > 100:

        oldest_key = min(SEARCH_CACHE.keys(), key=lambda k: SEARCH_CACHE[k][1])
        del SEARCH_CACHE[oldest_key]


def _get_trending_cached_result(cache_key: str, *, allow_stale: bool = False) -> Optional[List[Tuple[str, Optional[float], str]]]:
    cached = TRENDING_CACHE.get(cache_key)
    if not cached:
        return None

    cached_data, timestamp = cached
    age = time.time() - timestamp
    max_age = TRENDING_STALE_TTL if allow_stale else TRENDING_CACHE_TTL
    if age <= max_age:
        return list(cached_data)

    if age > TRENDING_STALE_TTL:
        TRENDING_CACHE.pop(cache_key, None)
    return None


def _set_trending_cached_result(cache_key: str, data: List[Tuple[str, Optional[float], str]]) -> None:
    if not data:
        return
    TRENDING_CACHE[cache_key] = (list(data), time.time())
    if len(TRENDING_CACHE) > 50:
        oldest_key = min(TRENDING_CACHE.keys(), key=lambda key: TRENDING_CACHE[key][1])
        del TRENDING_CACHE[oldest_key]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.trendyol.com/",
    "Connection": "keep-alive",
}


def parse_price_text(text: str) -> Optional[float]:
    """Надёжный парсер цены: учитывает форматы 1.234,56 / 1,234.56 / 1234.56 / 1234."""
    if not text:
        return None
    try:
        t = text.replace("\u00A0", "").replace("TL", "").strip()
                                              
        t = re.sub(r"[^0-9.,]", "", t)

        if not t:
            return None

        has_dot = "." in t
        has_comma = "," in t

                                      
        if has_dot and has_comma:
                                                      
            last_dot = t.rfind(".")
            last_comma = t.rfind(",")
            if last_comma > last_dot:
                                
                t = t.replace(".", "")                       
                t = t.replace(",", ".")                          
            else:
                                
                t = t.replace(",", "")                       
            return float(t)

                        
        if has_comma and not has_dot:
                                                                                      
            parts = t.split(",")
            if len(parts[-1]) in (1, 2):                    
                t = t.replace(",", ".")
                return float(t)
                                                          
            t = t.replace(",", "")
            return float(t)

                      
        if has_dot and not has_comma:
            parts = t.split(".")
            if len(parts[-1]) in (1, 2):
                return float(t)
                                  
            t = t.replace(".", "")
            return float(t)

                                        
        return float(t)
    except Exception:
        return None


@retry(
    exceptions=(requests.RequestException, json.JSONDecodeError),
    tries=3,
    delay=1,
    backoff=2,
    logger=logger
)
def get_price(url: str) -> Optional[float]:
    """
    Возвращает цену (float) или None.
    Порядок источников:
      1) window.__PRODUCT_DETAIL_APP_INITIAL_STATE__ (JavaScript переменная)
      2) meta product:price:amount
      3) JSON-LD (offers.price)
      4) Явные селекторы скидочной/обычной цены (prc-dsc, prc-org и др.)
      5) Регекс по '... TL' в тексте страницы
    """
    try:
        if not TRENDYOL_LIMITER.can_proceed():
            logger.warning(f"Rate limit exceeded while fetching price for {url}")
            time.sleep(2)                                         
            
        TRENDYOL_LIMITER.add_request()
        
                                                                                                  
        if SCRAPER is not None:
            r = SCRAPER.get(url, headers=HEADERS, timeout=20)
        else:
            r = requests.get(url, headers=HEADERS, timeout=20)
        
        if r.status_code != 200:
            logger.error(f"HTTP {r.status_code} when fetching price for {url}")
            return None

        html = r.text
        soup = BeautifulSoup(html, "html.parser")
        
                                                                                  
                                                                                    
        js_vars = [
            'window.__PRODUCT_DETAIL_APP_INITIAL_STATE__',
            'window.__INITIAL_STATE__',
            'window.__PRODUCT_INITIAL_STATE__',
            '__PRODUCT_DETAIL_APP_INITIAL_STATE__',
        ]
        for var_name in js_vars:
            data_obj = _extract_json_from_js_var(html, var_name)
            if data_obj:
                                                
                def find_price_in_obj(obj):
                    if isinstance(obj, dict):
                                                        
                        for key in ['price', 'sellingPrice', 'discountedPrice', 'originalPrice', 'currentPrice', 'finalPrice']:
                            if key in obj:
                                val = obj[key]
                                if isinstance(val, (int, float)):
                                    return float(val)
                                elif isinstance(val, dict):
                                                           
                                    nested_price = val.get('value') or val.get('amount') or val.get('price')
                                    if nested_price:
                                        p = parse_price_text(str(nested_price))
                                        if p is not None:
                                            return p
                                else:
                                    p = parse_price_text(str(val))
                                    if p is not None:
                                        return p
                                          
                        if 'offers' in obj:
                            offers = obj['offers']
                            if isinstance(offers, dict):
                                price = offers.get('price') or offers.get('lowPrice') or offers.get('highPrice')
                                if price:
                                    p = parse_price_text(str(price))
                                    if p is not None:
                                        return p
                            elif isinstance(offers, list) and offers:
                                price = offers[0].get('price') if isinstance(offers[0], dict) else None
                                if price:
                                    p = parse_price_text(str(price))
                                    if p is not None:
                                        return p
                                           
                        for v in obj.values():
                            res = find_price_in_obj(v)
                            if res is not None:
                                return res
                    elif isinstance(obj, list):
                        for item in obj:
                            res = find_price_in_obj(item)
                            if res is not None:
                                return res
                    return None
                
                price = find_price_in_obj(data_obj)
                if price is not None:
                    logger.debug(f"Found price {price} in JS var {var_name} for {url}")
                    return price

                                                             
        meta = soup.find("meta", {"property": "product:price:amount"})
        if meta and meta.get("content"):
            p = parse_price_text(meta["content"])
            if p is not None:
                return p

                                   
        for script in soup.find_all("script", type=re.compile("ld\\+json")):
            try:
                data = json.loads(script.string or "")
            except Exception:
                continue
                                                    
            def try_extract(obj) -> Optional[float]:
                if not isinstance(obj, (dict, list)):
                    return None
                if isinstance(obj, list):
                    for item in obj:
                        val = try_extract(item)
                        if val is not None:
                            return val
                else:
                                           
                    offers = obj.get("offers") if isinstance(obj, dict) else None
                    if isinstance(offers, dict):
                        price = offers.get("price") or offers.get("lowPrice") or offers.get("highPrice")
                        p = parse_price_text(str(price)) if price is not None else None
                        if p is not None:
                            return p
                                  
                    if "price" in obj:
                        p = parse_price_text(str(obj["price"]))
                        if p is not None:
                            return p
                                       
                    for v in obj.values():
                        val = try_extract(v)
                        if val is not None:
                            return val
                return None

            val = try_extract(data)
            if val is not None:
                return val

                                                                             
                                                            
        selectors = [
            "span.prc-dsc",                                    
            "span.prc-org",                                  
            "span.pr-new-br",                              
            'span[class*="prc"]',                                           
            'span[class*="price"]',                        
            'div[class*="price"] span',                    
            'div[class*="prc"] span',                            
            '[data-testid*="price"]',                               
            '[data-testid*="Price"]',                               
            'div.product-price-container span',                 
            'div.price-container span',                        
            'div[class*="ProductPrice"] span',               
            'span[data-testid="price"]',                           
        ]
        for sel in selectors:
            try:
                el = soup.select_one(sel)
                if el:
                    p = parse_price_text(el.get_text(" ", strip=True))
                    if p is not None and p > 0:
                        logger.debug(f"Found price {p} using selector {sel} for {url}")
                        return p
            except Exception:
                continue

                                                             
                                                                                   
        text = soup.get_text(" ", strip=True)
                                                            
        price_matches = list(re.finditer(r"(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?)\s*TL", text))
        if price_matches:
                                                                     
            for m in price_matches[:5]:                                 
                p = parse_price_text(m.group(1))
                if p is not None and p > 0 and p < 1000000:                         
                    logger.debug(f"Found price {p} using regex for {url}")
                    return p

                                                      
        try:
            price_attrs = soup.find_all(attrs={"data-price": True})
            for el in price_attrs:
                price_val = el.get("data-price")
                if price_val:
                    p = parse_price_text(str(price_val))
                    if p is not None and p > 0:
                        logger.debug(f"Found price {p} in data-price attribute for {url}")
                        return p
        except Exception:
            pass

        logger.warning(f"Could not extract price from {url} using any method")
        return None
    except Exception as e:
        logger.exception(f"scraper.get_price error for {url}: {e}")
        return None


def get_trending_sample() -> List[str]:
    return [
        "👟 Популярные кроссовки — скидки до 30%",
        "👜 Сумки — хит продаж",
        "📱 Чехлы и аксессуары — модные позиции"
    ]


                                                              

def _extract_title_from_json(html: str) -> Optional[str]:
    """
    Извлекает название товара из JSON данных Trendyol на странице.
    """
    try:
                                  
        varnames = [
            'window.__PRODUCT_DETAIL_APP_INITIAL_STATE__',
            'window.__INITIAL_STATE__',
            'window.__PRODUCT_INITIAL_STATE__',
            '__PRODUCT_DETAIL_APP_INITIAL_STATE__',
            '__INITIAL_STATE__'
        ]

        for vn in varnames:
            data_obj = _extract_json_from_js_var(html, vn)
            if data_obj and isinstance(data_obj, dict):
                                                         
                title_candidates = [
                    lambda: data_obj.get('product', {}).get('name'),
                    lambda: data_obj.get('product', {}).get('title'),
                    lambda: data_obj.get('product', {}).get('productName'),
                    lambda: data_obj.get('product', {}).get('brand', {}).get('name') + ' ' + data_obj.get('product', {}).get('name', ''),
                    lambda: _find_in_nested_dict(data_obj, 'name'),
                    lambda: _find_in_nested_dict(data_obj, 'title'),
                    lambda: _find_in_nested_dict(data_obj, 'productName'),
                ]

                for candidate_func in title_candidates:
                    try:
                        title = candidate_func()
                        if title and isinstance(title, str) and len(title.strip()) > 5:
                            return title.strip()
                    except Exception:
                        continue

    except Exception as e:
        logger.debug("_extract_title_from_json error: %s", e)

    return None


def _try_alternative_price_sources(title: str, trendyol_url: str) -> Optional[List[Tuple[str, float]]]:
    """
    Пытается получить историю цен из альтернативных источников.
    """
    try:
        logger.info("Trying alternative price sources for '%s'", title)

                                                    
        hist = _try_hepsiburada_price_history(title)
        if hist:
            logger.info("Found price history on Hepsiburada: %d points", len(hist))
            return hist

                                            
        hist = _try_n11_price_history(title)
        if hist:
            logger.info("Found price history on N11: %d points", len(hist))
            return hist

                                                     
        hist = _try_gittigidiyor_price_history(title)
        if hist:
            logger.info("Found price history on GittiGidiyor: %d points", len(hist))
            return hist

                                                                  
        hist = _try_trendyol_alternative_methods(trendyol_url)
        if hist:
            logger.info("Found price history using Trendyol alternative method: %d points", len(hist))
            return hist

    except Exception as e:
        logger.debug("_try_alternative_price_sources error: %s", e)

    return None


def _try_hepsiburada_price_history(title: str) -> Optional[List[Tuple[str, float]]]:
    """
    Пытается получить историю цен с Hepsiburada.
    """
    try:
        if not ASYNC_TRENDYOL_LIMITER.can_proceed():
            return None
        ASYNC_TRENDYOL_LIMITER.add_request()

                              
        q = quote_plus(title)
        search_url = f"https://www.hepsiburada.com/ara?q={q}"
        r = requests.get(search_url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, "html.parser")

                                       
        product_link = None
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/product/" in href and "hepsiburada.com" in href:
                product_link = href
                break

        if not product_link:
            return None

                                                      
        r2 = requests.get(product_link, headers=HEADERS, timeout=15)
        if r2.status_code != 200:
            return None

        soup2 = BeautifulSoup(r2.text, "html.parser")

                                             
        for script in soup2.find_all("script"):
            if script.string and "priceHistory" in script.string:
                try:
                                           
                    json_match = re.search(r'priceHistory\s*:\s*(\[[^\]]*\])', script.string)
                    if json_match:
                        hist_data = json.loads(json_match.group(1))
                        if hist_data:
                            return _normalize_price_history(hist_data, "Hepsiburada")
                except Exception:
                    continue

    except Exception as e:
        logger.debug("_try_hepsiburada_price_history error: %s", e)

    return None


def _try_n11_price_history(title: str) -> Optional[List[Tuple[str, float]]]:
    """
    Пытается получить историю цен с N11.
    """
    try:
        if not ASYNC_TRENDYOL_LIMITER.can_proceed():
            return None
        ASYNC_TRENDYOL_LIMITER.add_request()

                      
        q = quote_plus(title)
        search_url = f"https://www.n11.com/arama?q={q}"
        r = requests.get(search_url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, "html.parser")

                                       
        product_link = None
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/urun/" in href and "n11.com" in href:
                product_link = href
                break

        if not product_link:
            return None

                                                                                      
        return None

    except Exception as e:
        logger.debug("_try_n11_price_history error: %s", e)

    return None


def _try_gittigidiyor_price_history(title: str) -> Optional[List[Tuple[str, float]]]:
    """
    Пытается получить историю цен с GittiGidiyor.
    """
    try:
        if not ASYNC_TRENDYOL_LIMITER.can_proceed():
            return None
        ASYNC_TRENDYOL_LIMITER.add_request()

                               
        q = quote_plus(title)
        search_url = f"https://www.gittigidiyor.com/arama?q={q}"
        r = requests.get(search_url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, "html.parser")

                                       
        product_link = None
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/urun/" in href and "gittigidiyor.com" in href:
                product_link = href
                break

        if not product_link:
            return None

                                              
        return None

    except Exception as e:
        logger.debug("_try_gittigidiyor_price_history error: %s", e)

    return None


def _try_trendyol_alternative_methods(trendyol_url: str) -> Optional[List[Tuple[str, float]]]:
    """
    Альтернативные методы получения истории с Trendyol.
    """
    try:
                                                                       
        if SCRAPER is not None:
            r = SCRAPER.get(trendyol_url, headers=HEADERS, timeout=20)
        else:
            r = requests.get(trendyol_url, headers=HEADERS, timeout=20)

        if r.status_code != 200:
            return None

        html = r.text

                                               
        alt_varnames = [
            'window.__PRODUCT_DATA__',
            'window.__PRODUCT_DETAIL__',
            'window.productData',
            'window.productDetail',
            '__PRODUCT_DATA__',
            '__PRODUCT_DETAIL__'
        ]

        for vn in alt_varnames:
            data_obj = _extract_json_from_js_var(html, vn)
            if data_obj and isinstance(data_obj, dict):
                hist = _extract_price_history_from_object(data_obj)
                if hist:
                    logger.debug("Found price history in alternative JSON var %s", vn)
                    return hist

                                     
        hist = _try_extract_inline_price_history(html)
        if hist:
            return hist

    except Exception as e:
        logger.debug("_try_trendyol_alternative_methods error: %s", e)

    return None


def _extract_price_history_from_object(obj: dict) -> Optional[List[Tuple[str, float]]]:
    """
    Извлекает историю цен из JSON объекта.
    """
    try:
                                  
        candidates = ['priceHistory', 'price_history', 'prices', 'priceChanges', 'price_changes']

        for candidate in candidates:
            if candidate in obj:
                hist_data = obj[candidate]
                if isinstance(hist_data, list) and hist_data:
                    return _normalize_price_history(hist_data, "Trendyol_alt")

                                                
        for value in obj.values():
            if isinstance(value, dict):
                result = _extract_price_history_from_object(value)
                if result:
                    return result
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        result = _extract_price_history_from_object(item)
                        if result:
                            return result

    except Exception as e:
        logger.debug("_extract_price_history_from_object error: %s", e)

    return None


def _try_extract_inline_price_history(html: str) -> Optional[List[Tuple[str, float]]]:
    """
    Ищет историю цен в inline JSON на странице.
    """
    try:
                                                     
        patterns = [
            r'"priceHistory"\s*:\s*(\[[^\]]*\])',
            r'"price_history"\s*:\s*(\[[^\]]*\])',
            r'"prices"\s*:\s*(\[[^\]]*\])',
            r'priceHistory\s*:\s*(\[[^\]]*\])',
            r'price_history\s*:\s*(\[[^\]]*\])'
        ]

        for pattern in patterns:
            matches = re.findall(pattern, html, re.IGNORECASE)
            for match in matches:
                try:
                    hist_data = json.loads(match)
                    if hist_data and isinstance(hist_data, list):
                        normalized = _normalize_price_history(hist_data, "Trendyol_inline")
                        if normalized and len(normalized) >= 3:
                            return normalized
                except Exception:
                    continue

    except Exception as e:
        logger.debug("_try_extract_inline_price_history error: %s", e)

    return None


def _normalize_price_history(hist_data: list, source: str) -> Optional[List[Tuple[str, float]]]:
    """
    Нормализует данные истории цен в стандартный формат (date_str, price).
    """
    try:
        result = []
        for item in hist_data:
            if isinstance(item, dict):
                                          
                date_keys = ['date', 'timestamp', 'time', 'created_at', 'updated_at']
                price_keys = ['price', 'value', 'amount', 'selling_price', 'current_price']

                date_val = None
                price_val = None

                           
                for dk in date_keys:
                    if dk in item:
                        date_val = item[dk]
                        break

                           
                for pk in price_keys:
                    if pk in item:
                        price_val = item[pk]
                        break

                if date_val and price_val:
                                      
                    if isinstance(date_val, (int, float)):
                                   
                        dt = datetime.utcfromtimestamp(int(date_val))
                        date_str = dt.strftime('%d.%m.%Y')
                    elif isinstance(date_val, str):
                                     
                        try:
                            if len(date_val) == 10:              
                                date_str = date_val
                            else:
                                                     
                                dt = datetime.fromisoformat(date_val.replace('Z', '+00:00'))
                                date_str = dt.strftime('%d.%m.%Y')
                        except Exception:
                            date_str = str(date_val)
                    else:
                        date_str = str(date_val)

                                      
                    try:
                        price_float = float(price_val)
                        result.append((date_str, price_float))
                    except Exception:
                        continue

        if result:
                               
            result.sort(key=lambda x: x[0])
            return result

    except Exception as e:
        logger.debug("_normalize_price_history error for %s: %s", source, e)

    return None


def find_similar_products(product_title: str, product_url: str, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Ищет похожие товары на Trendyol.
    Возвращает список словарей с информацией о товарах.
    """
    try:
        if not product_title:
            return []

                                     
        clean_title = re.sub(r'[^\w\s]', ' ', product_title.lower())
                                                   
        stop_words = {'ve', 'ile', 'bir', 'bu', 'şu', 'o', 'the', 'and', 'or', 'a', 'an', 'for', 'to', 'in', 'on', 'at', 'by', 'with'}
        keywords = [word for word in clean_title.split() if len(word) > 2 and word not in stop_words]

        if len(keywords) < 2:
                                                         
            keywords = clean_title.split()[:3]

                          
        search_query = ' '.join(keywords[:3])                             
        search_url = f"https://www.trendyol.com/sr?q={quote_plus(search_query)}"

        logger.debug(f"Searching for similar products: '{search_query}'")

        if SCRAPER is not None:
            r = SCRAPER.get(search_url, headers=HEADERS, timeout=15)
        else:
            r = requests.get(search_url, headers=HEADERS, timeout=15)

        if r.status_code != 200:
            return []

        soup = BeautifulSoup(r.text, "html.parser")

        similar_products = []
        current_product_id = None

                                             
        if '-p-' in product_url:
            try:
                current_product_id = product_url.split('-p-')[-1].split('-')[0]
            except Exception as e:
                logger.debug("Could not extract current_product_id from %s: %s", product_url, e)

                                          
        for link in soup.find_all('a', href=True):
            href = link['href']
            if '/p-' in href and 'trendyol.com' in href:
                                     
                try:
                    product_id = href.split('-p-')[-1].split('-')[0]
                    if product_id == current_product_id:
                        continue                           
                except Exception as e:
                    logger.debug("Failed to extract product_id from href %s: %s", href, e)
                    continue

                                          
                title = link.get('title', '') or link.get_text(strip=True)
                if not title:
                    continue

                                         
                title_lower = title.lower()
                relevance_score = 0

                                                 
                for keyword in keywords:
                    if keyword in title_lower:
                        relevance_score += 1

                                                 
                if relevance_score < 1:
                    continue

                               
                full_url = f"https://www.trendyol.com{href}" if href.startswith('/') else href

                similar_products.append({
                    'title': title[:100],                      
                    'url': full_url,
                    'relevance': relevance_score,
                    'product_id': product_id
                })

                if len(similar_products) >= limit:
                    break

                                    
        similar_products.sort(key=lambda x: x['relevance'], reverse=True)

        logger.debug(f"Found {len(similar_products)} similar products")
        return similar_products[:limit]

    except Exception as e:
        logger.debug(f"find_similar_products error: {e}")
        return []


async def get_comparison_report(user_id: int, subscription_id: int, limit: int = 5) -> Optional[str]:
    """
    Получает сравнение цен для похожих товаров.
    Возвращает отформатированное сообщение или None если не удалось.
    """
    try:
                                              
        sub = get_subscription(subscription_id)
        if not sub:
            return None

        _, _, current_url, _, current_price, current_title, _, _, _, _, _, _, _ = sub[:13]

        if not current_title:
            return None

                             
        similar_products = await asyncio.to_thread(find_similar_products, current_title, current_url, limit)

        if not similar_products:
            return t(user_id, "compare_no_similar")

                                           
        comparison_data = []

                                 
        comparison_data.append({
            'title': current_title[:50] + "..." if len(current_title) > 50 else current_title,
            'price': current_price,
            'url': current_url,
            'is_current': True
        })

                                  
        for product in similar_products:
            try:
                                      
                price = await get_price_async(product['url'])
                if price:
                    comparison_data.append({
                        'title': product['title'][:50] + "..." if len(product['title']) > 50 else product['title'],
                        'price': price,
                        'url': product['url'],
                        'is_current': False
                    })
            except Exception as e:
                logger.debug(f"Failed to get price for similar product {product['url']}: {e}")
                continue

        if len(comparison_data) < 2:                        
            return t(user_id, "compare_no_similar")

                           
        comparison_data.sort(key=lambda x: x['price'] or 999999)

                               
        result = t(user_id, "compare_header")

                       
        current_item = next((item for item in comparison_data if item['is_current']), None)
        if current_item:
            price_str = f"{current_item['price']:.0f} TL" if current_item['price'] else t(user_id, "compare_no_price")
            result += f"🎯 *{t(user_id, 'compare_current_product')}:*\n"
            result += f"📦 {current_item['title']}\n"
            result += f"💰 {price_str}\n\n"

                        
        result += f"🔍 *{t(user_id, 'compare_similar_products')}:*\n"
        for i, item in enumerate([item for item in comparison_data if not item['is_current']], 1):
            price_str = f"{item['price']:.0f} TL" if item['price'] else t(user_id, "compare_no_price")
            marker = "🟢" if item['price'] and current_item and current_item['price'] and item['price'] < current_item['price'] else "⚪"
            result += f"{i}. {marker} {item['title']}\n   {price_str}\n"

        return result

    except Exception as e:
        logger.exception(f"get_similar_products_comparison error: {e}")
        return None


                                                                              
async def get_similar_products_comparison(user_id: int, subscription_id: int, limit: int = 5) -> Optional[str]:
    """Wrapper kept for backward compatibility with older imports/tests."""
    return await get_comparison_report(user_id, subscription_id, limit)

def _find_best_akakce_product_link(soup: BeautifulSoup, search_title: str) -> Optional[str]:
    """
    Находит лучшую ссылку на товар на странице результатов поиска Akakçe.
    """
    if not search_title:
        return None

    try:
                                      
        search_lower = search_title.lower().strip()

                                   
        product_links = []

                                          
        patterns = [
            "/p-",
            "/urun/",
            "/product/",
            "/urunler/"
        ]

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if any(pattern in href for pattern in patterns):
                                                          
                link_text = a.get_text(strip=True)
                parent = a.find_parent()
                if parent:
                                                                  
                    title_elem = parent.find("h3") or parent.find("h4") or parent.find("div", class_=re.compile("title"))
                    if title_elem:
                        link_text = title_elem.get_text(strip=True)

                                         
                relevance = _calculate_relevance(search_lower, link_text.lower() if link_text else "")

                product_links.append({
                    'href': href,
                    'text': link_text or '',
                    'relevance': relevance
                })

        if not product_links:
            return None

                                                        
        product_links.sort(key=lambda x: x['relevance'], reverse=True)
        best_link = product_links[0]

        logger.debug("Best Akakçe match: '%s' (relevance: %.2f) for search: '%s'",
                    best_link['text'][:50], best_link['relevance'], search_title[:50])

                                                           
        if best_link['relevance'] >= 0.3:
            return best_link['href']

    except Exception as e:
        logger.debug("_find_best_akakce_product_link error: %s", e)

    return None


def _calculate_relevance(search_text: str, candidate_text: str) -> float:
    """
    Вычисляет релевантность между поисковым запросом и кандидатом.
    Возвращает значение от 0.0 до 1.0.
    """
    if not search_text or not candidate_text:
        return 0.0

    try:
                            
        search_words = set(re.findall(r'\w+', search_text))
        candidate_words = set(re.findall(r'\w+', candidate_text))

        if not search_words:
            return 0.0

                               
        intersection = search_words & candidate_words
        union = search_words | candidate_words

                            
        jaccard = len(intersection) / len(union) if union else 0.0

                                                        
        consecutive_bonus = 0.0
        search_str = ' '.join(search_words)
        if search_str in candidate_text:
            consecutive_bonus = 0.3

                                    
        exact_bonus = 0.0
        if search_text in candidate_text:
            exact_bonus = 0.4

        relevance = min(1.0, jaccard + consecutive_bonus + exact_bonus)

        return relevance

    except Exception:
        return 0.0


def _find_in_nested_dict(obj: dict, key: str) -> Optional[str]:
    """
    Рекурсивно ищет ключ в вложенной структуре словаря.
    """
    if not isinstance(obj, dict):
        return None

    if key in obj and isinstance(obj[key], str):
        return obj[key]

    for value in obj.values():
        if isinstance(value, dict):
            result = _find_in_nested_dict(value, key)
            if result:
                return result
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    result = _find_in_nested_dict(item, key)
                    if result:
                        return result

    return None


def get_product_title(url: str) -> Optional[str]:
    """
    Пытаемся вытащить название товара со страницы Trendyol.
    Использует множественные методы: HTML, JSON, meta tags.
    Всегда использует cloudscraper для обхода защиты.
    Возвращает строку или None.
    """
    try:
                                                                   
        if SCRAPER is not None:
            r = SCRAPER.get(url, headers=HEADERS, timeout=20)
        else:
            r = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code != 200:
            logger.debug(f"get_product_title: HTTP {r.status_code} for {url}")
            return None

        html = r.text
        soup = BeautifulSoup(html, "html.parser")

                                                     
        title = _extract_title_from_json(html)
        if title:
            return title

                                                                    
        candidates = [
                                
            ("h1", {"class": re.compile(r"pr-new-br", re.I)}),
            ("h1", {"class": re.compile(r"product-name", re.I)}),
            ("h1", {"class": re.compile(r"title", re.I)}),
            ("h1", {"data-testid": re.compile(r"product-name", re.I)}),
            ("h1", None),

                                      
            ("div", {"class": re.compile(r"product-info", re.I)}),
            ("div", {"class": re.compile(r"product-detail", re.I)}),
            ("span", {"class": re.compile(r"product-name", re.I)}),
            ("meta", {"property": "og:title"}),
            ("meta", {"name": "title"}),
            ("title", None),
        ]

        for tag, attrs in candidates:
            try:
                if tag == "meta":
                    el = soup.find(tag, attrs=attrs)
                    if el and el.get("content"):
                        content = el["content"].strip()
                                                                    
                        if " | Trendyol" in content:
                            content = content.split(" | Trendyol")[0].strip()
                        if len(content) > 10:                       
                            return content
                else:
                    el = soup.find(tag, attrs=attrs) if attrs else soup.find(tag)
                    if el:
                        txt = el.get_text(strip=True)
                        if txt and len(txt) > 5:                      
                                                
                            txt = re.sub(r'\s+', ' ', txt)                                 
                            return txt
            except Exception:
                continue

                                                     
        og_title = soup.find("meta", {"property": "og:title"})
        if og_title and og_title.get("content"):
            content = og_title["content"].strip()
            if " | Trendyol" in content:
                content = content.split(" | Trendyol")[0].strip()
            if len(content) > 10:
                return content

                                                      
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            path_parts = parsed.path.strip('/').split('/')
            if path_parts:
                last_part = path_parts[-1]
                if '-p-' in last_part and len(last_part) > 10:
                                                                  
                    title = last_part.replace('-p-', '').replace('-', ' ').title()
                    if len(title) > 10:
                        return title
        except Exception:
            pass

    except Exception as e:
        logger.debug("get_product_title error for %s: %s", url, e)

    return None


def get_product_image(url: str) -> Optional[str]:
    """Попытаться получить URL главного изображения товара (og:image, meta или первый крупный img)."""
    try:
        if SCRAPER is not None:
            r = SCRAPER.get(url, headers=HEADERS, timeout=15)
        else:
            r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "html.parser")
                  
        meta = soup.find("meta", property="og:image")
        if meta and meta.get("content"):
            return meta["content"]

                            
        link = soup.find("link", rel="image_src")
        if link and link.get("href"):
            return link["href"]

                                              
        imgs = soup.find_all("img", src=True)
        best = None
        for img in imgs:
            src = img.get("src") or img.get("data-src")
            if not src:
                continue
                                         
            w = img.get("width")
            h = img.get("height")
            try:
                if w and int(w) < 50:
                    continue
                if h and int(h) < 50:
                    continue
            except Exception:
                pass
                                        
            best = src
            break
        return best
    except Exception as e:
        logger.debug("get_product_image error: %s", e)
    return None


def _try_parse_price_history_from_script(soup: BeautifulSoup) -> Optional[List[Tuple[str, float]]]:
    """
    Ищем в <script> JSON-подобные структуры с датами и ценами.
    Возвращаем список (date_str, price) или None.
    """
    scripts = soup.find_all("script")
    for s in scripts:
        text = s.string or ""
                                                                                     
        m = re.search(r"(\[{\s*\"date\".*?}\])", text, flags=re.S)
        if m:
            try:
                import json
                arr = json.loads(m.group(1))
                out = []
                for item in arr:
                    date = item.get("date") or item.get("t") or item.get("x")
                    price = item.get("price") or item.get("y") or item.get("p")
                    if date and price is not None:
                        out.append((str(date), float(price)))
                if out:
                    return out
            except Exception:
                continue
    return None


def _try_parse_html_table_history(soup: BeautifulSoup) -> Optional[List[Tuple[str, float]]]:
    """
    Ищем блоки с историей в HTML (таблицы/блоки с классами, содержащими слова типа 'history', 'grafik', 'fiyat').
    Возвращаем список (date_str, price) или None.
    """
    candidates = soup.find_all(attrs={"class": re.compile(r"(fiyat|history|grafik|chart|price-history|pricehistory)", re.I)})
    for c in candidates:
        text = c.get_text(" ", strip=True)
                                   
        pairs = re.findall(r"(\d{1,2}\.\d{1,2}\.\d{2,4}|\d{4}-\d{2}-\d{2}).{0,20}?(\d+[.,]?\d*)\s*TL", text)
        if pairs:
            out = []
            for date_str, price_str in pairs:
                                  
                ds = date_str.replace(".", "-")
                try:
                    price = float(price_str.replace(".", "").replace(",", "."))
                    out.append((ds, price))
                except Exception as e:
                    logger.debug("Failed to parse price '%s': %s", price_str, e)
                    continue
            if out:
                return out
    return None


@retry(
    exceptions=(requests.RequestException, json.JSONDecodeError),
    tries=3,
    delay=1,
    backoff=2,
    logger=logger
)
def get_price_history_from_akakce(trendyol_url: str) -> Optional[List[Tuple[str, float]]]:
    """
    Попытка получить историю цен с Akakçe по URL Trendyol:
    1) Берём название товара с Trendyol
    2) Ищем на akakce через /arama?q=
    3) Открываем страницу первого найденного товара и пытаемся распарсить историю
    Возвращает список (date_str, price) или None.
    """
    try:
        if not TRENDYOL_LIMITER.can_proceed():
            logger.warning(f"Rate limit exceeded while fetching history for {trendyol_url}")
            time.sleep(2)
        
        TRENDYOL_LIMITER.add_request()
        title = get_product_title(trendyol_url)
        if not title:
            logger.warning(f"Could not get product title for {trendyol_url}")
            return None

                       
        cache_key = _get_cache_key(title, "akakce_search")
        cached_result = _get_cached_result(cache_key)
        if cached_result:
            logger.debug("Using cached Akakçe search result for '%s'", title)
            link, soup = cached_result
        else:
            q = quote_plus(title)
            search_url = f"https://www.akakce.com/arama?q={q}"
            logger.info(f"Searching price history for '{title}'...")
            r = requests.get(search_url, headers=HEADERS, timeout=15)
            if r.status_code != 200:
                return None
            soup = BeautifulSoup(r.text, "html.parser")

                                              
            link = _find_best_akakce_product_link(soup, title)
            _set_cached_result(cache_key, (link, soup))

        if not link:
            logger.warning("No suitable product found on Akakçe for '%s'", title)
                                                
            return _try_alternative_price_sources(title, trendyol_url)

                            
        if link.startswith("/"):
            product_url = "https://www.akakce.com" + link
        elif link.startswith("http"):
            product_url = link
        else:
            product_url = "https://www.akakce.com/" + link.lstrip("/")

        r2 = requests.get(product_url, headers=HEADERS, timeout=15)
        if r2.status_code != 200:
            return None
        soup2 = BeautifulSoup(r2.text, "html.parser")

                                         
        hist = _try_parse_price_history_from_script(soup2)
        if hist:
            return hist

                                             
        hist = _try_parse_html_table_history(soup2)
        if hist:
            return hist

                                                
        txt = soup2.get_text(" ", strip=True)
        pairs = re.findall(r"(\d{1,2}\.\d{1,2}\.\d{2,4}|\d{4}-\d{2}-\d{2}).{0,20}?(\d+[.,]?\d*)\s*TL", txt)
        if pairs:
            out = []
            for date_str, price_str in pairs:
                ds = date_str.replace(".", "-")
                try:
                    price = float(price_str.replace(".", "").replace(",", "."))
                    out.append((ds, price))
                except Exception as e:
                    logger.debug("Failed to parse price '%s' in text pairs: %s", price_str, e)
                    continue
            if out:
                return out

    except Exception as e:
        print("get_price_history_from_akakce error:", e)
    return None


                                                                   
@async_retry(
    exceptions=(requests.RequestException, json.JSONDecodeError),
    tries=3,
    delay=1,
    backoff=2,
    logger=logger
)
async def get_price_async(url: str) -> Optional[float]:
    """
    Async wrapper for get_price() using a thread to avoid blocking the event loop.
    Includes rate limiting and retries.
    """
    if not await ASYNC_TRENDYOL_LIMITER.can_proceed():
        logger.warning(f"Async rate limit exceeded while fetching price for {url}")
        await asyncio.sleep(2)                                         
        
    await ASYNC_TRENDYOL_LIMITER.add_request()
    try:
        return await asyncio.wait_for(asyncio.to_thread(get_price, url), timeout=20.0)
    except asyncio.TimeoutError:
        logger.warning("Timeout fetching price for %s", url)
        return None
    except Exception as e:
        logger.error(f"Error fetching price for {url}: {e}")
        return None
        raise


async def get_product_info_async(url: str) -> Tuple[Optional[float], Optional[str], Optional[str]]:
    """Возвращает кортеж (price, title, image_url) — выполняет сетевые запросы в thread.
    Нужна для случаев, когда надо показать пользователю название/обложку вместе с ценой.
    """
    if not await ASYNC_TRENDYOL_LIMITER.can_proceed():
        logger.warning(f"Async rate limit exceeded while fetching product info for {url}")
        await asyncio.sleep(1)
    await ASYNC_TRENDYOL_LIMITER.add_request()

    def _sync():
        price = get_price(url)
        title = get_product_title(url)
        image = get_product_image(url)
        return price, title, image

    try:
        return await asyncio.wait_for(asyncio.to_thread(_sync), timeout=30.0)                     
    except asyncio.TimeoutError:
        logger.warning("Timeout fetching product info for %s", url)
        return None, None, None


@async_retry(
    exceptions=(requests.RequestException, json.JSONDecodeError),
    tries=3,
    delay=1,
    backoff=2,
    logger=logger
)
async def get_price_history_from_akakce_async(trendyol_url: str) -> Optional[List[Tuple[str, float]]]:
    """
    Async wrapper for get_price_history_from_akakce() using a thread.
    Includes rate limiting and retries.
    """
    if not await ASYNC_TRENDYOL_LIMITER.can_proceed():
        logger.warning(f"Async rate limit exceeded while fetching history for {trendyol_url}")
        await asyncio.sleep(2)
        
    await ASYNC_TRENDYOL_LIMITER.add_request()
    try:
        res = await asyncio.wait_for(asyncio.to_thread(get_price_history_from_akakce, trendyol_url), timeout=45.0)
        if res:
            logger.info("get_price_history_from_akakce_async: found %d points for %s", len(res), trendyol_url)
            return res
                                               
        logger.info("get_price_history_from_akakce_async: akakce returned no history, trying Trendyol fallback for %s", trendyol_url)
        try:
            return await get_price_history_from_trendyol_async(trendyol_url)
        except Exception as e:
            logger.exception("Trendol fallback raised exception: %s", e)
            return None
    except Exception as e:
        logger.error(f"Error fetching price history for {trendyol_url}: {e}")
        raise


def _extract_json_from_js_var(text: str, varname: str) -> Optional[dict]:
    """Find JavaScript assignment like window.__VAR__ = {...}; and return parsed dict if possible."""
    try:
                                                                  
        patterns = [
            rf"{re.escape(varname)}\s*=\s*(\{{.*?\}})\s*;",                           
            rf"{re.escape(varname)}\s*=\s*(\{{.*?\}})\s*$",                               
            rf"var\s+{re.escape(varname)}\s*=\s*(\{{.*?\}})\s*;",                        
            rf"let\s+{re.escape(varname)}\s*=\s*(\{{.*?\}})\s*;",                        
            rf"const\s+{re.escape(varname)}\s*=\s*(\{{.*?\}})\s*;",                          
        ]
        
        for pattern_str in patterns:
            pattern = re.compile(pattern_str, re.S | re.M)
            m = pattern.search(text)
            if m:
                json_text = m.group(1)
                                                                  
                json_text = re.sub(r",\s*([}\]])", r"\1", json_text)
                                                                                     
                                                  
                try:
                    return json.loads(json_text)
                except json.JSONDecodeError:
                                                         
                    try:
                                             
                        json_text = re.sub(r'//.*?$', '', json_text, flags=re.M)
                        json_text = re.sub(r'/\*.*?\*/', '', json_text, flags=re.S)
                                                 
                        json_text = re.sub(r",\s*([}\]])", r"\1", json_text)
                                       
                        return json.loads(json_text)
                    except Exception:
                                                                                            
                        try:
                            cleaned = json_text
                                                                                        
                            cleaned = re.sub(r"'(\w+)'\s*:", r'"\1":', cleaned)                    
                            cleaned = re.sub(r":\s*'([^']*)'", r': "\1"', cleaned)                          
                            cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
                            return json.loads(cleaned)
                        except Exception:
                            continue
        
        return None
    except Exception as e:
        logger.debug("_extract_json_from_js_var failed for %s: %s", varname, e)
    return None


def get_price_history_from_trendyol(trendyol_url: str) -> Optional[List[Tuple[str, float]]]:
    """
    Попытаться извлечь историю цен прямо из страницы товара Trendyol.
    Ищем объект window.__PRODUCT_DETAIL_APP_INITIAL_STATE__ или похожие, затем поле priceHistory.
    Возвращаем список (date_str, price) или None.
    """
    logger.info("Attempting Trendyol page history parse for %s", trendyol_url)
    try:
        if SCRAPER is not None:
            r = SCRAPER.get(trendyol_url, headers=HEADERS, timeout=20)
        else:
            r = requests.get(trendyol_url, headers=HEADERS, timeout=20)
        if r.status_code != 200:
            logger.info("Trendyol page fetch returned status %s for %s", r.status_code, trendyol_url)
            return None
        html = r.text

                                           
        varnames = [
            'window.__PRODUCT_DETAIL_APP_INITIAL_STATE__',
            'window.__INITIAL_STATE__',
            'window.__PRODUCT_INITIAL_STATE__'
        ]
        data_obj = None
        for vn in varnames:
            data_obj = _extract_json_from_js_var(html, vn)
            if data_obj:
                logger.debug("Found JS var %s, attempting to locate priceHistory", vn)
                break

                                                                                            
        if not data_obj:
            for s in re.finditer(r"(\{.*?\})", html, flags=re.S):
                chunk = s.group(1)
                if 'priceHistory' in chunk:
                    try:
                        obj = json.loads(chunk)
                        data_obj = obj
                        logger.debug("Found inline JSON chunk containing priceHistory")
                        break
                    except Exception:
                        continue

        if not data_obj:
            logger.info("No product initial state JSON found on Trendyol page %s", trendyol_url)
                                                                                    
                                                                                     
            pass

                                                   
        def find_price_history(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    if k and 'price' in k.lower() and isinstance(v, list):
                                         
                        if v and isinstance(v[0], (dict, list, str)):
                            return v
                    res = find_price_history(v)
                    if res:
                        return res
            elif isinstance(o, list):
                for it in o:
                    res = find_price_history(it)
                    if res:
                        return res
            return None

        hist = find_price_history(data_obj)
        if not hist:
            logger.info("No priceHistory array found in initial state for %s", trendyol_url)
                                                                                    
                                                       
            logger.debug("Attempting Trendyol internal API fallback for %s", trendyol_url)
            try:
                api_hist = _get_price_history_from_trendyol_api(trendyol_url, html)
                if api_hist:
                    return api_hist
            except Exception:
                logger.exception("Trendyol API fallback raised an exception for %s", trendyol_url)
            return None

        out = []
        for item in hist:
            try:
                                                       
                if isinstance(item, dict):
                                            
                    date = item.get('date') or item.get('t') or item.get('x') or item.get('time')
                    price = item.get('price') or item.get('y') or item.get('p') or item.get('value')
                    if date and price is not None:
                        out.append((str(date), float(price)))
                elif isinstance(item, list) and len(item) >= 2:
                                        
                    d, p = item[0], item[1]
                    out.append((str(d), float(p)))
                else:
                                                                
                    s = str(item)
                    m = re.search(r"(\d{4}-\d{2}-\d{2}).*?(\d+[.,]?\d*)", s)
                    if m:
                        out.append((m.group(1), float(m.group(2).replace(',', '.'))))
            except Exception:
                continue

        if out:
            logger.info("Extracted %d price history points from Trendyol for %s", len(out), trendyol_url)
            return out
        logger.info("No valid price points parsed from Trendyol for %s", trendyol_url)
        return None
    except Exception as e:
        logger.exception("get_price_history_from_trendyol error for %s: %s", trendyol_url, e)
        return None


def _extract_listing_ids_from_html(html: str) -> List[str]:
    """
    Extract candidate listingId values from Trendyol product page HTML.
    Returns a list of unique listingId strings (may be empty).
    """
    ids = []
    try:
                                                                            
        for m in re.finditer(r'"listingId"\s*:\s*"([0-9a-fA-F-]+)"', html):
            ids.append(m.group(1))

                                                                                     
        for m in re.finditer(r'listingId\s*[:=]\s*"([0-9a-fA-F-]+)"', html):
            ids.append(m.group(1))

    except Exception:
        logger.debug("_extract_listing_ids_from_html failed", exc_info=True)
                            
    seen = set()
    out = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def _call_santral_price_history_api(listing_id: str, referer: Optional[str] = None) -> Optional[dict]:
    """
    Call Trendyol internal price-history SANTRAL endpoint for a single listingId.
    Tries GET with query param and then POST with JSON body as fallback.
    Returns parsed JSON dict on success or None.
    """
    base = "https://apigw.trendyol.com/discovery-pdp-websfxpricehistory-santral"
    headers = HEADERS.copy()
    headers.update({
        "Accept": "application/json, text/plain, */*",
        "Referer": referer or "https://www.trendyol.com/",
        "X-Requested-With": "XMLHttpRequest",
    })
    try:
        params = {"listingId": listing_id}
                       
        if SCRAPER is not None:
            r = SCRAPER.get(base, params=params, headers=headers, timeout=15)
        else:
            r = requests.get(base, params=params, headers=headers, timeout=15)
        if r.status_code == 200:
            try:
                return r.json()
            except Exception:
                return None

                                                   
        payload = {"listingId": listing_id}
        headers_post = headers.copy()
        headers_post["Content-Type"] = "application/json;charset=UTF-8"
        if SCRAPER is not None:
            r2 = SCRAPER.post(base, json=payload, headers=headers_post, timeout=15)
        else:
            r2 = requests.post(base, json=payload, headers=headers_post, timeout=15)
        if r2.status_code == 200:
            try:
                return r2.json()
            except Exception:
                return None
    except Exception:
        logger.debug("_call_santral_price_history_api error for %s", listing_id, exc_info=True)
    return None


def _get_price_history_from_trendyol_api(trendyol_url: str, html: Optional[str] = None) -> Optional[List[Tuple[str, float]]]:
    """
    High-level function: extract listingId candidates from HTML (or fetch page if html not supplied),
    call SANTRAL API and normalize response into list of (date, price).
    """
    try:
        page_html = html
        if not page_html:
            if SCRAPER is not None:
                r = SCRAPER.get(trendyol_url, headers=HEADERS, timeout=15)
            else:
                r = requests.get(trendyol_url, headers=HEADERS, timeout=15)
            if r.status_code != 200:
                return None
            page_html = r.text

        listing_ids = _extract_listing_ids_from_html(page_html)
        if not listing_ids:
            logger.info("No listingId found on page %s", trendyol_url)
            return None

        for lid in listing_ids:
            logger.debug("Trying SANTRAL API for listingId=%s", lid)
            payload = _call_santral_price_history_api(lid, referer=trendyol_url)
            if not payload:
                logger.debug("No payload returned for listingId=%s", lid)
                continue

                                                                         
            def find_price_array(o):
                if isinstance(o, dict):
                    for k, v in o.items():
                        if isinstance(v, list) and v:
                                                                                 
                            if isinstance(v[0], dict) and any('price' in kk.lower() or 'selling' in kk.lower() for kk in v[0].keys()):
                                return v
                        res = find_price_array(v)
                        if res:
                            return res
                elif isinstance(o, list):
                    for it in o:
                        res = find_price_array(it)
                        if res:
                            return res
                return None

            arr = find_price_array(payload)
            if not arr:
                logger.debug("SANTRAL response for %s did not contain recognizable array", lid)
                continue

            out = []
            for item in arr:
                try:
                    if isinstance(item, dict):
                                               
                                                                            
                        date = (item.get('createdAt') or item.get('createdDate') or item.get('date') or
                                item.get('time') or item.get('ts') or item.get('timestamp'))
                                                                            
                        price = (item.get('price') or item.get('sellingPrice') or item.get('discountedPrice') or
                                 item.get('value') or item.get('amount'))
                                                
                        if isinstance(price, dict):
                            price = price.get('value') or price.get('amount') or price.get('sellingPrice')
                        if date and price is not None:
                                                              
                            if isinstance(date, (int, float)):
                                                      
                                if date > 1e12:
                                        
                                    ds = datetime.utcfromtimestamp(date / 1000).strftime('%Y-%m-%d')
                                elif date > 1e9:
                                    ds = datetime.utcfromtimestamp(date).strftime('%Y-%m-%d')
                                else:
                                    ds = str(date)
                            else:
                                ds = str(date)
                            pval = None
                            try:
                                pval = float(price)
                            except Exception:
                                                      
                                pval = parse_price_text(str(price))
                            if pval is not None:
                                out.append((ds, float(pval)))
                    elif isinstance(item, list) and len(item) >= 2:
                        d, p = item[0], item[1]
                        ds = str(d)
                        pval = float(p)
                        out.append((ds, pval))
                except Exception:
                    continue

            if out:
                logger.info("Extracted %d points from SANTRAL for listingId=%s", len(out), lid)
                return out

        return None
    except Exception:
        logger.exception("_get_price_history_from_trendyol_api failed for %s", trendyol_url)
    return None


async def get_price_history_from_trendyol_async(trendyol_url: str) -> Optional[List[Tuple[str, float]]]:
    if not await ASYNC_TRENDYOL_LIMITER.can_proceed():
        logger.warning(f"Async rate limit exceeded while fetching Trendyol history for {trendyol_url}")
        await asyncio.sleep(2)
    await ASYNC_TRENDYOL_LIMITER.add_request()
    try:
        return await asyncio.wait_for(asyncio.to_thread(get_price_history_from_trendyol, trendyol_url), timeout=45.0)
    except Exception as e:
        logger.error(f"Error fetching Trendyol price history for {trendyol_url}: {e}")
        raise


                                                      
def _abs_trendyol_url(href: str) -> str:
    if not href:
        return ""
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return "https://www.trendyol.com" + href
    return "https://www.trendyol.com/" + href.lstrip("/")


def _parse_listing_products(html: str, limit: int = 3) -> List[Tuple[str, Optional[float], str]]:
    """
    Пытаемся распарсить карточки товаров со страниц листинга Trendyol.
    Возвращает список (title, price, url).
    Алгоритм:
      1) Попытка достать данные из window.__SEARCH_*_INITIAL_STATE__ (JSON в <script>)
      2) Если не удалось — парсинг карточек из HTML
      3) Фолбэк — ссылки на /p- или -p- и ближайшая цена
    """
    out: List[Tuple[str, Optional[float], str]] = []
    try:
                                                           
                                                                                  
                                                                
        patterns = [
            r"window\.__[A-Z0-9_]*INITIAL_STATE__\s*=\s*(\{.*?\})\s*;",
            r"window\.__SEARCH_APP_INITIAL_STATE__\s*=\s*(\{.*?\})\s*;",
            r"window\.__SEARCH_INITIAL_STATE__\s*=\s*(\{.*?\})\s*;",
            r"window\.__SEARCH_RESULT_APP_INITIAL_STATE__\s*=\s*(\{.*?\})\s*;",
        ]
        data_obj = None
        for pat in patterns:
            m = re.search(pat, html, flags=re.S)
            if m:
                try:
                    data_obj = json.loads(m.group(1))
                    break
                except Exception:
                    data_obj = None

        def _num(x) -> Optional[float]:
            if x is None:
                return None
            try:
                return float(x)
            except Exception:
                try:
                    return parse_price_text(str(x))
                except Exception:
                    return None

        def _collect_products(obj) -> List[Tuple[str, Optional[float], str]]:
            res: List[Tuple[str, Optional[float], str]] = []
            try:
                if isinstance(obj, list):
                    for it in obj:
                        res.extend(_collect_products(it))
                elif isinstance(obj, dict):
                                                       
                    if ("url" in obj or "productUrl" in obj) and any(
                        k in obj for k in ("name", "productName", "title", "brand")
                    ):
                        title_parts = []
                        for k in ("brand", "name", "productName", "title"):
                            v = obj.get(k)
                            if isinstance(v, str) and v.strip():
                                title_parts.append(v.strip())
                        title = " ".join(dict.fromkeys(title_parts)) if title_parts else ""

                        url = obj.get("url") or obj.get("productUrl") or ""
                        url = _abs_trendyol_url(url)

                        price = None
                                      
                        for key in ("price", "discountedPrice", "salePrice", "listingPrice", "marketPrice"):
                            if key in obj:
                                cand = obj.get(key)
                                if isinstance(cand, dict):
                                    cand = cand.get("value") or cand.get("amount")
                                p = _num(cand)
                                if p:
                                    price = p
                                    break

                        if title and url:
                            res.append((title, price, url))

                                               
                    for v in obj.values():
                        res.extend(_collect_products(v))
            except Exception:
                pass
            return res

        if data_obj is not None:
            items = _collect_products(data_obj)
                                                 
            seen = set()
            deduped: List[Tuple[str, Optional[float], str]] = []
            for title, price, url in items:
                if not url or url in seen:
                    continue
                seen.add(url)
                deduped.append((title, price, url))
                if len(deduped) >= limit:
                    break
            if deduped:
                return deduped

                          
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select('div.p-card-wrppr, div.p-card-chldrn-cntnr, div.product-card, div.card, div.col-lg-3, div.srch-prdcts *')
        if cards:
            for card in cards:
                        
                a = card.select_one('a[href*="/p-"], a[href*="-p-"]') or card.find("a", href=re.compile("(/p-|\\-p\\-)"))
                href = a.get("href") if a else ""
                url = _abs_trendyol_url(href or "")

                           
                title_el = (
                    card.find("span", class_=re.compile("(prdct-desc|product|title)", re.I)) or
                    card.find("div", class_=re.compile("(prdct-desc|product|title)", re.I)) or
                    (a if a and a.get("title") else None)
                )
                title = (title_el.get("title") if title_el and title_el.get("title") else title_el.get_text(" ", strip=True) if title_el else "")
                title = (title or "").strip()

                      
                price_el = (
                    card.select_one('div[class*="prc-box"] span, span.prc-dsc, span.prc-org, span[class*="price"]')
                    or card.find("span", class_=re.compile("prc-dsc|prc-org|price", re.I))
                    or card.find("div", class_=re.compile("price", re.I))
                )
                price_text = price_el.get_text(" ", strip=True) if price_el else ""
                price = parse_price_text(price_text)

                if title and url:
                    out.append((title, price, url))
                    if len(out) >= limit:
                        return out

                                                                              
        for a in soup.select('a[href*="/p-"], a[href*="-p-"]'):
            title = (a.get("title") or a.get_text(" ", strip=True) or "").strip()
            href = a.get("href") or ""
            url = _abs_trendyol_url(href)
                                  
            price_text = None
            prc = a.find_next("span", class_=re.compile("(prc|price)", re.I))
            if prc:
                price_text = prc.get_text(" ", strip=True)
            price = parse_price_text(price_text or "")
            if title and url:
                out.append((title, price, url))
                if len(out) >= limit:
                    break

                                                                                            
                                                                                       
                                                                     
        if not out:
            seen_links = set()
            candidates = []
            for a in soup.select('a[href*="/p-"], a[href*="-p-"]'):
                href = a.get('href') or ''
                url = _abs_trendyol_url(href)
                if url and url not in seen_links:
                    seen_links.add(url)
                    candidates.append(url)
                if len(candidates) >= limit * 5:
                    break

            for prod_url in candidates:
                try:
                                                       
                    if SCRAPER is not None:
                        p = SCRAPER.get(prod_url, headers=HEADERS, timeout=10)
                    else:
                        p = requests.get(prod_url, headers=HEADERS, timeout=10)
                    if p.status_code != 200:
                        continue
                    title = get_product_title(prod_url) or ''
                    price = get_price(prod_url)
                    if title:
                        out.append((title, price, prod_url))
                    if len(out) >= limit:
                        break
                except Exception:
                    continue
    except Exception as e:
        print("_parse_listing_products error:", e)
    return out


def _fetch_first_working_listing(urls: List[str], limit: int = 3) -> List[Tuple[str, Optional[float], str]]:
    """
    Перебираем набор URL с разными стратегиями сортировки, возвращаем первые распаршенные карточки.
    """
    for u in urls:
        try:
            if SCRAPER is not None:
                r = SCRAPER.get(u, headers=HEADERS, timeout=15)
            else:
                r = requests.get(u, headers=HEADERS, timeout=15)
            if r.status_code != 200:
                continue
            items = _parse_listing_products(r.text, limit=limit)
            if items:
                return items
        except Exception:
            continue
    return []


def _get_trending_listing(cache_key: str, urls: List[str], limit: int = 3) -> List[Tuple[str, Optional[float], str]]:
    cached = _get_trending_cached_result(cache_key)
    if cached is not None:
        return cached[:limit]

    result = _fetch_first_working_listing(urls, limit=limit)
    if result:
        _set_trending_cached_result(cache_key, result)
        return result[:limit]

    stale = _get_trending_cached_result(cache_key, allow_stale=True)
    if stale is not None:
        logger.info("Using stale trending cache for %s", cache_key)
        return stale[:limit]

    return []


def _trendyol_search_item(title: str, query: str) -> Tuple[str, Optional[float], str]:
    q = quote_plus((query or "").strip())
    return (title, None, f"https://www.trendyol.com/sr?q={q}")


def get_trending_all_top3() -> List[Tuple[str, Optional[float], str]]:
    """
    Пытаемся получить топ-3 по всему сайту (самые продаваемые).
    Сначала пробуем реальные запросы к Trendyol, если не получается -
    возвращаем популярные товары как заглушки для демонстрации функционала.
    """
    candidates = [
                                       
        "https://www.trendyol.com/sr?q=iphone",
        "https://www.trendyol.com/sr?q=samsung",
        "https://www.trendyol.com/sr?q=nike",
        "https://www.trendyol.com/sr?q=adidas",
                            
        "https://www.trendyol.com/sr?q=elbise",
        "https://www.trendyol.com/sr?q=ayakkabi",
        "https://www.trendyol.com/sr?q=telefon",
    ]

    result = _get_trending_listing("all", candidates, limit=3)

                                                                            
    if not result:
        logger.warning("Trendyol listings unavailable, returning search shortcuts")
        return [
            _trendyol_search_item("Trendyol search: iPhone", "iphone"),
            _trendyol_search_item("Trendyol search: Samsung", "samsung"),
            _trendyol_search_item("Trendyol search: shoes", "ayakkabi"),
        ]

    return result


def get_trending_by_search_top3(query: str) -> List[Tuple[str, Optional[float], str]]:
    """
    Топ-3 по пользовательскому запросу.
    Сначала пробуем реальные запросы к Trendyol, если не получается -
    возвращаем демо-данные для демонстрации функционала.
    """
    q = quote_plus((query or "").strip())
    if not q:
        return []

    candidates = [
        f"https://www.trendyol.com/sr?q={q}",
        f"https://www.trendyol.com/sr?q={q}&sst=mostSold",
        f"https://www.trendyol.com/sr?q={q}&sort=mostSold",
    ]

    result = _get_trending_listing(f"search:{q}", candidates, limit=3)

                                                                          
    if not result:
        logger.warning("Trendyol search unavailable for query %r, returning search shortcut", query)
        return [_trendyol_search_item(f"Trendyol search: {query.strip()}", query)]

    return result


CATEGORY_QUERY_MAP = {
    "electronics": "elektronik",
    "clothing": "giyim",
    "shoes": "ayakkabi",
    "home": "ev",
}


def get_trending_by_category_top3(category_key: str) -> List[Tuple[str, Optional[float], str]]:
    """
    Топ-3 по предустановленным "категориям" (по сути — ключевые слова).
    """
    key = (category_key or "").lower()
    q = CATEGORY_QUERY_MAP.get(key, key)                                                     
    if not q:
        return []

                                    
    candidates = [f"https://www.trendyol.com/sr?q={quote_plus(q)}"]
    result = _get_trending_listing(f"category:{key}:{quote_plus(q)}", candidates, limit=3)

                                                           
    if not result:
        logger.warning("Trendyol category search unavailable for %r, returning search shortcut", key)
        return [_trendyol_search_item(f"Trendyol category: {key or q}", q)]

    return result


                
async def get_trending_all_top3_async() -> List[Tuple[str, Optional[float], str]]:
    return await asyncio.wait_for(asyncio.to_thread(get_trending_all_top3), timeout=30.0)


async def get_trending_by_search_top3_async(query: str) -> List[Tuple[str, Optional[float], str]]:
    return await asyncio.wait_for(asyncio.to_thread(get_trending_by_search_top3, query), timeout=30.0)


async def get_trending_by_category_top3_async(category_key: str) -> List[Tuple[str, Optional[float], str]]:
    return await asyncio.wait_for(asyncio.to_thread(get_trending_by_category_top3, category_key), timeout=30.0)
