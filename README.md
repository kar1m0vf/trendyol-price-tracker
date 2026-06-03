# Price Tracker for Trendyol

<p align="center">
  <img src="assets/brand/logo.png" alt="Price Tracker for Trendyol logo" width="260">
</p>

An independent Telegram service by Faini Tech for tracking Trendyol product prices, managing personal watchlists, storing price history, and sending practical price-change notifications.

Live bot: [@trendyolpw_bot](https://t.me/trendyolpw_bot)
The project is built as a real service rather than a one-off script: it has Telegram workflows, persistent user state, background jobs, admin controls, localization, diagnostics, and tests. The source is visible for portfolio review, but the bot is not distributed as a reusable package or a ready-made third-party deployment. The production Trendyol scraper and owner environment template are private runtime assets and are not part of the public repository.

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
- Guide first-time users with a short `/start` explanation and quick-action buttons.
- Track each user's own watchlist.
- Show user-facing product numbers like `№ 1`, `№ 2`, `№ 3` instead of internal database IDs.
- Support discount-only mode, hourly mode, target price alerts, min/max thresholds, percent-change alerts, custom notification intervals, and quiet hours.
- Let users change per-product mode, interval, and target price through inline settings buttons.
- Let users pause and resume per-product alerts without deleting the product or losing history.
- Group multiple price updates into one notification when needed.
- Support internal free/premium access tiers with different product limits.

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
- Broken subscription diagnostics with recheck, pause, and delete actions.
- Internal premium access management through admin commands.
- Runtime health check.

### Localization

- RU, EN, AZ, and TR locale files.
- Locale consistency check through `check_locales.py`.

## Technical Highlights

| Area | Implementation |
| --- | --- |
| Telegram runtime | aiogram 3 router/dispatcher stack with package-based handlers |
| UX state | Inline callbacks, reply keyboards, in-place product cards, user-facing numbering |
| Persistence | SQLite schema, migrations, indexes, price history, recommendations, custom texts, access tiers |
| Scheduler | APScheduler jobs for price checks and daily backups |
| Concurrency | Scheduler lock, task batching, network fetch semaphore, grouped notifications |
| Notifications | Safe send helpers, image fallback, grouped updates, chart delivery |
| Scraping | Private Trendyol data extraction module used by the owner runtime |
| Admin tools | Stats, users, broadcasts, reports, cleanup, backups, recommendations, premium access, broken subscription diagnostics |
| Quality | Owner-runtime pytest suite, readiness check, deploy smoke check, public locale key validation |
| Security posture | `.env` configuration, ignored runtime data, token validation, no production data in repo |

Detailed system notes are in [Architecture](docs/ARCHITECTURE.md).

## Command Surface

| Command | Purpose |
| --- | --- |
| `/start` | First launch and main menu |
| `/help` | User help |
| `/mysubs` | Personal tracked products |
| `/unsubscribe 1` | Remove product `№ 1` from the watchlist |
| `/history 1` | Price history for product `№ 1` |
| `/history_export 1 30 csv` | Export recent price history |
| `/history_plot 1 30` | Generate a price history chart |
| `/stats 1` | Price statistics |
| `/all_list` | Compact table of tracked products |
| `/top_drops` | Products with the largest visible price drops |
| `/compare 1` | Compare a saved product |
| `/compare <url1> <url2>` | Compare two product URLs |
| `/setmode 1 discount` | Change notification mode |
| `/price_alert 1 2500` | Notify when product `№ 1` reaches 2500 TL or lower |
| `/settings quiet 23 7` | Configure quiet hours |
| `/settings interval 1 60` | Configure a product notification interval |
| `/settings price 1 min:1000 max:3000 percent:10` | Configure min/max and percent thresholds |
| `/alerts` | Manage target prices |
| `/recommend` | Recommendations |
| `/export csv` | Export user subscriptions |
| `/import` | Import subscriptions from CSV/JSON export |
| `/report` | Send a report to admins |
| `/about` | Bot information |
| `/terms` | Terms of use and service disclaimer |
| `/privacy` | Stored data and privacy summary |
| `/support` | Support and safe report instructions |
| `/delete_me` | Delete the user's bot profile, subscriptions, and local price history |
| `/ping` or `ping` | Response check |
| `/health` | Admin-only health check |
| `/runcheck` | Admin manual price check run |
| `/admin` | Admin panel |
| `/admin premium ...` | Admin-managed free/premium access |
| `/bad_subs` | Admin diagnostics for subscriptions with failed price checks |

Product numbers come from `/mysubs` and keep the same stable order in price notifications.
Internal database IDs are intentionally hidden from regular users.

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
    +--> handlers/trending_handler.py
    +--> handlers/callback_handler.py
    +--> handlers/admin_handler.py
    |
    v
bot.py runtime helpers
    |
    +--> database.py
    +--> private Trendyol scraper module
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
- Private Trendyol scraper module - owner runtime dependency for product extraction, trends, and history helpers. The implementation is not distributed in the public portfolio source.
- `services/notification_service.py` - notifications and charts.
- `locales/` - translation files.
- `tools/diagnostics/deploy_smoke_check.py` - deploy smoke validation.
- `tests/` - behavioral and unit tests.

## Data And Security

- `.env` is private and ignored by git.
- `.env.example` is also private in the portfolio repository because the public source is not intended as a self-hosting package.
- `BOT_TOKEN` must only live in environment variables or `.env`.
- The production Trendyol scraper is not part of the public source.
- `trendyol_bot.db`, `logs/`, `backups/`, and production configuration are runtime artifacts and are not part of the public source.
- User export payloads are generated for direct delivery and should not be committed if saved manually.
- Users can request deletion of their bot profile, subscriptions, and related local price history through `/delete_me`.
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

Latest recorded owner-runtime verification: `252 passed, 3 skipped`. The public portfolio source does not include every private runtime asset required to run the production bot.

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
