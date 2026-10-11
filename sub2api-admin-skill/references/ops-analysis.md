# Sub2API Ops Analysis

The Python CLI uses the versioned admin Ops routes already present in Sub2API. It does not assume that every 502/503 has the same cause.

## Data sources

- `GET /api/v1/admin/ops/errors`: indexed error records, with `phase`, `error_source`, `error_owner`, `status_code`, `account_id`, `request_id`, and optional upstream context.
- `GET /api/v1/admin/ops/request-errors`: client-visible failures.
- `GET /api/v1/admin/ops/upstream-errors`: independent upstream failures and account/proxy attribution when available.
- `GET /api/v1/admin/ops/system-logs`: indexed service logs.
- `GET /api/v1/admin/ops/dashboard/*`: windowed aggregates and trends.
- SSH helper: read-only `systemctl`, `journalctl`, `pg_isready`, `redis-cli ping`, and `ss -ltn` checks.

All timestamps supplied by the CLI are UTC RFC3339 values. The report records the query window so a 6-hour result is not confused with a 24-hour result.

## Interpreting 502 and 503

| Signal | Interpretation | Next check |
|---|---|---|
| 502 with `source=upstream_http` or `phase=upstream` | upstream gateway, proxy, TLS, or transport failure | upstream status/message, proxy, request ID, and neighboring attempts |
| 503 with upstream context | upstream unavailable, overloaded, rate-limited, or temporarily unhealthy | upstream health, concurrency, retry bursts, and proxy distribution |
| 502/503 with `phase=routing` or `phase=internal` | local Sub2API routing or service path may have failed | service health, journal, DB/Redis, and dashboard error trend |
| 502/503 with `phase=account_auth` | account credentials, quota, or provider authorization | account state, temporary unschedulable state, and single-account test |
| status code without phase/source/upstream context | insufficient evidence | query request/upstream detail before changing account or proxy state |

The CLI reports a probable cause and confidence. A status code by itself is never treated as proof that an account or proxy is bad.

## Safe workflow

1. Run `health` and record whether the service, DB, Redis, and listening port are healthy.
2. Run `ops-report --since 6h` and `ops-report --since 24h` to separate current incidents from historical noise.
3. Run `account-report --ids ...` and compare error concentration by account and proxy.
4. Drill into `request_id` or error ID with the existing raw admin CLI if the API version exposes a field not yet wrapped.
5. Only after evidence is clear, use `errors resolve --confirm` or `system-logs cleanup --confirm`.

The tool intentionally does not provide automatic restart, upgrade, rollback, account deletion, or credential replacement commands.
