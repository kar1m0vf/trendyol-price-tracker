"""
Backfill price_history using Wayback CDX snapshots for subscription URLs.
Run manually after making a DB backup. This script is best-effort and respects simple rate limits.
Usage:
    python tools/backfill_price_history.py [--limit N] [--days 3650]

It will iterate subscriptions and for each subscription query the Wayback CDX API for snapshots
and attempt to fetch snapshot pages and extract a price using scraper.get_price. Found points
are inserted with source='wayback'.

WARNING: Run only after full DB backup.
"""
import argparse
import time
import requests
from urllib.parse import quote_plus
from datetime import datetime
import json
import sqlite3
import logging
import os

# Use relative imports from project
from scraper import get_price
from database import get_all_subscriptions, add_price_point

CDX_URL = "http://web.archive.org/cdx/search/cdx"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PriceBackfill/1.0; +https://example.com)"
}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('backfill')


def query_cdx(url, from_ts=None, to_ts=None, limit=50):
    params = {
        'url': url,
        'output': 'json',
        'filter': 'statuscode:200',
        'limit': limit,
        'collapse': 'digest'
    }
    if from_ts:
        params['from'] = from_ts
    if to_ts:
        params['to'] = to_ts
    try:
        r = requests.get(CDX_URL, params=params, headers=HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json()
        # first row is header
        if len(data) <= 1:
            return []
        rows = data[1:]
        # rows: [timestamp, original, ...] depending on output; default includes timestamp at index 1
        snapshots = []
        for row in rows:
            # some CDX endpoints return ["original","timestamp",...]
            if len(row) >= 2:
                ts = row[1]
                snapshots.append(ts)
        return snapshots
    except Exception as e:
        logger.exception("CDX query failed for %s: %s", url, e)
        return []


def fetch_wayback_snapshot(url, timestamp):
    snap_url = f"http://web.archive.org/web/{timestamp}id_/{url}"
    try:
        r = requests.get(snap_url, headers=HEADERS, timeout=20)
        if r.status_code == 200:
            return r.text
    except Exception as e:
        logger.debug("Failed fetch snapshot %s: %s", snap_url, e)
    return None


def main(limit=None, days=None):
    subs = get_all_subscriptions()
    logger.info("Found %d subscriptions to backfill", len(subs))
    count_points = 0
    for sub in subs:
        sub_id = sub[0]
        url = sub[2]
        logger.info("Processing sub %s %s", sub_id, url)
        snapshots = query_cdx(url, limit=limit or 50)
        if not snapshots:
            logger.info("No snapshots for %s", url)
            continue
        # iterate snapshots from oldest to newest
        for ts in sorted(snapshots):
            # optional date filtering
            if days:
                try:
                    snap_dt = datetime.strptime(ts, "%Y%m%d%H%M%S")
                    if (datetime.utcnow() - snap_dt).days > days:
                        continue
                except Exception:
                    pass
            try:
                snap_html = fetch_wayback_snapshot(url, ts)
                if not snap_html:
                    continue
                # try to extract price using get_price, but get_price expects live url; we can attempt parse with BeautifulSoup
                # simplest approach: save point with unknown price? Instead attempt to parse with scraper.parse_price_text via temporary file
                # We'll write snapshot to a temp file and use scraper.get_price on the original Wayback URL (it may not work), so
                # better: attempt simple regex for TL in snapshot
                import re
                m = re.search(r"(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?)\s*TL", snap_html)
                if m:
                    from scraper import parse_price_text
                    p = parse_price_text(m.group(1))
                    if p:
                        # convert snapshot ts to POSIX
                        try:
                            snap_dt = datetime.strptime(ts, "%Y%m%d%H%M%S")
                            snap_ts = int(snap_dt.timestamp())
                        except Exception:
                            snap_ts = None
                        add_price_point(sub_id, url, float(p), ts=snap_ts or None, source='wayback')
                        count_points += 1
                        logger.info("Saved point %s -> %s TL", ts, p)
                # be polite
                time.sleep(0.5)
            except Exception as e:
                logger.exception("Error processing snapshot %s for %s: %s", ts, url, e)
                continue
    logger.info("Backfill finished, points added: %d", count_points)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=50)
    parser.add_argument('--days', type=int, default=3650)
    args = parser.parse_args()
    main(limit=args.limit, days=args.days)
