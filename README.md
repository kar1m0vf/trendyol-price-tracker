# Trendyol Price Tracker Bot

Portfolio/source-available repository for a production-oriented Telegram bot that tracks Trendyol prices, manages user subscriptions, stores price history, sends notifications, and exposes admin tooling.

This repository is published to demonstrate the system design, implementation quality, and product thinking behind the bot. It is not an open-source starter template and it is not offered as a ready-made bot for third-party deployment.

## Access And Usage Policy

The source code is visible for review purposes only.

- You may read the code and documentation to evaluate the project.
- You may not copy, redistribute, sell, host, rebrand, or deploy this bot or a derivative service without explicit written permission from the repository owner.
- Runtime data, bot tokens, user data, logs, backups, and production configuration are not part of this repository and must never be published.
- The live bot/service, if offered publicly, is intended to be used through Telegram, not by cloning this repository.

See [LICENSE](LICENSE).

## Product Overview

The bot solves a practical user problem: tracking prices on Trendyol without manually checking product pages. A user sends a product link, the bot saves it, checks prices in the background, keeps history, and sends human-friendly notifications when the price changes or reaches a configured target.

The project is built as a service, not a script:

- Telegram UX with reply keyboards and inline controls.
- Per-user product lists with friendly numbering like `№ 1`, `№ 2`, `№ 3`.
- Background price checks with scheduler locking and batch processing.
- SQLite persistence with migrations, indexes, history tables, and backup support.
- Price alerts, discount mode, hourly mode, min/max thresholds, percent thresholds, custom intervals, and quiet hours.
- Price history, statistics, CSV/JSON exports, and chart generation.
- Trendyol trends, category/search flows, and product comparison.
- Personalized recommendations plus admin-managed recommendation catalog.
- Admin panel for stats, users, broadcasts, reports, cleanup, backups, and recommendation management.
- Localization for RU, EN, AZ, and TR.
- Diagnostics and tests for deployment confidence.

## User Experience

The intended user experience happens inside Telegram:

1. User opens the bot and sends `/start`.
2. User sends a Trendyol product link.
3. Bot extracts the product, price, image, and default tracking mode.
4. User opens "My products" and gets one compact list, not a stream of spam messages.
5. Tapping `№ 1`, `№ 2`, etc. opens the selected product card in-place.
6. User configures history, comparison, target price, mode, or unsubscribe from inline buttons.
7. Background jobs check prices and send grouped notifications when conditions are met.

Read more in [User Guide](docs/guides/USER_GUIDE.md).

## Core Commands

| Command | Purpose |
| --- | --- |
| `/start` | First launch and main menu |
| `/help` | User help |
| `/mysubs` | User's tracked products |
| `/history 1` | Price history for product `№ 1` |
| `/stats 1` | Price statistics |
| `/compare 1` | Compare saved product price |
| `/compare <url1> <url2>` | Compare two product URLs |
| `/price_alert 1 2500` | Notify when product `№ 1` reaches 2500 TL or lower |
| `/settings` | Quiet hours, intervals, thresholds |
| `/alerts` | Manage target prices |
| `/recommend` | Recommendations |
| `/export` | Export user subscriptions |
| `/health` | Admin health-check |
| `/admin` | Admin panel |

Product numbers are user-facing list positions from `/mysubs`. Internal database IDs are intentionally hidden from regular users.

## System Architecture

The main runtime still starts from `bot.py`, while the application logic is split across handler packages and supporting services:

- `bot.py` - runtime factory, polling entry point, scheduler jobs, common helpers, remaining legacy commands.
- `handlers/` - aiogram handlers for basic commands, subscriptions, analytics, callbacks, and admin flows.
- `database.py` - SQLite schema, migrations, subscriptions, price history, recommendations, custom texts, backups.
- `scraper.py` - Trendyol product data, price extraction, trends, search/category flows, external history helpers.
- `services/notification_service.py` - safe notifications and chart delivery.
- `locales/` - RU/EN/AZ/TR translations.
- `tools/diagnostics/` - readiness and deployment smoke checks.
- `tests/` - pytest coverage for handlers, callbacks, database logic, localization, scraper helpers, and notification behavior.

Detailed architecture: [Architecture](docs/ARCHITECTURE.md).

## Repository Documentation

- [User Guide](docs/guides/USER_GUIDE.md) - product behavior from a Telegram user's perspective.
- [Architecture](docs/ARCHITECTURE.md) - modules, data model, scheduler, callbacks, and technical debt.
- [Docs Index](INDEX.md) - documentation map.

## Quality Signals

The project includes checks for:

- localization consistency;
- runtime readiness;
- deploy smoke validation;
- handler registration;
- callback behavior;
- subscription list UX;
- database functions;
- scraper parsing helpers;
- notification flow.

Recent local verification: `118 passed, 3 skipped`.

## Security Notes

- `.env` is private and must not be committed.
- `BOT_TOKEN` must only live in environment variables or `.env`.
- `trendyol_bot.db`, `logs/`, and `backups/` are runtime artifacts and are excluded from public sharing.
- If a Telegram bot token is ever exposed, it must be revoked and regenerated through `@BotFather`.
