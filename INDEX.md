# Project Documentation Index

This repository contains the source code and documentation for the Trendyol Price Tracker Bot. It is not a public self-hosting package.

## Main Documentation

| Document | Audience | Purpose |
| --- | --- | --- |
| [README.md](README.md) | General | Product overview, capabilities, ownership policy |
| [User Guide](docs/guides/USER_GUIDE.md) | Product | Telegram user experience and workflows |
| [Architecture](docs/ARCHITECTURE.md) | Engineering | Runtime, modules, data model, scheduler, callbacks |
| Owner Operations Runbook | Operations | Private runtime notes, kept outside the public source tree |

## Diagnostics

| File | Purpose |
| --- | --- |
| [check_bot_ready.py](check_bot_ready.py) | Owner-runtime readiness check |
| [deploy_smoke_check.py](tools/diagnostics/deploy_smoke_check.py) | Owner-runtime deploy smoke check |
| [check_locales.py](check_locales.py) | Localization key consistency |
| [Deploy Smoke Checklist](docs/guides/DEPLOY_SMOKE_CHECKLIST.md) | Owner/internal post-deploy checklist |

## Code Map

| Path | Purpose |
| --- | --- |
| [bot.py](bot.py) | Entry point, runtime, scheduler, common helpers |
| [handlers/](handlers) | aiogram handler package |
| [database.py](database.py) | SQLite schema, migrations, subscriptions, history, recommendations |
| Private scraper module | Trendyol data collection and parsing, not distributed in the public portfolio source |
| [services/notification_service.py](services/notification_service.py) | Notifications and chart delivery |
| [locales/](locales) | RU/EN/AZ/TR localization |
| [tests/](tests) | pytest test suite |

## Documentation Policy

The repository intentionally keeps a compact documentation set:

- product overview;
- user-facing Telegram workflow;
- architecture;
- owner-only operations;
- deploy smoke checklist.

Old reports, fix logs, duplicate quick starts, and local run notes were removed to avoid presenting the project as a public self-hosting template.
