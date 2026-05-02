# Deploy Smoke Checklist

Owner/internal checklist. This document does not grant permission to deploy a
copy of the bot; it exists so the project owner can validate the live service.

Run this before and right after deployment.

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

## 3. Telegram Basic Commands

In Telegram:
1. Send `/start`
2. Send `/help`
3. Send `/settings`
4. Send `/language`

Expected:
- bot replies without timeout/errors;
- UI buttons are visible;
- language changes are applied.

## 4. Subscription Flow

In Telegram:
1. Send `/subscribe <trendyol_product_url>`
2. Verify it appears in `/mysubs`
3. Send `/history`
4. Send `/unsubscribe`

Expected:
- subscription is created, visible, and removable;
- history/export commands do not fail.

## 5. Scheduler and Notifications

Check:
1. Scheduler job `check_all` runs on interval.
2. No overlapping run warnings in normal mode.
3. No repeated tracebacks for network/parser failures.

Expected:
- periodic checks continue;
- bot remains responsive to commands.

## 6. Backup and DB Health

Check:
1. `backups/` contains fresh DB backups.
2. DB file is writable.
3. Log does not show SQLite lock storms.

Expected:
- backups are created and rotated;
- DB remains healthy under bot load.

## 7. Security Final Pass

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
