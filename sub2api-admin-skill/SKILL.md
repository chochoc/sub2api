---
name: sub2api-admin
description: Manage and diagnose Sub2API deployments through the admin API and SSH, especially 502/503 error logs, account-level failures, upstream/proxy attribution, health checks, and safe log cleanup. Also use for existing account, proxy, group, redeem-code, and admin API operations.
---

# Sub2API Admin

Use the bundled Python operations CLI for diagnostics and the existing Node.js CLI for legacy account/redeem-code CRUD. Run examples from this skill directory. The skill does not check or pin a Python version; replace `python` with `python3` when that is the available interpreter.

```bash
export SUB2API_BASE_URL='https://your-sub2api-host'
export SUB2API_ADMIN_TOKEN='<replaceable admin access token>'
export SUB2API_AUTH_MODE='auto'  # admin-... key => api-key; JWT => bearer
export SUB2API_SSH_SCRIPT='/Users/james/sub2api_gcp.sh'
python scripts/sub2api_admin.py ops-report --since 24h --format markdown
```

For persistent desktop and CLI use, store non-secret settings in `$CODEX_HOME/sub2api-admin/config.json` (default `~/.codex/sub2api-admin/config.json`):

```json
{
  "base_url": "https://your-sub2api-host",
  "auth_mode": "auto",
  "keychain_service": "sub2api-admin",
  "keychain_account": "https://your-sub2api-host"
}
```

Store the token itself in the native OS keychain under the configured service and account. Explicit command-line arguments and environment variables take precedence over this file; the token is never read from the config file.

For error semantics and report interpretation, read [references/ops-analysis.md](references/ops-analysis.md). For the existing CRUD command surface, read [references/admin-cli.md](references/admin-cli.md).
The implementation scope, endpoint contract, safety rules, and verification limits are recorded in [SUB2API_ADMIN_SKILL_IMPLEMENTATION.md](../docs/SUB2API_ADMIN_SKILL_IMPLEMENTATION.md) when this skill is used from the repository.

## Workflow

1. Reuse `base_url` and auth settings from `$CODEX_HOME/sub2api-admin/config.json`, with environment variables and command-line arguments taking precedence. Read credentials from the native OS keychain; set `SUB2API_KEYCHAIN_SERVICE` and `SUB2API_KEYCHAIN_ACCOUNT` to select the keychain item. `SUB2API_JWT` and `SUB2API_ADMIN_API_KEY` remain compatible aliases.
2. Run read-only diagnostics first and preserve the time window in the report.
3. Correlate `/ops/errors`, `/ops/request-errors`, `/ops/upstream-errors`, account stats, and SSH health before assigning a root cause.
4. Before Python write or cleanup operations, print the target IDs and require explicit `--confirm`; never restart or upgrade the live service automatically.
5. Re-run a read-only query after a write and report what changed.

## Common Commands

```bash
python scripts/sub2api_admin.py health
python scripts/sub2api_admin.py ops-report --since 24h --format markdown
python scripts/sub2api_admin.py account-report --ids 27,32,33 --since 24h
python scripts/sub2api_admin.py errors list --status-codes 502,503
python scripts/sub2api_admin.py errors analyze --account-id 32 --since 24h
python scripts/sub2api_admin.py errors get --id 123
python scripts/sub2api_admin.py errors request-upstream --id 123
python scripts/sub2api_admin.py dashboard snapshot --since 6h
python scripts/sub2api_admin.py system-logs list --since 1h --level error
python scripts/sub2api_admin.py errors resolve --id 123 --resolved true --confirm
python scripts/sub2api_admin.py system-logs cleanup --filter-file filters.json --confirm

# Existing CRUD surface
python scripts/sub2api_admin.py users list --status active --sort-by last_used_at --sort-order desc
python scripts/sub2api_admin.py users usage --user-id 123
python scripts/sub2api_admin.py usage top-keys --limit 5 --metric actual_cost
python scripts/sub2api_admin.py accounts load --platform openai
python scripts/sub2api_admin.py keys list --user-id 123
python scripts/sub2api_admin.py keys create --user-id 123 --json '{"name":"automation","quota":10,"group_id":2}' --confirm
python scripts/sub2api_admin.py scheduled-tests list --account-id 40
python scripts/sub2api_admin.py backup-schedule get
python scripts/sub2api_admin.py scheduler-settings get
node scripts/sub2api-admin.js accounts list --page-size 20
node scripts/sub2api-admin.js accounts get 40
node scripts/sub2api-admin.js accounts usage 40
node scripts/sub2api-admin.js accounts set-schedulable 40 true
node scripts/sub2api-admin.js accounts bulk-update --ids 40,39 --json '{"concurrency":10}'
node scripts/sub2api-admin.js redeem-codes list --page-size 20
node scripts/sub2api-admin.js redeem-codes generate --json '{"count":1,"type":"balance","value":10}' --idempotency-key redeem-$(date +%s)
node scripts/sub2api-admin.js redeem-codes create-and-redeem --json '{"code":"order_123","type":"balance","value":10,"user_id":123}' --idempotency-key order-123
node scripts/sub2api-admin.js error-rules list
node scripts/sub2api-admin.js tls-profiles list
```

## Safety Notes

- Node authentication uses `x-api-key` from `SUB2API_ADMIN_API_KEY` first, then falls back to `Authorization: Bearer <jwt>` from `SUB2API_JWT`; Python authentication and its aliases are described below.
- The Python CLI prefers replaceable `SUB2API_ADMIN_TOKEN`, then `SUB2API_JWT`, then the legacy API-key variable. In auto mode, a token beginning with `admin-` is sent as `x-api-key`; set `SUB2API_AUTH_MODE=bearer` or `api-key` to override. When no explicit token is set, the Python CLI reads the native macOS Keychain (`security`) or Linux Secret Service (`secret-tool`) and never writes the credential to disk.
- If the API returns `INVALID_ADMIN_KEY`, ask the user to regenerate the admin API key. If using JWT, log in as an admin user and copy the `access_token` from `POST /api/v1/auth/login`.
- `accounts export` includes credentials and tokens. Prefer `--file` and avoid printing exports in chat.
- The Python CLI redacts Authorization, API keys, OAuth credentials, proxy credentials, cookies, and token-like values in output and errors.
- SSH checks are allowlisted and read-only. The helper at `SUB2API_SSH_SCRIPT` is used only for service, database, Redis, port, and journal inspection.
- Python `errors resolve`, `system-logs cleanup`, and mutating `api` calls require `--confirm`; inspect first and verify afterward. Check targets before using the legacy Node CRUD writes.
- Redeem code create/redeem commands should use `--idempotency-key` for payment or recharge workflows.
- For uncertain or newly added backend APIs, use `api <METHOD> <admin-path>` after a read-only check.
