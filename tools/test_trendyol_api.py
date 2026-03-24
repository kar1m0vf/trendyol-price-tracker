import requests
import json

BASE = "https://apigw.trendyol.com/discovery-pdp-websfxpricehistory-santral"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.trendyol.com/",
}

product_ids = ["318291787", "944315539"]

                                        
paths = ["", "/v1", "/v2", "/get", "/priceHistory", "/PriceHistory", "/price-history"]
param_names = ["productId", "product_id", "productIds", "productIds[]", "productIdList"]

for pid in product_ids:
    print(f"\n=== Trying product {pid} ===")
    for p in paths:
        url = BASE.rstrip('/') + p
        for param in param_names:
            params = {param: pid}
            try:
                r = requests.get(url, headers=HEADERS, params=params, timeout=10)
                print(f"URL: {url} params={param} -> status {r.status_code} len={len(r.text)}")
                                                 
                try:
                    j = r.json()
                    print("JSON keys:", list(j.keys()) if isinstance(j, dict) else type(j))
                    print(json.dumps(j, indent=2)[:2000])
                except Exception:
                                         
                    print(r.text[:1000])
                                                  
                if r.status_code == 200 and r.headers.get('Content-Type', '').lower().startswith('application/json') and len(r.text) > 50:
                    print("Likely valid response, moving to next product.")
                    raise StopIteration
            except StopIteration:
                break
            except Exception as e:
                print(f"Error calling {url} with {param}: {e}")
        else:
            continue
        break
    else:
        print(f"No successful pattern found for product {pid}")

print('\nDone')
