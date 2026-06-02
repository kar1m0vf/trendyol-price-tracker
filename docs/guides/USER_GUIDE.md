# User Guide

This guide describes the bot from the Telegram user's point of view. It does not explain how to install or self-host the code; the bot is intended to be used as a service inside Telegram.

Open the live bot in Telegram: [@trendyolpw_bot](https://t.me/trendyolpw_bot).

## Summary

The bot tracks Trendyol products. A user sends a product link, the bot saves it to a personal watchlist, checks the price in the background, stores price history, and sends notifications when the price changes or matches a configured alert rule.

## First Interaction

1. The user opens the bot in Telegram.
2. The user sends `/start`.
3. The bot shows a short explanation, the persistent main menu, and quick-action buttons for the first step.
4. The user chooses a language if needed.
5. The user sends a Trendyol product URL or taps `➕ Add product` to see the expected link format.

After a product is added, the bot shows a product card with:

- product title;
- current price;
- notification mode;
- controls for manual refresh, price history, comparison, target price, pause/resume, mode changes, settings, and unsubscribe.

Saved product cards also show the next expected notification/check timing when the user opens the product from the watchlist.

## Personal Watchlist

Command:

```text
/mysubs
```

The bot sends one compact watchlist message instead of separate messages for every product. Each product gets a user-facing number within that user's list:

```text
№ 1  Robot vacuum ...
№ 2  Face moisturizer ...
№ 3  Sneakers ...
```

The same message includes buttons:

```text
№ 1 · Robot vacuum
№ 2 · Face moisturizer
№ 3 · Sneakers
```

Tapping a product button opens the selected product card in the same message. Internal database IDs are not shown to regular users.

The service can enforce a configurable product limit for regular users. If the
limit is reached, the user is asked to remove an older product from `/mysubs`
before adding a new one.

## Product Numbers In Commands

Commands that target a specific product use the number from `/mysubs`:

```text
/history 1
/stats 1
/compare 1
/price_alert 1 2500
/unsubscribe 1
```

If a product is displayed as `№ 1`, the user enters `1`. This is easier than exposing internal database IDs such as `120`.
Price notifications use the same product numbers, and background price checks do not renumber the watchlist.

## Notification Modes

Each tracked product can use different notification rules:

| Mode | Behavior |
| --- | --- |
| `discount` | Notify when the current price is lower than the previous saved price |
| `hourly` | Send regular updates according to the configured interval |
| Target price | Notify once when the price becomes equal to or lower than the target |
| Min/max range | Notify when the price leaves the configured range |
| Percent threshold | Notify when the price changes by the configured percentage |

Examples:

```text
/setmode 1 discount
/setmode 1 hourly
/price_alert 1 2500
/settings price 1 min:1000 max:3000 percent:10
/settings interval 1 60
```

The same per-product controls are also available through inline buttons:
open `/mysubs`, choose a product, and use `⚙️ Settings` to change mode,
notification interval, and target price without typing command arguments.

Users can also pause a product from its card or settings menu. A paused product
stays in `/mysubs`; history, manual price checks, settings, and deletion still
work, but background price alerts are skipped until the user resumes it.

## Quiet Hours

The user can configure hours when the bot should not send notifications:

```text
/settings quiet 23 7
```

This means the bot should stay quiet from 23:00 to 07:00.

## Price History

Command:

```text
/history 1
```

The bot shows price history for the selected product. Local history is used first. If local data is limited, the bot can use external history helpers where available.

Additional history commands:

```text
/history_export 1 30 csv
/history_export 1 30 json
/history_plot 1 30
```

## Statistics And Price Drops

Commands:

```text
/stats 1
/all_list
/top_drops
```

`/stats` shows current, minimum, maximum, and average price, trend, data range, and number of collected price points.

`/top_drops` shows products with the most visible price drops in the user's own watchlist.

## Price Comparison

There are two comparison flows:

```text
/compare 1
```

Compare a saved product using current price and available history.

```text
/compare https://www.trendyol.com/... https://www.trendyol.com/...
```

Compare two direct product URLs.

## Trends

Trends are available through the main menu button and inline trend menus.

Supported flows:

- overall top products;
- category trends;
- text search.

If an external source is temporarily unavailable, the bot tries to return a fallback response instead of leaving the user without feedback.

External-data actions such as trends, comparison, recommendations, and history
can have a short cooldown. This keeps the bot responsive when users repeat
heavy requests quickly.

## Recommendations

Command:

```text
/recommend
```

The bot analyzes the user's tracked products and generates recommendations. Recommendations can come from:

- products similar to the user's interests;
- an admin-managed recommendation catalog;
- priorities, categories, brands, and custom recommendation copy configured by the owner.

## Export

Commands:

```text
/export csv
/export json
```

The bot exports the user's subscriptions as CSV or JSON documents and sends them directly to the user. The normal export flow does not create persistent export files in the runtime artifact directories.

## Import

Command:

```text
/import
```

The bot can restore subscriptions from CSV or JSON files created by `/export`.
Users can run `/import` and then attach the file, or send the file with `/import`
in the document caption. Existing tracked products are skipped as duplicates;
valid new Trendyol product rows are added with their saved mode, alert settings,
interval, pause state, last known price, title, image, and tags where present.
If the service product limit is reached during import, the bot adds the first
valid new products in file order until the remaining slots are filled. Later
valid new rows are reported as skipped by the product limit.

## User Reports

Command:

```text
/report
```

After this command, the user can write a message. The bot forwards the report to admins.

## Terms, Privacy, And Data Deletion

Commands:

```text
/terms
/privacy
/support
/delete_me
```

`/terms` explains that the bot is an independent Trendyol price-tracking assistant, not an official Trendyol service, and that users should check the final price on Trendyol before buying.

`/privacy` summarizes the data needed for price tracking: Telegram user id, public Telegram profile fields, language, saved product links, alert settings, and local price history for the user's subscriptions. The bot does not ask for Trendyol account passwords, payment card details, addresses, or private Trendyol account data.

`/support` points users to `/report` and reminds them not to send sensitive personal data.

`/delete_me` asks for explicit confirmation. After `/delete_me confirm`, the bot deletes the user's bot profile, saved products, notification settings, and related local price history.

## Language

Command:

```text
/language
```

Supported languages:

- Russian;
- English;
- Azerbaijani;
- Turkish.

## UX Principles

- A watchlist is shown as one compact message, not as a stream of separate product cards.
- Product buttons open the requested product immediately.
- Users see friendly product numbers, not database IDs.
- Long-running actions provide clear feedback such as checking, searching, completed, or failed.
- Errors are phrased as user-facing situations instead of technical tracebacks.
