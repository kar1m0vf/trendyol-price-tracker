"""
Тест валидации и обработки ошибок в обработчиках команд
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

print("=" * 60)
print("ТЕСТИРОВАНИЕ ВАЛИДАЦИИ И ОБРАБОТКИ ОШИБОК")
print("=" * 60)

issues = []

                                          
print("\n[1] Проверка распаковки кортежей подписок...")
import bot
import database

                           
test_user = 999999
test_url = "https://www.trendyol.com/test-p-123"
sub_id = database.add_subscription(test_user, test_url, mode="hourly")

                   
sub = database.get_subscription(sub_id)
if sub:
    print(f"✅ Подписка получена: {len(sub)} полей")
    
                                               
    try:
        if len(sub) >= 13:
                                        
            (sid, uid, url, mode, last_price, title, image,
             min_price, max_price, notify_percent, notify_interval, last_notify_time, price_alert) = sub
            print("✅ Распаковка 13 полей работает")
        elif len(sub) >= 12:
                                           
            (sid, uid, url, mode, last_price, title, image,
             min_price, max_price, notify_percent, notify_interval, last_notify_time) = sub[:12]
            price_alert = None
            print("✅ Распаковка 12 полей работает (fallback)")
        else:
            issues.append(f"Подписка имеет неожиданное количество полей: {len(sub)}")
            print(f"⚠️  Неожиданное количество полей: {len(sub)}")
    except ValueError as e:
        issues.append(f"Ошибка распаковки подписки: {e}")
        print(f"❌ Ошибка распаковки: {e}")
    
             
    database.remove_subscription(sub_id)

                           
print("\n[2] Проверка валидации URL...")
test_urls = [
    ("https://www.trendyol.com/product-p-123", True),
    ("https://www.trendyol.com/brand/product-p-123", True),
    ("https://www.trendyol.com/", False),
    ("https://example.com/product", False),
    ("not-a-url", False),
    ("", False),
    (None, False),
]

for url, should_be_valid in test_urls:
    try:
        normalized = bot.normalize_url(url) if url else ""
        is_valid = bot.is_trendyol_product_url(normalized) if normalized else False
        if is_valid != should_be_valid:
            issues.append(f"URL валидация: '{url}' - ожидалось {should_be_valid}, получено {is_valid}")
            print(f"⚠️  URL '{url}': ожидалось {should_be_valid}, получено {is_valid}")
        else:
            url_display = str(url)[:50] if url else "None"
            print(f"✅ URL '{url_display}': {is_valid}")
    except Exception as e:
        issues.append(f"Ошибка валидации URL '{url}': {e}")
        print(f"❌ Ошибка валидации URL '{url}': {e}")

                         
print("\n[3] Проверка функции локализации...")
test_keys = [
    "start_text",
    "help_text",
    "error_generic",
    "no_subs",
    "cmd_stats_usage",
    "price_alert_usage"
]

for key in test_keys:
    try:
        result = bot.t(999999, key)
        if result == key:
                                                                                    
            print(f"⚠️  Ключ '{key}' не найден (fallback на ключ)")
        else:
            print(f"✅ Ключ '{key}': найдено")
    except Exception as e:
        issues.append(f"Ошибка локализации для ключа '{key}': {e}")
        print(f"❌ Ошибка локализации '{key}': {e}")

                                     
print("\n[4] Проверка обработки None значений...")
try:
                               
    result = bot.normalize_url(None)
    if result == "":
        print("✅ normalize_url(None) возвращает пустую строку")
    else:
        issues.append(f"normalize_url(None) вернул '{result}' вместо ''")
    
                                         
    result = bot.is_trendyol_product_url(None)
    if result == False:
        print("✅ is_trendyol_product_url(None) возвращает False")
    else:
        issues.append(f"is_trendyol_product_url(None) вернул {result} вместо False")
        
except Exception as e:
    issues.append(f"Ошибка обработки None: {e}")
    print(f"❌ Ошибка обработки None: {e}")

print("\n" + "=" * 60)
if issues:
    print(f"⚠️  Найдено проблем: {len(issues)}")
    for i, issue in enumerate(issues[:10], 1):
        print(f"  {i}. {issue}")
    if len(issues) > 10:
        print(f"  ... и еще {len(issues) - 10} проблем")
else:
    print("✅ ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ УСПЕШНО!")
print("=" * 60)

