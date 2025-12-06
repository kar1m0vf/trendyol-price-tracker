# scraper.py
import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime
from urllib.parse import quote_plus
from typing import List, Tuple, Optional
import asyncio
import json
import time
from utils import setup_logger, retry, async_retry, RateLimiter, AsyncRateLimiter
try:
    import cloudscraper
    SCRAPER = cloudscraper.create_scraper()
except Exception:
    SCRAPER = None

# Настройка логирования
logger = setup_logger('scraper', 'scraper.log')

# Rate limiter для запросов к Trendyol (максимум 30 запросов в минуту)
TRENDYOL_LIMITER = RateLimiter(max_requests=30, time_window=60)
ASYNC_TRENDYOL_LIMITER = AsyncRateLimiter(max_requests=30, time_window=60)

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
        # Оставляем только цифры и разделители
        t = re.sub(r"[^0-9.,]", "", t)

        if not t:
            return None

        has_dot = "." in t
        has_comma = "," in t

        # Оба разделителя присутствуют
        if has_dot and has_comma:
            # Последний разделитель считаем десятичным
            last_dot = t.rfind(".")
            last_comma = t.rfind(",")
            if last_comma > last_dot:
                # десятичный ','
                t = t.replace(".", "")        # убрать тысячи
                t = t.replace(",", ".")       # десятичный -> '.'
            else:
                # десятичный '.'
                t = t.replace(",", "")        # убрать тысячи
            return float(t)

        # Только запятая
        if has_comma and not has_dot:
            # Если 1,23 -> десятичный; если 1,234 -> вероятно тысячи (удаляем запятую)
            parts = t.split(",")
            if len(parts[-1]) in (1, 2):  # десятичная часть
                t = t.replace(",", ".")
                return float(t)
            # иначе нет десятичной части, запятые - тысячи
            t = t.replace(",", "")
            return float(t)

        # Только точка
        if has_dot and not has_comma:
            parts = t.split(".")
            if len(parts[-1]) in (1, 2):
                return float(t)
            # иначе точки - тысячи
            t = t.replace(".", "")
            return float(t)

        # Нет разделителей, просто число
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
      1) meta product:price:amount
    def get_price(url: str) -> Optional[float]:
      3) Явные селекторы скидочной/обычной цены (prc-dsc, prc-org и др.)
      4) Регекс по '... TL' в тексте страницы (ограниченный, чтобы не брать произвольные числа)
    """
    try:
        if not TRENDYOL_LIMITER.can_proceed():
            logger.warning(f"Rate limit exceeded while fetching price for {url}")
            time.sleep(2)  # Ждем немного перед повторной попыткой
            
        TRENDYOL_LIMITER.add_request()
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()  # Вызовет HTTPError если статус не 200
        
        if r.status_code != 200:
            logger.error(f"HTTP {r.status_code} when fetching price for {url}")
            # Use cloudscraper when available to bypass Cloudflare challenges
            if SCRAPER is not None:
                r = SCRAPER.get(url, headers=HEADERS, timeout=15)
            else:
                r = requests.get(url, headers=HEADERS, timeout=15)

        soup = BeautifulSoup(r.text, "html.parser")

        # 1) meta product:price:amount (чаще всего корректно)
        meta = soup.find("meta", {"property": "product:price:amount"})
        if meta and meta.get("content"):
            p = parse_price_text(meta["content"])
            if p is not None:
                return p

        # 2) JSON-LD (offers.price)
        for script in soup.find_all("script", type=re.compile("ld\\+json")):
            try:
                data = json.loads(script.string or "")
            except Exception:
                continue
            # В JSON-LD может быть объект или массив
            def try_extract(obj) -> Optional[float]:
                if not isinstance(obj, (dict, list)):
                    return None
                if isinstance(obj, list):
                    for item in obj:
                        val = try_extract(item)
                        if val is not None:
                            return val
                else:
                    # Популярные места цены
                    offers = obj.get("offers") if isinstance(obj, dict) else None
                    if isinstance(offers, dict):
                        price = offers.get("price") or offers.get("lowPrice") or offers.get("highPrice")
                        p = parse_price_text(str(price)) if price is not None else None
                        if p is not None:
                            return p
                    # прямой price
                    if "price" in obj:
                        p = parse_price_text(str(obj["price"]))
                        if p is not None:
                            return p
                    # вложенные объекты
                    for v in obj.values():
                        val = try_extract(v)
                        if val is not None:
                            return val
                return None

            val = try_extract(data)
            if val is not None:
                return val

        # 3) Популярные селекторы Trendyol (актуальные классы могут меняться)
        selectors = [
            "span.prc-dsc",        # скидочная цена
            "span.prc-org",        # обычная цена
            'span[class*="prc"]',  # любые цены с префиксом prc-
            'span[class*="price"]',
            'div[class*="price"] span',
        ]
        for sel in selectors:
            el = soup.select_one(sel)
            if el:
                p = parse_price_text(el.get_text(" ", strip=True))
                if p is not None and p > 0:
                    return p

        # 4) Регекс по шаблону "<число> TL"
        #    Находим числа только рядом с "TL", чтобы не брать посторонние значения
        text = soup.get_text(" ", strip=True)
        for m in re.finditer(r"(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?)\s*TL", text):
            p = parse_price_text(m.group(1))
            if p is not None and p > 0:
                return p

        return None
    except Exception as e:
        print("scraper.get_price error:", e)
        return None


def get_trending_sample() -> List[str]:
    return [
        "👟 Популярные кроссовки — скидки до 30%",
        "👜 Сумки — хит продаж",
        "📱 Чехлы и аксессуары — модные позиции"
    ]


# ----------------- History / Akakçe helpers -----------------

def get_product_title(url: str) -> Optional[str]:
    """
    Пытаемся вытащить название товара со страницы Trendyol.
    Возвращает строку или None.
    """
    try:
        if SCRAPER is not None:
            r = SCRAPER.get(url, headers=HEADERS, timeout=15)
        else:
            r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        # пробуем несколько селекторов
        candidates = [
            ("h1", None),
            ("h1", {"class": re.compile("product", re.I)}),
            ("h1", {"class": re.compile("title", re.I)}),
            ("title", None)
        ]
        for tag, attrs in candidates:
            el = soup.find(tag, attrs=attrs) if attrs else soup.find(tag)
            if el:
                txt = el.get_text(strip=True)
                if txt:
                    return txt
    except Exception as e:
        print("get_product_title error:", e)
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
        # og:image
        meta = soup.find("meta", property="og:image")
        if meta and meta.get("content"):
            return meta["content"]

        # link rel image_src
        link = soup.find("link", rel="image_src")
        if link and link.get("href"):
            return link["href"]

        # Попробуем найти первый крупный <img>
        imgs = soup.find_all("img", src=True)
        best = None
        for img in imgs:
            src = img.get("src") or img.get("data-src")
            if not src:
                continue
            # игнорируем маленькие иконки
            w = img.get("width")
            h = img.get("height")
            try:
                if w and int(w) < 50:
                    continue
                if h and int(h) < 50:
                    continue
            except Exception:
                pass
            # выбираем первый подходящий
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
        # ищем массивы в JSON-подобной форме: [{"date":"2025-08-01","price":799},...]
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
        # ищем пары: дата + цена TL
        pairs = re.findall(r"(\d{1,2}\.\d{1,2}\.\d{2,4}|\d{4}-\d{2}-\d{2}).{0,20}?(\d+[.,]?\d*)\s*TL", text)
        if pairs:
            out = []
            for date_str, price_str in pairs:
                # нормализуем дату
                ds = date_str.replace(".", "-")
                try:
                    price = float(price_str.replace(".", "").replace(",", "."))
                    out.append((ds, price))
                except:
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

        q = quote_plus(title)
        search_url = f"https://www.akakce.com/arama?q={q}"
        logger.info(f"Searching price history for '{title}'...")
        r = requests.get(search_url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "html.parser")

        # попробуем найти первую релевантную ссылку на товар
        link = None
        # ищем ссылки с типичными паттернами
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if any(seg in href for seg in ("/p-", "/urun/", "/product/", "/urunler/")):
                link = href
                break
        if not link:
            a = soup.select_one("a[href*='/p-'], a[href*='/urun/'], a[href*='/product/']")
            if a:
                link = a.get("href")

        if not link:
            return None

        # нормализуем ссылку
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

        # 1) Попытка через скрипты (JSON)
        hist = _try_parse_price_history_from_script(soup2)
        if hist:
            return hist

        # 2) Попытка через HTML-блоки/таблицы
        hist = _try_parse_html_table_history(soup2)
        if hist:
            return hist

        # 3) Поиск чисел и дат в тексте страницы
        txt = soup2.get_text(" ", strip=True)
        pairs = re.findall(r"(\d{1,2}\.\d{1,2}\.\d{2,4}|\d{4}-\d{2}-\d{2}).{0,20}?(\d+[.,]?\d*)\s*TL", txt)
        if pairs:
            out = []
            for date_str, price_str in pairs:
                ds = date_str.replace(".", "-")
                try:
                    price = float(price_str.replace(".", "").replace(",", "."))
                    out.append((ds, price))
                except:
                    continue
            if out:
                return out

    except Exception as e:
        print("get_price_history_from_akakce error:", e)
    return None


# ----------------- Async wrappers (non-blocking) -----------------
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
        await asyncio.sleep(2)  # Ждем немного перед повторной попыткой
        
    await ASYNC_TRENDYOL_LIMITER.add_request()
    try:
        return await asyncio.to_thread(get_price, url)
    except Exception as e:
        logger.error(f"Error fetching price for {url}: {e}")
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

    return await asyncio.to_thread(_sync)


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
        res = await asyncio.to_thread(get_price_history_from_akakce, trendyol_url)
        if res:
            logger.info("get_price_history_from_akakce_async: found %d points for %s", len(res), trendyol_url)
            return res
        # Fallback: try direct Trendyol parsing
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
        pattern = re.compile(rf"{re.escape(varname)}\s*=\s*(\{{.*?\}})\s*;", re.S)
        m = pattern.search(text)
        if not m:
            return None
        json_text = m.group(1)
        # Try to make JSON-safe: remove JS trailing commas
        json_text = re.sub(r",\s*([}\]])", r"\1", json_text)
        # Replace single quotes with double where likely
        json_text = json_text.replace("\'", "\\'")
        try:
            return json.loads(json_text)
        except Exception:
            # Attempt more tolerant eval via simple replacements
            cleaned = json_text
            cleaned = re.sub(r"(\w+)\s*:\s*", r'"\1":', cleaned)  # convert keys without quotes
            cleaned = cleaned.replace("'", '"')
            cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
            return json.loads(cleaned)
    except Exception:
        logger.debug("_extract_json_from_js_var failed for %s", varname, exc_info=True)
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

        # 1) try to extract explicit JS var
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

        # 2) if not found, try to find any JSON-like in scripts that contains 'priceHistory'
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
            # If we didn't find embedded initial state, we'll later try internal API
            # but continue to try to extract listing identifiers from the HTML below.
            pass

        # Traverse to find priceHistory-like arrays
        def find_price_history(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    if k and 'price' in k.lower() and isinstance(v, list):
                        # crude heuristic
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
            # fallthrough to try calling internal Trendyol SANTRAL price-history API
            # using listingId(s) discovered on the page
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
                # item may be dict with date/price keys
                if isinstance(item, dict):
                    # check common key names
                    date = item.get('date') or item.get('t') or item.get('x') or item.get('time')
                    price = item.get('price') or item.get('y') or item.get('p') or item.get('value')
                    if date and price is not None:
                        out.append((str(date), float(price)))
                elif isinstance(item, list) and len(item) >= 2:
                    # [timestamp, price]
                    d, p = item[0], item[1]
                    out.append((str(d), float(p)))
                else:
                    # try to parse strings like "2025-08-01:799"
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
        # Common occurrences: "listingId":"abcd..." or listingId":"abcd...",
        for m in re.finditer(r'"listingId"\s*:\s*"([0-9a-fA-F-]+)"', html):
            ids.append(m.group(1))

        # Also look for winnerVariant or variants sections that may include listingId
        for m in re.finditer(r'listingId\s*[:=]\s*"([0-9a-fA-F-]+)"', html):
            ids.append(m.group(1))

    except Exception:
        logger.debug("_extract_listing_ids_from_html failed", exc_info=True)
    # preserve order, unique
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
        # Try GET first
        if SCRAPER is not None:
            r = SCRAPER.get(base, params=params, headers=headers, timeout=15)
        else:
            r = requests.get(base, params=params, headers=headers, timeout=15)
        if r.status_code == 200:
            try:
                return r.json()
            except Exception:
                return None

        # If GET failed, try POST with JSON payload
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

            # Try to find a price-history array anywhere in returned JSON
            def find_price_array(o):
                if isinstance(o, dict):
                    for k, v in o.items():
                        if isinstance(v, list) and v:
                            # Heuristic: list of dicts containing price/date keys
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
                        # Common key candidates
                        # date/time: createdAt, createdDate, date, timestamp
                        date = (item.get('createdAt') or item.get('createdDate') or item.get('date') or
                                item.get('time') or item.get('ts') or item.get('timestamp'))
                        # price: price, sellingPrice, discountedPrice, value
                        price = (item.get('price') or item.get('sellingPrice') or item.get('discountedPrice') or
                                 item.get('value') or item.get('amount'))
                        # If nested price object
                        if isinstance(price, dict):
                            price = price.get('value') or price.get('amount') or price.get('sellingPrice')
                        if date and price is not None:
                            # Normalize timestamp-like numbers
                            if isinstance(date, (int, float)):
                                # assume epoch ms or s
                                if date > 1e12:
                                    # ms
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
                                # try parse_price_text
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
        return await asyncio.to_thread(get_price_history_from_trendyol, trendyol_url)
    except Exception as e:
        logger.error(f"Error fetching Trendyol price history for {trendyol_url}: {e}")
        raise


# ----------------- Trending (Top-3) -----------------
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
        # 1) Попытка JSON-инициализации (SSR/state скрипты)
        # Попробуем найти любой скрипт инициализации, содержащий "INITIAL_STATE" —
        # вёрстка Trendyol может менять точные имена переменных.
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
                    # проверяем, похоже ли это на товар
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
                        # варианты цен
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

                    # рекурсивный обход словаря
                    for v in obj.values():
                        res.extend(_collect_products(v))
            except Exception:
                pass
            return res

        if data_obj is not None:
            items = _collect_products(data_obj)
            # Удаляем дубли по URL и ограничиваем
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

        # 2) HTML-карточки
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select('div.p-card-wrppr, div.p-card-chldrn-cntnr, div.product-card, div.card, div.col-lg-3, div.srch-prdcts *')
        if cards:
            for card in cards:
                # ссылка
                a = card.select_one('a[href*="/p-"], a[href*="-p-"]') or card.find("a", href=re.compile("(/p-|\\-p\\-)"))
                href = a.get("href") if a else ""
                url = _abs_trendyol_url(href or "")

                # заголовок
                title_el = (
                    card.find("span", class_=re.compile("(prdct-desc|product|title)", re.I)) or
                    card.find("div", class_=re.compile("(prdct-desc|product|title)", re.I)) or
                    (a if a and a.get("title") else None)
                )
                title = (title_el.get("title") if title_el and title_el.get("title") else title_el.get_text(" ", strip=True) if title_el else "")
                title = (title or "").strip()

                # цена
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

        # 3) Фолбэк — ссылки на /p- или -p- (страницы товара) + ближайшая цена
        for a in soup.select('a[href*="/p-"], a[href*="-p-"]'):
            title = (a.get("title") or a.get_text(" ", strip=True) or "").strip()
            href = a.get("href") or ""
            url = _abs_trendyol_url(href)
            # ищем цену поблизости
            price_text = None
            prc = a.find_next("span", class_=re.compile("(prc|price)", re.I))
            if prc:
                price_text = prc.get_text(" ", strip=True)
            price = parse_price_text(price_text or "")
            if title and url:
                out.append((title, price, url))
                if len(out) >= limit:
                    break

        # 4) Надёжный фолбэк: если всё ещё пусто, возьмём первые уникальные ссылки на товары
        # и откроем их страницы, чтобы получить title/price напрямую. Это медленнее, но
        # значительно повышает шансы на успех при изменчивой вёрстке.
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
                    # Получаем данные с карточки товара
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


def get_trending_all_top3() -> List[Tuple[str, Optional[float], str]]:
    """
    Пытаемся получить топ-3 по всему сайту (самые продаваемые).
    Используем разные значения сортировки (sst) и фолбэк на “широкий” поиск по букве.
    Добавлены параметры os=1 и pi=1 для повышения вероятности SSR-контента.
    Если парсинг не удался — возвращаем пустой список (бот покажет понятное сообщение).
    """
    base = "https://www.trendyol.com/sr"
    candidates = [
        f"{base}?os=1&pi=1&sst=mostSold",
        f"{base}?os=1&pi=1&sst=mostSelling",
        f"{base}?os=1&pi=1&sst=MOST_SELLING",
        f"{base}?os=1&pi=1&sst=most_favorited",
        f"{base}?os=1&pi=1&q=a&sst=mostSold",
        f"{base}?os=1&pi=1&q=e&sst=mostSold",
        f"{base}?os=1&pi=1&q=o&sst=mostSold",
        f"{base}?os=1&pi=1&q=i&sst=mostSold",
    ]
    return _fetch_first_working_listing(candidates, limit=3)


def get_trending_by_search_top3(query: str) -> List[Tuple[str, Optional[float], str]]:
    """
    Топ-3 по пользовательскому запросу; пробуем sst и альтернативные sort + os=1&pi=1.
    Если парсинг не удался — возвращаем пустой список (бот покажет понятное сообщение).
    """
    q = quote_plus((query or "").strip())
    base = "https://www.trendyol.com/sr"
    candidates = [
        f"{base}?os=1&pi=1&q={q}&sst=mostSold",
        f"{base}?os=1&pi=1&q={q}&sst=mostSelling",
        f"{base}?os=1&pi=1&q={q}&sst=MOST_SELLING",
        f"{base}?os=1&pi=1&q={q}&sst=most_favorited",
        f"{base}?os=1&pi=1&q={q}&sort=mostSold",
        f"{base}?os=1&pi=1&q={q}&sort=MOST_SELLING",
        f"{base}?os=1&pi=1&q={q}&sort=most_favorited",
    ]
    return _fetch_first_working_listing(candidates, limit=3)


CATEGORY_QUERY_MAP = {
    "electronics": "elektronik",
    "clothing": "giyim",
    "shoes": "ayakkabı",
    "home": "ev",
}


def get_trending_by_category_top3(category_key: str) -> List[Tuple[str, Optional[float], str]]:
    """
    Топ-3 по предустановленным “категориям” (по сути — ключевые слова).
    """
    key = (category_key or "").lower()
    q = CATEGORY_QUERY_MAP.get(key, key)  # если пришёл собственный ключ — пробуем как запрос
    if not q:
        return []
    return get_trending_by_search_top3(q)


# Async wrappers
async def get_trending_all_top3_async() -> List[Tuple[str, Optional[float], str]]:
    return await asyncio.to_thread(get_trending_all_top3)


async def get_trending_by_search_top3_async(query: str) -> List[Tuple[str, Optional[float], str]]:
    return await asyncio.to_thread(get_trending_by_search_top3, query)


async def get_trending_by_category_top3_async(category_key: str) -> List[Tuple[str, Optional[float], str]]:
    return await asyncio.to_thread(get_trending_by_category_top3, category_key)
