# Deploy Smoke Checklist

Owner/internal checklist. This document does not grant permission to operate a
copy of the bot; it exists so the project owner can validate the live service.

Run this before and right after owner-controlled runtime changes.

## 1. Pre-Deploy Local Checks

```bash
python check_bot_ready.py
python tools/diagnostics/deploy_smoke_check.py
python -m pytest -q
```

Expected:
- all checks pass;
- no token-like secrets are found in docs;
- tests are green.

## 2. Start Bot in Target Environment

```bash
python bot.py
```

Expected startup signals in logs:
- database initialized;
- handlers registered;
- scheduler started.

If `ADMIN_RUNTIME_ALERTS=1`, the configured admins should also receive a
Telegram startup alert.

## 3. Telegram Basic Commands

In Telegram:
1. Send `/start`
2. Send `/help`
3. Send `/settings`
4. Send `/language`
5. As admin, send `/health`
6. As admin, send `/bad_subs`

Expected:
- bot replies without timeout/errors;
- UI buttons are visible;
- language changes are applied.
- `/health` shows database, scheduler, latest price-check, next price-check,
  and backup path information.
- `/bad_subs` opens the broken-subscription diagnostics list or a clear empty
  state.

## 4. Subscription And Export Flow

In Telegram:
1. Send a Trendyol product URL directly
2. Verify it appears in `/mysubs`
3. Send `/history 1`
4. Send `/history_export 1 30 csv`
5. Send `/history_plot 1 30`
6. Send `/export csv`
7. Send `/import` and attach the exported CSV file
8. Send `/unsubscribe 1`

Expected:
- subscription is created, visible, and removable;
- history, chart, export, and import commands do not fail;
- export commands deliver Telegram documents directly;
- import skips duplicates and reports the result clearly.

## 5. Discovery Flow

In Telegram:
1. Open the trends menu from the main keyboard.
2. Run an overall trends request.
3. Run a trend search query.
4. Send `/recommend`.

Expected:
- trend results or a clear fallback message are shown;
- recommendations either show relevant products or a clear no-data message.

## 6. Scheduler and Notifications

Check:
1. Scheduler job `check_all` runs on interval.
2. No overlapping run warnings in normal mode.
3. No repeated tracebacks for network/parser failures.

Expected:
- periodic checks continue;
- bot remains responsive to commands.

## 7. Backup and DB Health

Check:
1. `BACKUP_DIR` contains fresh DB backups.
2. DB file is writable.
3. Log does not show SQLite lock storms.

Expected:
- backups are created and rotated;
- DB remains healthy under bot load.

## 8. Security Final Pass

Run:

```bash
git grep -nI -E "\b[0-9]{8,10}:[A-Za-z0-9_-]{35}\b" -- . ":(exclude).env" ":(exclude).env.*"
```

Expected:
- no matches.

If any match appears:
1. remove secret from files;
2. rotate/revoke affected secret;
3. if committed, rewrite history and force-push.
