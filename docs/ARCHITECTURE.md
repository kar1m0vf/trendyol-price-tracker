# Architecture

This document describes the system design behind the bot. It is not a deployment license and does not grant permission to operate a copy of the service.

## System Purpose

The project is designed as a Telegram service. Users interact with the live bot in Telegram: they send product links, manage subscriptions, receive alerts, and view price history. The repository demonstrates how the service is implemented.

## High-Level Flow

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
    +--> handlers/payment_handler.py
    +--> handlers/admin_handler.py
    |
    v
runtime helpers in bot.py
    |
    +--> database.py
    +--> private Trendyol scraper module
    +--> services/notification_service.py
    +--> services/payment_service.py
    +--> localization.py / locales/
    |
    v
SQLite + Telegram API + Trendyol
```

## Runtime Entry Point

`bot.py` is the owner runtime entry point. It is responsible for:

- creating the aiogram `Bot` and `Dispatcher`;
- registering the package-based handler stack;
- setting the Telegram command menu;
- clearing webhook state before polling;
- starting polling;
- starting APScheduler jobs;
- shutting down the scheduler, database connections, and HTTP session cleanly.

Some command helpers still live in `bot.py` while the handler package migration continues. New and migrated flows are registered through `handlers/`; remaining legacy routes are kept only where they still own current behavior.

## Handler Layers

| Module | Responsibility |
| --- | --- |
| `handlers/basic.py` | `/start`, `/help`, `/language`, `/terms`, `/privacy`, `/support`, `/delete_me`, language/help buttons |
| `handlers/subscription_handler.py` | `/mysubs`, `/unsubscribe`, watchlist buttons, Trendyol URL handling |
| `handlers/analytics_handler.py` | `/stats`, `/all_list`, `/top_drops` |
| `handlers/trending_handler.py` | Trend menu entry point and trend search text input |
| `handlers/callback_handler.py` | Inline product controls, history, compare, alerts, trends, admin callbacks |
| `handlers/payment_handler.py` | Telegram Stars pre-checkout validation and successful payment application |
| `handlers/admin_handler.py` | Admin menu, stats, users, broadcast, reports, cleanup, backups, recommendations, broken subscription diagnostics |

## Database Layer

`database.py` uses SQLite and owns:

- connection helpers;
- schema initialization;
- lightweight migrations;
- subscriptions;
- users, language preferences, internal access tiers, and user-owned data deletion;
- price history;
- recommendations;
- custom bot texts;
- payment events for Telegram Stars premium and donation flows;
- direct CSV/JSON export payloads;
- SQLite backup API usage.

Main tables:

| Table | Purpose |
| --- | --- |
| `users` | Telegram user ID, language, quiet hours, internal access tier, premium expiry, created timestamp |
| `subscriptions` | Product URL, title, image, mode, pause state, price settings, notification state |
| `price_history` | Price time series for tracked products |
| `recommended_products` | Admin-managed recommendation catalog |
| `bot_texts` | Custom copy controlled by admin flows |
| `payment_events` | Internal ledger for pending/paid/failed/refunded premium or donation payment events |

Indexes are focused on common runtime queries: subscriptions by user, price history by subscription/time, price history by URL/time, and notification scheduling.

## Payment And Premium Layer

`services/payment_service.py` defines the internal payment model. `handlers/callback_handler.py` creates Telegram Stars invoices when owner runtime payments are enabled, and `handlers/payment_handler.py` validates Telegram pre-checkout queries and applies confirmed payments.

Current responsibilities:

- keep premium and donation plan definitions in one place;
- create pending payment events before an invoice is sent;
- mark payment events as paid, failed, or refunded through database helpers;
- apply a successful premium payment exactly once;
- extend an active premium period from the current expiry date instead of overwriting remaining paid time;
- keep donation payment events separate from premium access grants.

Telegram Stars payments use `XTR` invoice currency and an internal payload that points to the payment event. Admin-granted premium remains available through `handlers/admin_handler.py` and uses the same internal access tier fields.

## Scraper Layer

The private Trendyol scraper module is responsible for external product data in the owner runtime:

- current price;
- product title;
- product image;
- Trendyol trends;
- category/search trend flows;
- external price history helpers where available.

It is called by subscription creation, scheduled price checks, history flows, comparison, and trending flows. The implementation is not distributed in the public portfolio source.

## Notification Layer

`services/notification_service.py` and helpers in `bot.py` handle:

- safe message sending;
- photo fallback when image delivery fails;
- grouped notifications to reduce spam;
- chart generation and delivery;
- user-facing progress/error messages.

## Scheduler

The runtime uses `AsyncIOScheduler`.

| Job | Purpose |
| --- | --- |
| `check_all_interval` | Check active subscriptions and notify users |
| `db_backup_daily` | Create a daily SQLite backup |
| `premium_expiry_cleanup_daily` | Warn expired premium users above the Free limit and clean up after the grace period |

The price checker uses:

- a global lock to avoid overlapping runs;
- batched database iteration;
- task batching;
- network concurrency limits;
- a shared `ProductSnapshot` model for progressively richer product data;
- an in-memory product cache that coalesces simultaneous requests for the same URL;
- fetch/cache/coalescing counters exposed in the latest runtime health summary;
- grouped notifications;
- batch price-history writes with fallback.

## User-Facing Product Numbers

Internal subscription IDs are global database IDs. They are not shown to regular users.

The user sees local list numbers:

```text
№ 1
№ 2
№ 3
```

Commands such as `/history 1`, `/compare 1`, and `/unsubscribe 1` resolve the visible list number to the internal subscription ID. Callback data still uses the internal ID because it is stable and safe for internal routing.

## Localization

Localization lives in:

```text
locales/ru.json
locales/en.json
locales/az.json
locales/tr.json
```

Consistency is checked with:

```powershell
python check_locales.py
```

Every new locale key must be present in all language files.

## Diagnostics

Important checks:

```powershell
python check_bot_ready.py
python tools\diagnostics\deploy_smoke_check.py
python check_locales.py
python -m pytest -q
```

These checks validate runtime readiness, deployment smoke conditions, locale consistency, and behavioral tests.

## Known Technical Debt

The main remaining architectural debt is that `bot.py` still contains too much mixed responsibility. Future refactors should gradually move:

- history and comparison logic into a dedicated service;
- scheduler setup into a runtime module;
- card/list formatting into a presenter layer;
- recommendation generation into a recommendation service;
- scraper fallback strategies into adapters.

This is not blocking the current bot, but it is the correct direction for long-term maintainability.
