import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from database import add_subscription, add_price_point, get_price_stats, get_top_price_drops, remove_subscription
import time

TEST_USER = 999999

print('Creating test subscription...')
sub_id = add_subscription(TEST_USER, 'https://www.trendyol.com/test-p-wave2', product_title='Wave2 Test Product')
print('Created subscription id:', sub_id)

                                                                 
now = int(time.time())
for i in range(30):
    ts = now - (29 - i) * 24 * 3600
                                                          
    if i < 15:
        price = 3000 - i * 66
    else:
        price = 2000 + (i - 15) * 40
    add_price_point(sub_id, 'https://www.trendyol.com/test-p-wave2', float(price), ts)

print('Inserted 30 price points')

print('Getting stats...')
stats = get_price_stats(sub_id)
print('Stats:', stats)

print('Getting top drops for TEST_USER...')
drops = get_top_price_drops(TEST_USER, limit=5)
print('Top drops:', drops)

print('Cleaning up...')
removed = remove_subscription(sub_id)
print('Subscription removed:', removed)
print('Done')
