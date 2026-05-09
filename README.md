# Trendyol Price Tracker Bot

A Telegram service for tracking Trendyol product prices, managing personal watchlists, storing price history, and sending practical price-change notifications.

The project is built as a real service rather than a one-off script: it has Telegram workflows, persistent user state, background jobs, admin controls, localization, diagnostics, and tests. The source is visible, but the bot is not distributed as a reusable package or a ready-made third-party deployment.

## Problem

Trendyol prices change often, and manually checking product pages is repetitive. A useful price tracker needs to do more than fetch a number once:

- remember each user's products;
- avoid noisy notifications;
- keep price history;
- support different alert strategies;
- survive external parsing failures;
- give the owner tools to monitor and manage the service.

## Solution

The bot turns a Telegram chat into a product tracking interface. A user sends a Trendyol link, the bot extracts product data, saves the subscription, checks prices in the background, and notifies the user when a configured condition is met.

The core experience is designed around Telegram-native controls:

1. User sends `/start`.
2. User sends a Trendyol product URL.
3. Bot creates a tracked product card with price, mode, and controls.
4. User opens `/mysubs` and gets one compact watchlist message.
5. Product buttons open the selected product in-place.
6. User can view history, compare prices, set a target price, change mode, or unsubscribe.
7. Background jobs group notifications so users do not receive message spam.

Read the full product flow in [User Guide](docs/guides/USER_GUIDE.md).

## Product Capabilities

### Tracking And Alerts

- Add products from Trendyol URLs.
- Track each user's own watchlist.
- Show user-facing product numbers like `№ 1`, `№ 2`, `№ 3` instead of internal database IDs.
- Support discount-only mode, hourly mode, target price alerts, min/max thresholds, percent-change alerts, custom notification intervals, and quiet hours.
- Group multiple price updates into one notification when needed.

### Price Intelligence

- Store local price history in SQLite.
- Show price history and statistics.
- Generate price charts.
- Export subscriptions and price history as directly delivered CSV/JSON documents.
- Compare saved products or two direct product links.
- Use local history first and external history helpers where available.

### Discovery

- Show Trendyol trends.
- Support trend categories and search.
- Generate recommendations from user interests and an admin-managed recommendation catalog.

### Administration

- Admin dashboard through Telegram commands and inline controls.
- User overview and system statistics.
- Broadcasts.
- User report handling.
- Manual cleanup.
- Manual and scheduled database backups.
- Recommendation catalog management.
- Runtime health check.

### Localization

- RU, EN, AZ, and TR locale files.
- Locale consistency check through `check_locales.py`.

## Technical Highlights

| Area | Implementation |
| --- | --- |
| Telegram runtime | aiogram 3 router/dispatcher stack with package-based handlers |
| UX state | Inline callbacks, reply keyboards, in-place product cards, user-facing numbering |
| Persistence | SQLite schema, migrations, indexes, price history, recommendations, custom texts |
| Scheduler | APScheduler jobs for price checks and daily backups |
| Concurrency | Scheduler lock, task batching, network fetch semaphore, grouped notifications |
| Notifications | Safe send helpers, image fallback, grouped updates, chart delivery |
| Scraping | Trendyol product extraction, trends, category/search flows, history helpers |
| Admin tools | Stats, users, broadcasts, reports, cleanup, backups, recommendations |
| Quality | pytest suite, readiness check, deploy smoke check, locale key validation |
| Security posture | `.env` configuration, ignored runtime data, token validation, no production data in repo |

Detailed system notes are in [Architecture](docs/ARCHITECTURE.md).

## Command Surface

| Command | Purpose |
| --- | --- |
| `/start` | First launch and main menu |
| `/help` | User help |
| `/mysubs` | Personal tracked products |
| `/history 1` | Price history for product `№ 1` |
| `/stats 1` | Price statistics |
| `/compare 1` | Compare a saved product |
| `/compare <url1> <url2>` | Compare two product URLs |
| `/price_alert 1 2500` | Notify when product `№ 1` reaches 2500 TL or lower |
| `/settings` | Quiet hours, intervals, and thresholds |
| `/alerts` | Manage target prices |
| `/recommend` | Recommendations |
| `/export` | Export user subscriptions |
| `/health` | Admin health check |
| `/admin` | Admin panel |

Product numbers come from `/mysubs`. Internal database IDs are intentionally hidden from regular users.

## Architecture Snapshot

```text
Telegram user
    |
    v
aiogram Dispatcher / Router
    |
    +--> handlers/basic.py
    +--> handlers/subscription_handler.py
    +--> handlers/analytics_handler.py
    +--> handlers/callback_handler.py
    +--> handlers/admin_handler.py
    |
    v
bot.py runtime helpers
    |
    +--> database.py
    +--> scraper.py
    +--> services/notification_service.py
    +--> localization.py / locales/
    |
    v
SQLite + Telegram API + Trendyol
```

Key paths:

- `bot.py` - runtime factory, polling entry point, scheduler jobs, common helpers.
- `handlers/` - aiogram handlers for user, analytics, callback, and admin flows.
- `database.py` - SQLite schema, migrations, subscriptions, price history, recommendations, backups.
- `scraper.py` - Trendyol data extraction and trend/history helpers.
- `services/notification_service.py` - notifications and charts.
- `locales/` - translation files.
- `tools/diagnostics/deploy_smoke_check.py` - deploy smoke validation.
- `tests/` - behavioral and unit tests.

## Data And Security

- `.env` is private and ignored by git.
- `BOT_TOKEN` must only live in environment variables or `.env`.
- `trendyol_bot.db`, `logs/`, `backups/`, and production configuration are runtime artifacts and are not part of the public source.
- User export payloads are generated for direct delivery and should not be committed if saved manually.
- If a Telegram bot token is ever exposed, it must be revoked and regenerated through `@BotFather`.

## Verification

The project includes checks for:

- runtime readiness;
- locale consistency;
- deploy smoke conditions;
- command coverage;
- callback behavior;
- subscription list UX;
- database functions;
- scraper parsing helpers;
- notification flow.

Recent local verification: `191 passed, 3 skipped`.

## Documentation

- [User Guide](docs/guides/USER_GUIDE.md) - user-facing Telegram workflows.
- [Architecture](docs/ARCHITECTURE.md) - runtime, modules, data model, scheduler, callbacks, and technical debt.
- [Docs Index](INDEX.md) - documentation map.

## Usage Rights

The source code is visible, but usage rights are restricted.

- You may read the code and documentation.
- You may not copy, redistribute, sell, host, rebrand, or deploy this bot or a derivative service without explicit written permission from the repository owner.
- Runtime data, bot tokens, user data, logs, backups, and production configuration are not part of this repository and must never be published.

See [LICENSE](LICENSE).
