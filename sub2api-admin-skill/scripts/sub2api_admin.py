#!/usr/bin/env python
"""Safe Sub2API operations and error-log analysis CLI.

The module intentionally uses only Python's standard library so the whole
skill directory can be copied to another machine without extra packages.
"""

import argparse
import csv
import datetime as dt
import decimal
import http.client
import json
import os
import platform
import re
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


SENSITIVE_KEYS = re.compile(
    r"(authorization|x-api-key|api[_-]?key|token|secret|password|credential|cookie|proxy[_-]?auth)",
    re.I,
)
TOKEN_VALUE = re.compile(r"(?i)(bearer\s+|admin[-_])?[A-Za-z0-9._=-]{24,}")
REDACTED = "[REDACTED]"


def config_file() -> Path:
    """Return the persistent non-secret configuration path."""
    override = os.environ.get("SUB2API_CONFIG_FILE")
    if override:
        return Path(override).expanduser()
    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
    return codex_home / "sub2api-admin" / "config.json"


def load_config() -> Dict[str, Any]:
    """Load non-secret settings; credentials remain in the native keychain."""
    path = config_file()
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AdminError("invalid Sub2API config file: " + str(path)) from exc
    if not isinstance(value, dict):
        raise AdminError("Sub2API config must be a JSON object: " + str(path))
    return value


class AdminError(RuntimeError):
    """A safe, user-facing operation error."""


def keychain_token(base_url: str, config: Optional[Mapping[str, Any]] = None) -> str:
    """Read the admin token from the native OS credential store."""
    config = config or {}
    service = os.environ.get("SUB2API_KEYCHAIN_SERVICE", str(config.get("keychain_service", "sub2api-admin")))
    account = os.environ.get("SUB2API_KEYCHAIN_ACCOUNT", str(config.get("keychain_account", base_url.rstrip("/"))))
    system = platform.system().lower()
    if system == "darwin":
        argv = ["security", "find-generic-password", "-s", service, "-a", account, "-w"]
    elif system == "linux":
        argv = ["secret-tool", "lookup", "service", service, "account", account]
    else:
        raise AdminError("OS keychain is unsupported; set SUB2API_ADMIN_TOKEN explicitly")
    try:
        result = subprocess.run(argv, check=False, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AdminError("unable to read Sub2API admin token from OS keychain") from exc
    token = result.stdout.strip() if result.returncode == 0 else ""
    if not token:
        raise AdminError("no Sub2API admin token found in OS keychain")
    return token


def redact(value: Any, key: str = "") -> Any:
    """Redact credentials and token-like strings recursively."""
    if SENSITIVE_KEYS.search(key or ""):
        return REDACTED
    if isinstance(value, Mapping):
        return {str(k): redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, key) for v in value]
    if isinstance(value, tuple):
        return [redact(v, key) for v in value]
    if isinstance(value, str):
        value = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._=-]{20,}", r"\1" + REDACTED, value)
        return TOKEN_VALUE.sub(REDACTED, value)
    return value


def parse_since(value: str, now: Optional[dt.datetime] = None) -> dt.datetime:
    """Parse 30m, 6h, 24h, 7d or an RFC3339 timestamp into UTC."""
    now = now or dt.datetime.now(dt.timezone.utc)
    raw = str(value).strip()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([mhdw])", raw.lower())
    if match:
        amount = float(match.group(1))
        unit = match.group(2)
        seconds = amount * {"m": 60, "h": 3600, "d": 86400, "w": 604800}[unit]
        return now - dt.timedelta(seconds=seconds)
    candidate = raw.replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise AdminError("since must be a duration such as 24h or an RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def first(data: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return default


def unwrap_data(payload: Any) -> Any:
    if isinstance(payload, Mapping) and "data" in payload:
        return payload["data"]
    return payload


def records_from(payload: Any, keys: Sequence[str]) -> List[Dict[str, Any]]:
    data = unwrap_data(payload)
    if isinstance(data, list):
        return [dict(item) for item in data if isinstance(item, Mapping)]
    if isinstance(data, Mapping):
        for key in keys:
            value = data.get(key)
            if isinstance(value, list):
                return [dict(item) for item in value if isinstance(item, Mapping)]
    return []


def parse_upstream_events(record: Mapping[str, Any]) -> List[Dict[str, Any]]:
    raw = first(record, "upstream_errors", "upstreamErrors", default=[])
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return []
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, Mapping)]


def classify_error(record: Mapping[str, Any]) -> Dict[str, Any]:
    """Classify an error without pretending that a status code proves a cause."""
    status = as_int(first(record, "status_code", "status", default=0))
    phase = str(first(record, "phase", "error_phase", default="") or "").lower()
    source = str(first(record, "error_source", "source", default="") or "").lower()
    owner = str(first(record, "error_owner", "owner", default="") or "").lower()
    upstream_status = as_int(first(record, "upstream_status_code", default=0))
    events = parse_upstream_events(record)
    if not upstream_status:
        for event in reversed(events):
            upstream_status = as_int(first(event, "status_code", "upstream_status_code", default=0))
            if upstream_status:
                break

    if phase in {"upstream", "network"} or source == "upstream_http" or upstream_status in (502, 503):
        category = "upstream_or_proxy"
        if status == 503 or upstream_status == 503:
            cause = "upstream_unavailable_or_overloaded"
        elif status == 502 or upstream_status == 502:
            cause = "upstream_gateway_or_transport"
        else:
            cause = "upstream_failure"
        confidence = "high" if source == "upstream_http" or upstream_status else "medium"
    elif phase in {"routing", "request", "internal"} or owner == "platform":
        category = "local_platform"
        cause = "local_routing_or_service_error"
        confidence = "medium"
    elif phase in {"auth", "account_auth"} or owner == "provider":
        category = "account_or_auth"
        cause = "account_authentication_or_quota"
        confidence = "medium"
    else:
        category = "unknown"
        cause = "insufficient_context"
        confidence = "low"

    return {
        "status_code": status,
        "upstream_status_code": upstream_status or None,
        "category": category,
        "probable_cause": cause,
        "confidence": confidence,
        "phase": phase or None,
        "source": source or None,
        "owner": owner or None,
    }


def aggregate_errors(records: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    rows = [dict(item) for item in records]
    status_counts = Counter()
    category_counts = Counter()
    account_counts = Counter()
    proxy_counts = Counter()
    phase_counts = Counter()
    for row in rows:
        status = as_int(first(row, "status_code", "status", default=0))
        if status:
            status_counts[str(status)] += 1
        classification = classify_error(row)
        category_counts[classification["category"]] += 1
        if classification["phase"]:
            phase_counts[classification["phase"]] += 1
        account = first(row, "account_id", "accountId", default=None)
        if account is not None:
            account_counts[str(account)] += 1
        proxy = first(row, "proxy_id", "proxyId", "proxy_name", default=None)
        for event in parse_upstream_events(row):
            proxy = first(event, "proxy_id", "proxyId", "proxy_name", default=proxy)
        if proxy is not None:
            proxy_counts[str(proxy)] += 1
    return {
        "total_errors": len(rows),
        "status_counts": dict(status_counts),
        "category_counts": dict(category_counts),
        "phase_counts": dict(phase_counts),
        "account_counts": dict(account_counts),
        "proxy_counts": dict(proxy_counts),
    }


def account_error_report(records: Iterable[Mapping[str, Any]], account_ids: Sequence[int]) -> List[Dict[str, Any]]:
    wanted = {str(item) for item in account_ids}
    grouped: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        account = first(record, "account_id", "accountId", default=None)
        if account is not None and (not wanted or str(account) in wanted):
            grouped[str(account)].append(record)
    output = []
    for account in account_ids or sorted(as_int(key) for key in grouped):
        rows = grouped.get(str(account), [])
        statuses = Counter(as_int(first(row, "status_code", "status", default=0)) for row in rows)
        errors_502 = statuses.get(502, 0)
        errors_503 = statuses.get(503, 0)
        output.append({
            "account_id": account,
            "error_count": len(rows),
            "502": errors_502,
            "503": errors_503,
            "other_errors": max(0, len(rows) - errors_502 - errors_503),
            "latest_error": first(rows[0], "created_at", "timestamp", default=None) if rows else None,
            "categories": dict(Counter(classify_error(row)["category"] for row in rows)),
        })
    output.sort(key=lambda row: (-row["error_count"], -row["503"], row["account_id"]))
    return output


def find_metric(value: Any, names: Sequence[str]) -> Optional[int]:
    """Find a common count field in an unknown dashboard/account response."""
    wanted = {name.lower() for name in names}
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).lower() in wanted and isinstance(item, (int, float, str)):
                try:
                    return int(item)
                except (TypeError, ValueError):
                    pass
        for item in value.values():
            result = find_metric(item, names)
            if result is not None:
                return result
    elif isinstance(value, list):
        for item in value:
            result = find_metric(item, names)
            if result is not None:
                return result
    return None


def traffic_metrics(payload: Any, fallback_errors: int) -> Dict[str, Any]:
    total = find_metric(payload, ("total_requests", "total_calls", "request_count", "calls", "total"))
    success = find_metric(payload, ("success_count", "successful_requests", "successes", "success"))
    errors = find_metric(payload, ("error_count", "errors", "failed_requests", "failure_count"))
    if errors is None:
        errors = max(0, total - success) if total is not None and success is not None else fallback_errors
    if total is None and success is not None:
        total = success + errors
    if success is None and total is not None:
        success = max(0, total - errors)
    rate = None
    if total:
        rate = round(float(errors) / float(total), 6)
    return {"total_calls": total, "successful_calls": success, "error_calls": errors, "error_rate": rate}


class AdminClient:
    def __init__(self, base_url: str, token: str, auth_mode: str = "bearer", timeout: float = 15.0, retries: int = 2):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.auth_mode = auth_mode
        self.timeout = timeout
        self.retries = retries
        if not self.base_url:
            raise AdminError("SUB2API_BASE_URL is required")
        if not self.token:
            raise AdminError("SUB2API_ADMIN_TOKEN, SUB2API_JWT, or SUB2API_ADMIN_API_KEY is required")

    def _headers(self) -> Dict[str, str]:
        if self.auth_mode == "api-key":
            return {"x-api-key": self.token, "Accept": "application/json"}
        return {"Authorization": "Bearer " + self.token, "Accept": "application/json"}

    def request(self, method: str, path: str, body: Optional[Any] = None, params: Optional[Mapping[str, Any]] = None, extra_headers: Optional[Mapping[str, str]] = None) -> Any:
        method = method.upper()
        retryable = method in {"GET", "HEAD", "OPTIONS"}
        url = self.base_url + (path if path.startswith("/") else "/" + path)
        query = [(key, str(value)) for key, value in (params or {}).items() if value is not None and value != ""]
        if query:
            url += "?" + urllib.parse.urlencode(query)
        headers = self._headers()
        headers.update(extra_headers or {})
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")
        last_error: Optional[Exception] = None
        for attempt in range(self.retries + 1):
            try:
                request = urllib.request.Request(url, data=data, headers=headers, method=method)
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = response.read().decode("utf-8", errors="replace")
                    if not raw:
                        return None
                    try:
                        payload = json.loads(raw)
                    except json.JSONDecodeError:
                        return {"raw": raw}
                    # Sub2API wraps both success and error responses in a JSON
                    # envelope.  A few reverse proxies preserve HTTP 200 for
                    # an application error, so do not treat a non-zero code as
                    # a successful operation.
                    if isinstance(payload, Mapping):
                        code = payload.get("code")
                        if code not in (None, 0, "0"):
                            detail = payload.get("message") or payload.get("reason") or code
                            raise AdminError("%s %s failed: %s" % (response.status, method, json.dumps(redact(detail), ensure_ascii=False)))
                    return payload
            except urllib.error.HTTPError as exc:
                raw = exc.read().decode("utf-8", errors="replace")
                detail: Any = raw
                try:
                    detail = json.loads(raw)
                except json.JSONDecodeError:
                    pass
                if retryable and exc.code in (408, 429, 500, 502, 503, 504) and attempt < self.retries:
                    time.sleep(0.25 * (attempt + 1))
                    continue
                raise AdminError("HTTP %s %s failed: %s" % (exc.code, method.upper(), json.dumps(redact(detail), ensure_ascii=False))) from exc
            except (urllib.error.URLError, TimeoutError, http.client.HTTPException) as exc:
                last_error = exc
                if retryable and attempt < self.retries:
                    time.sleep(0.25 * (attempt + 1))
                    continue
                break
        raise AdminError("request failed: " + str(last_error))

    def list_errors(self, since: dt.datetime, until: Optional[dt.datetime] = None, account_id: Optional[int] = None,
                    status_codes: Optional[Sequence[int]] = None, endpoint: str = "/api/v1/admin/ops/errors") -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        page = 1
        while True:
            payload = self.request("GET", endpoint, params={
                "page": page,
                "page_size": 500,
                "start_time": since.isoformat(),
                "end_time": until.isoformat() if until else None,
                "account_id": account_id,
                "status_codes": ",".join(str(item) for item in status_codes) if status_codes else None,
                "sort_by": "created_at",
                "sort_order": "desc",
                "view": "all",
            })
            page_rows = records_from(payload, ("errors", "items", "logs"))
            rows.extend(page_rows)
            data = unwrap_data(payload)
            total = as_int(data.get("total"), 0) if isinstance(data, Mapping) else 0
            if not page_rows or len(rows) >= total or len(page_rows) < 500:
                break
            page += 1
        return rows

    def collect_error_records(self, since: dt.datetime, until: Optional[dt.datetime] = None,
                              account_id: Optional[int] = None, status_codes: Optional[Sequence[int]] = None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Collect the three compatible Ops views and de-duplicate by error ID."""
        endpoints = (
            "/api/v1/admin/ops/errors",
            "/api/v1/admin/ops/request-errors",
            "/api/v1/admin/ops/upstream-errors",
        )
        merged: Dict[str, Dict[str, Any]] = {}
        source_counts: Dict[str, int] = {}
        source_errors: Dict[str, str] = {}
        for endpoint in endpoints:
            try:
                rows = self.list_errors(since, until, account_id, status_codes, endpoint)
            except AdminError as exc:
                rows = []
                source_errors[endpoint] = redact(str(exc))
            source_counts[endpoint] = len(rows)
            for row in rows:
                key = str(row.get("id")) if row.get("id") is not None else json.dumps(row, sort_keys=True, default=str)
                merged[key] = row
        if not merged and len(source_errors) == len(endpoints):
            details = "; ".join("%s: %s" % (key.rsplit("/", 1)[-1], value) for key, value in source_errors.items())
            raise AdminError("all error-log endpoints failed: " + details)
        if source_errors:
            source_counts["_errors"] = source_errors
        return list(merged.values()), source_counts

    def error_detail(self, error_id: int, endpoint: str = "/api/v1/admin/ops/errors") -> Any:
        return self.request("GET", "%s/%s" % (endpoint.rstrip("/"), error_id))

    def request_error_upstream(self, error_id: int, params: Optional[Mapping[str, Any]] = None) -> Any:
        return self.request("GET", "/api/v1/admin/ops/request-errors/%s/upstream-errors" % error_id, params=params)


def payload_data(payload: Any) -> Any:
    """Unwrap the standard Sub2API response envelope."""
    if isinstance(payload, Mapping) and "data" in payload:
        return payload["data"]
    return payload


def page_items(payload: Any) -> Tuple[List[Dict[str, Any]], Optional[int]]:
    value = payload_data(payload)
    if isinstance(value, list):
        return [dict(row) for row in value if isinstance(row, Mapping)], None
    if not isinstance(value, Mapping):
        return [], None
    items = value.get("items", value.get("data", []))
    rows = [dict(row) for row in items if isinstance(row, Mapping)] if isinstance(items, list) else []
    total = value.get("total")
    return rows, int(total) if isinstance(total, (int, float)) else None


def fetch_all_pages(client: AdminClient, path: str, params: Mapping[str, Any], max_pages: int = 1000) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    page = 1
    last_signature = None
    while page <= max_pages:
        query = dict(params)
        query.update({"page": page, "page_size": query.get("page_size", 500)})
        items, total = page_items(client.request("GET", path, params=query))
        signature = tuple(str(item.get("id", "")) for item in items)
        if signature and signature == last_signature:
            raise AdminError("pagination repeated the same page; refusing incomplete result")
        last_signature = signature
        rows.extend(items)
        if not items or (total is not None and len(rows) >= total) or len(items) < int(query["page_size"]):
            return rows
        page += 1
    raise AdminError("pagination exceeded --max-pages; result is incomplete")


def parse_date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise AdminError("date must use YYYY-MM-DD") from exc


def today_range(timezone_name: str) -> Tuple[str, str]:
    try:
        from zoneinfo import ZoneInfo
        today = dt.datetime.now(ZoneInfo(timezone_name)).date()
    except Exception as exc:
        raise AdminError("invalid timezone: " + timezone_name) from exc
    return today.isoformat(), (today + dt.timedelta(days=1)).isoformat()


def admin_request(client: AdminClient, method: str, path: str, body: Any = None, params: Optional[Mapping[str, Any]] = None, extra_headers: Optional[Mapping[str, str]] = None) -> Any:
    return payload_data(client.request(method, path, body=body, params=params, extra_headers=extra_headers))


def write_secret_output(value: Any, filename: str) -> Dict[str, Any]:
    path = Path(filename).expanduser()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(str(path), flags, 0o600)
    except FileExistsError as exc:
        raise AdminError("secret output already exists; choose a new path") from exc
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return {"secret_output": str(path), "mode": "0600"}


def usage_rows(client: AdminClient, params: Mapping[str, Any], max_pages: int) -> List[Dict[str, Any]]:
    return fetch_all_pages(client, "/api/v1/admin/usage", params, max_pages=max_pages)


def money(value: Any) -> decimal.Decimal:
    try:
        return decimal.Decimal(str(value or 0))
    except decimal.InvalidOperation:
        return decimal.Decimal("0")


def usage_top_keys(client: AdminClient, args: argparse.Namespace) -> Dict[str, Any]:
    start = args.start_date
    end = args.end_date
    if not start or not end:
        start, end = today_range(args.timezone)
    parse_date(start); parse_date(end)
    params: Dict[str, Any] = {"start_date": start, "end_date": end, "timezone": args.timezone,
                              "sort_by": "created_at", "sort_order": "asc", "exact_total": "false"}
    for flag in ("user_id", "account_id", "group_id", "model", "request_type", "billing_type", "billing_mode"):
        value = getattr(args, flag, None)
        if value is not None:
            params[flag] = value
    if args.stream is not None:
        params["stream"] = str(args.stream).lower()
    rows = usage_rows(client, params, args.max_pages)
    grouped: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        key_id = row.get("api_key_id")
        if key_id is None:
            continue
        bucket = grouped.setdefault(str(key_id), {"api_key_id": int(key_id), "user_id": row.get("user_id"), "name": row.get("api_key_name") or row.get("key_name") or "", "requests": 0, "actual_cost": decimal.Decimal("0"), "total_cost": decimal.Decimal("0"), "tokens": 0})
        bucket["requests"] += 1
        bucket["actual_cost"] += money(row.get("actual_cost", row.get("cost")))
        bucket["total_cost"] += money(row.get("total_cost", row.get("cost")))
        bucket["tokens"] += int(row.get("total_tokens") or row.get("tokens") or 0)
    metric = args.metric
    ranked = sorted(grouped.values(), key=lambda item: item[metric], reverse=True)[:args.limit]
    for item in ranked:
        item[metric] = format(item[metric], "f")
        item["actual_cost"] = format(item["actual_cost"], "f")
        item["total_cost"] = format(item["total_cost"], "f")
    return {"start_date": start, "end_date": end, "timezone": args.timezone, "metric": metric, "rows_scanned": len(rows), "complete": True, "items": ranked}


def command_management(client: AdminClient, args: argparse.Namespace) -> Any:
    if args.command == "users":
        if args.action == "list":
            return admin_request(client, "GET", "/api/v1/admin/users", params={k: v for k, v in {"page": args.page, "page_size": args.page_size, "search": args.search, "status": args.status, "role": args.role, "sort_by": args.sort_by, "sort_order": args.sort_order}.items() if v is not None})
        if args.action == "usage":
            if args.self_user:
                me = admin_request(client, "GET", "/api/v1/admin/users/me")
                args.user_id = int(me.get("id"))
            if not args.user_id: raise AdminError("users usage requires --user-id or --self")
            start, end = (args.start_date, args.end_date) if args.start_date and args.end_date else today_range(args.timezone)
            return admin_request(client, "GET", "/api/v1/admin/usage/stats", params={"user_id": args.user_id, "start_date": start, "end_date": end, "timezone": args.timezone, "nocache": 1})
        if args.action == "keys":
            return admin_request(client, "GET", "/api/v1/admin/users/%s/api-keys" % args.user_id, params={"page": args.page, "page_size": args.page_size})
    if args.command == "keys":
        base = "/api/v1/admin/users/%s/keys" % args.user_id
        if args.action == "list":
            return admin_request(client, "GET", base, params={"page": args.page, "page_size": args.page_size, "search": args.search, "status": args.status, "group_id": args.group_id})
        if args.action == "create":
            confirm(args, "create api key")
            headers = {"Idempotency-Key": args.idempotency_key} if args.idempotency_key else None
            created = admin_request(client, "POST", base, body=json.loads(args.json_body), extra_headers=headers)
            result = {"key": {k: v for k, v in created.items() if k != "key"}} if isinstance(created, Mapping) else {}
            if args.secret_output:
                result.update(write_secret_output(created, args.secret_output))
            return result
        key_path = base + "/%s" % args.key_id
        if args.action == "get":
            return admin_request(client, "GET", key_path)
        if args.action == "update":
            confirm(args, "update api key")
            return admin_request(client, "PUT", key_path, body=json.loads(args.json_body))
        if args.action == "delete":
            confirm(args, "delete api key")
            return admin_request(client, "DELETE", key_path)
    if args.command == "usage" and args.action == "top-keys":
        return usage_top_keys(client, args)
    if args.command == "accounts" and args.action == "load":
        params = {"page_size": args.page_size, "platform": args.platform, "type": args.type, "status": args.status, "group": args.group, "search": args.search, "sort_by": args.sort_by, "sort_order": args.sort_order, "include_scheduler_score": "1", "lite": "1"}
        rows = fetch_all_pages(client, "/api/v1/admin/accounts", {k: v for k, v in params.items() if v is not None}, args.max_pages)
        return {"filters": {k: v for k, v in params.items() if v is not None}, "count": len(rows), "items": rows}
    if args.command == "scheduled-tests":
        if args.action == "list":
            if args.account_id is None: raise AdminError("scheduled-tests list requires --account-id")
            return admin_request(client, "GET", "/api/v1/admin/accounts/%s/scheduled-test-plans" % args.account_id)
        path = "/api/v1/admin/scheduled-test-plans"
        if args.action == "create":
            confirm(args, "create scheduled test")
            return admin_request(client, "POST", path, body=json.loads(args.json_body))
        if args.action in ("get-results", "update", "delete"):
            path += "/%s" % args.plan_id
        if args.action == "get-results":
            return admin_request(client, "GET", path + "/results", params={"limit": args.limit})
        if args.action == "update":
            confirm(args, "update scheduled test")
            return admin_request(client, "PUT", path, body=json.loads(args.json_body))
        if args.action == "delete":
            confirm(args, "delete scheduled test")
            return admin_request(client, "DELETE", path)
    if args.command == "backup-schedule":
        path = "/api/v1/admin/backups/schedule"
        if args.action == "get": return admin_request(client, "GET", path)
        confirm(args, "update backup schedule")
        return admin_request(client, "PUT", path, body=json.loads(args.json_body))
    if args.command == "scheduler-settings":
        path = "/api/v1/admin/settings"
        if args.action == "get":
            return admin_request(client, "GET", path)
        confirm(args, "update scheduler settings")
        return admin_request(client, "PUT", path, body=json.loads(args.json_body))
    raise AdminError("unsupported management command")


class RemoteDiagnostics:
    """Run a small allowlisted set of read-only commands through the SSH helper."""
    COMMANDS = {
        "service": "systemctl is-active sub2api; systemctl --no-pager --full status sub2api",
        "database": "pg_isready",
        "redis": "redis-cli ping",
        "ports": "ss -ltn",
        "logs": "journalctl -u sub2api --no-pager -n 200",
    }

    def __init__(self, script: str, timeout: float = 20.0):
        self.script = Path(script).expanduser()
        self.timeout = timeout

    def _argv(self, remote_command: str) -> List[str]:
        if not self.script.exists():
            raise AdminError("SSH helper not found: " + str(self.script))
        text = self.script.read_text(encoding="utf-8").strip()
        lines = [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
        if not lines:
            raise AdminError("SSH helper is empty")
        # `remote_command` comes only from COMMANDS above; it is never built
        # from CLI input.  Keep compound commands (for example service status
        # plus systemctl output) intact so the remote SSH shell can execute
        # them, while still rejecting unknown command keys in run().
        base = shlex.split(lines[-1])
        if not base:
            raise AdminError("SSH helper has no executable command")
        if "$@" in lines[-1] or "\"$@\"" in lines[-1]:
            return [str(self.script), remote_command]
        return base + [remote_command]

    def run(self, check: str) -> Dict[str, Any]:
        if check not in self.COMMANDS:
            raise AdminError("unsupported SSH check: " + check)
        command = self.COMMANDS[check]
        try:
            completed = subprocess.run(self._argv(command), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       universal_newlines=True, timeout=self.timeout, check=False)
        except OSError as exc:
            raise AdminError("SSH command failed: " + str(exc)) from exc
        return {"check": check, "returncode": completed.returncode, "stdout": redact(completed.stdout), "stderr": redact(completed.stderr)}


def build_client(args: argparse.Namespace) -> AdminClient:
    config = load_config()
    base_url = args.base_url or os.environ.get("SUB2API_BASE_URL") or str(config.get("base_url", ""))
    explicit_token = args.token or os.environ.get("SUB2API_ADMIN_TOKEN")
    jwt = os.environ.get("SUB2API_JWT")
    api_key = os.environ.get("SUB2API_ADMIN_API_KEY")
    if not explicit_token and not jwt and not api_key and os.environ.get("SUB2API_KEYCHAIN", "true").lower() not in {"0", "false", "no"}:
        explicit_token = keychain_token(base_url, config)
    token = explicit_token or jwt or api_key
    auth_mode = args.auth_mode or os.environ.get("SUB2API_AUTH_MODE") or str(config.get("auth_mode", "auto"))
    if auth_mode == "auto":
        # The bundled server uses x-api-key for its generated admin key.  The
        # documented admin- prefix is a useful default, while explicit JWT and
        # legacy API-key aliases remain unambiguous.
        if api_key and not explicit_token and not jwt:
            auth_mode = "api-key"
        elif jwt and not explicit_token:
            auth_mode = "bearer"
        elif str(explicit_token or "").lower().startswith("admin-"):
            auth_mode = "api-key"
        else:
            auth_mode = "bearer"
    return AdminClient(base_url, token or "", auth_mode, args.timeout, args.retries)


def output_value(value: Any, output_format: str, output_file: Optional[str] = None) -> None:
    safe = redact(value)
    if output_format == "json":
        text = json.dumps(safe, ensure_ascii=False, indent=2, default=str)
    elif output_format == "csv":
        rows = safe if isinstance(safe, list) else [safe]
        fields = sorted({key for row in rows if isinstance(row, Mapping) for key in row})
        lines = []
        writer_target = []
        import io
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row if isinstance(row, Mapping) else {"value": row})
        text = buffer.getvalue()
    else:
        text = markdown(safe)
    if output_file:
        Path(output_file).write_text(text + ("\n" if not text.endswith("\n") else ""), encoding="utf-8")
    else:
        print(text)


def markdown(value: Any) -> str:
    if isinstance(value, Mapping):
        lines = ["# Sub2API Operations Report", "", "| Field | Value |", "|---|---|"]
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                item = json.dumps(item, ensure_ascii=False, default=str)
            lines.append("| %s | %s |" % (str(key).replace("|", "\\|"), str(item).replace("|", "\\|")))
        return "\n".join(lines)
    if isinstance(value, list):
        if not value:
            return "# Sub2API Operations Report\n\nNo records."
        fields = list(value[0].keys()) if isinstance(value[0], Mapping) else ["value"]
        lines = ["# Sub2API Operations Report", "", "| " + " | ".join(fields) + " |", "|" + "|".join("---" for _ in fields) + "|"]
        for item in value:
            row = item if isinstance(item, Mapping) else {"value": item}
            lines.append("| " + " | ".join(str(row.get(field, "")).replace("|", "\\|") for field in fields) + " |")
        return "\n".join(lines)
    return str(value)


def confirm(args: argparse.Namespace, action: str) -> None:
    if not args.confirm:
        raise AdminError("%s requires --confirm; no changes were made" % action)


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base-url", help="Sub2API base URL; defaults to SUB2API_BASE_URL")
    parser.add_argument("--token", help="replaceable admin token; prefer SUB2API_ADMIN_TOKEN")
    parser.add_argument("--auth-mode", choices=("auto", "bearer", "api-key"), default=None,
                        help="authentication transport; auto also reads SUB2API_AUTH_MODE")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--format", choices=("json", "markdown", "csv"), default="json")
    parser.add_argument("--output", help="write the report to a file")


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    add_common(common)
    parser = argparse.ArgumentParser(description="Safe Sub2API admin diagnostics and error analysis", parents=[common])
    sub = parser.add_subparsers(dest="command")

    health = sub.add_parser("health", help="check remote service dependencies", parents=[common])
    health.add_argument("--ssh-script", default=os.environ.get("SUB2API_SSH_SCRIPT", "/Users/james/sub2api_gcp.sh"))
    health.add_argument("--checks", default="service,database,redis,ports")

    for name, help_text in (("ops-report", "build a windowed operations report"), ("account-report", "summarize errors by account")):
        item = sub.add_parser(name, help=help_text, parents=[common])
        item.add_argument("--since", default="24h")
        item.add_argument("--until")
        if name == "account-report":
            item.add_argument("--ids", required=True, help="comma-separated account IDs")

    dashboard = sub.add_parser("dashboard", help="fetch an ops dashboard endpoint", parents=[common])
    dashboard.add_argument("kind", choices=("snapshot", "overview", "error-trend", "error-distribution"), default="snapshot")
    dashboard.add_argument("--since", default="6h")

    errors = sub.add_parser("errors", help="list, analyze, or resolve errors", parents=[common])
    errors.add_argument("action", choices=("list", "get", "analyze", "resolve", "request-upstream"))
    errors.add_argument("--since", default="24h")
    errors.add_argument("--until")
    errors.add_argument("--account-id", type=int)
    errors.add_argument("--status-codes")
    errors.add_argument("--id", type=int)
    errors.add_argument("--resolved", choices=("true", "false"))
    errors.add_argument("--confirm", action="store_true")

    api = sub.add_parser("api", help="call an arbitrary admin endpoint", parents=[common])
    api.add_argument("method", choices=("GET", "POST", "PUT", "PATCH", "DELETE"))
    api.add_argument("path", help="/admin/... or /api/v1/admin/... path")
    api.add_argument("--json", dest="json_body", help="JSON request body")
    api.add_argument("--file", dest="json_file", help="read JSON request body from a file")
    api.add_argument("--confirm", action="store_true", help="required for POST/PUT/PATCH/DELETE")

    users = sub.add_parser("users", help="query and manage users", parents=[common])
    users.add_argument("action", choices=("list", "usage", "keys"))
    users.add_argument("--user-id", type=int); users.add_argument("--self", dest="self_user", action="store_true")
    users.add_argument("--page", type=int, default=1); users.add_argument("--page-size", type=int, default=100)
    users.add_argument("--search"); users.add_argument("--status"); users.add_argument("--role")
    users.add_argument("--sort-by", default="created_at"); users.add_argument("--sort-order", default="desc")
    users.add_argument("--start-date"); users.add_argument("--end-date"); users.add_argument("--timezone", default="Asia/Shanghai")

    keys = sub.add_parser("keys", help="manage user API keys", parents=[common])
    keys.add_argument("action", choices=("list", "get", "create", "update", "delete"))
    keys.add_argument("--user-id", type=int, required=True); keys.add_argument("--key-id", type=int)
    keys.add_argument("--page", type=int, default=1); keys.add_argument("--page-size", type=int, default=100)
    keys.add_argument("--search"); keys.add_argument("--status"); keys.add_argument("--group-id", type=int)
    keys.add_argument("--json", dest="json_body"); keys.add_argument("--idempotency-key"); keys.add_argument("--secret-output"); keys.add_argument("--confirm", action="store_true")

    usage_cmd = sub.add_parser("usage", help="aggregate usage", parents=[common])
    usage_cmd.add_argument("action", choices=("top-keys",))
    usage_cmd.add_argument("--start-date"); usage_cmd.add_argument("--end-date"); usage_cmd.add_argument("--timezone", default="Asia/Shanghai")
    usage_cmd.add_argument("--limit", type=int, default=5); usage_cmd.add_argument("--metric", choices=("actual_cost", "total_cost", "tokens"), default="actual_cost")
    usage_cmd.add_argument("--user-id", type=int); usage_cmd.add_argument("--account-id", type=int); usage_cmd.add_argument("--group-id", type=int)
    usage_cmd.add_argument("--model"); usage_cmd.add_argument("--request-type"); usage_cmd.add_argument("--billing-type", type=int); usage_cmd.add_argument("--billing-mode"); usage_cmd.add_argument("--stream", type=lambda v: v.lower() == "true")
    usage_cmd.add_argument("--max-pages", type=int, default=1000)

    accounts_load = sub.add_parser("accounts", help="account management extensions", parents=[common])
    accounts_load.add_argument("action", choices=("load",)); accounts_load.add_argument("--page-size", type=int, default=200); accounts_load.add_argument("--max-pages", type=int, default=1000)
    accounts_load.add_argument("--platform"); accounts_load.add_argument("--type"); accounts_load.add_argument("--status"); accounts_load.add_argument("--group"); accounts_load.add_argument("--search"); accounts_load.add_argument("--sort-by", default="name"); accounts_load.add_argument("--sort-order", default="asc")

    plans = sub.add_parser("scheduled-tests", help="manage scheduled account tests", parents=[common])
    plans.add_argument("action", choices=("list", "create", "update", "delete", "get-results")); plans.add_argument("--account-id", type=int); plans.add_argument("--plan-id", type=int); plans.add_argument("--json", dest="json_body"); plans.add_argument("--limit", type=int); plans.add_argument("--confirm", action="store_true")

    backup_schedule = sub.add_parser("backup-schedule", help="manage scheduled backups", parents=[common])
    backup_schedule.add_argument("action", choices=("get", "update")); backup_schedule.add_argument("--json", dest="json_body"); backup_schedule.add_argument("--confirm", action="store_true")

    scheduler = sub.add_parser("scheduler-settings", help="read or update scheduler settings", parents=[common])
    scheduler.add_argument("action", choices=("get", "update")); scheduler.add_argument("--json", dest="json_body"); scheduler.add_argument("--confirm", action="store_true")

    logs = sub.add_parser("system-logs", help="list or safely clean indexed system logs", parents=[common])
    logs.add_argument("action", choices=("list", "cleanup"))
    logs.add_argument("--since", default="1h")
    logs.add_argument("--filter-file")
    for name in ("host", "level", "component", "request-id", "client-request-id", "platform", "model", "q"):
        logs.add_argument("--" + name, dest=name.replace("-", "_"))
    for name in ("user-id", "api-key-id", "account-id"):
        logs.add_argument("--" + name, dest=name.replace("-", "_"), type=int)
    logs.add_argument("--confirm", action="store_true")
    return parser


def time_window(args: argparse.Namespace) -> Tuple[dt.datetime, Optional[dt.datetime]]:
    return parse_since(args.since), parse_since(args.until) if args.until else None


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if not args.command:
            raise AdminError("a command is required; use --help")
        if args.command == "health":
            remote = RemoteDiagnostics(args.ssh_script, args.timeout)
            result = {check: remote.run(check) for check in args.checks.split(",") if check}
            output_value({"checked_at": iso_now(), "checks": result}, args.format, args.output)
            return 0 if all(item.get("returncode") == 0 for item in result.values()) else 1

        client = build_client(args)
        if args.command in {"users", "keys", "usage", "accounts", "scheduled-tests", "backup-schedule", "scheduler-settings"}:
            output_value(command_management(client, args), args.format, args.output)
            return 0
        if args.command == "dashboard":
            since, until = time_window(args)
            path = {
                "snapshot": "/api/v1/admin/ops/dashboard/snapshot-v2",
                "overview": "/api/v1/admin/ops/dashboard/overview",
                "error-trend": "/api/v1/admin/ops/dashboard/error-trend",
                "error-distribution": "/api/v1/admin/ops/dashboard/error-distribution",
            }[args.kind]
            output_value(client.request("GET", path, params={"start_time": since.isoformat(), "end_time": until.isoformat() if until else None}), args.format, args.output)
            return 0

        if args.command == "api":
            if args.json_body and args.json_file:
                raise AdminError("api accepts only one of --json or --file")
            if args.method != "GET":
                confirm(args, "api " + args.method)
            body = None
            if args.json_body:
                body = json.loads(args.json_body)
            elif args.json_file:
                body = json.loads(Path(args.json_file).read_text(encoding="utf-8"))
            path = args.path if args.path.startswith("/") else "/" + args.path
            if path.startswith("/admin/"):
                path = "/api/v1" + path
            output_value(client.request(args.method, path, body=body), args.format, args.output)
            return 0

        if args.command == "system-logs":
            since, until = time_window(args)
            if args.action == "list":
                params = {"start_time": since.isoformat(), "end_time": until.isoformat() if until else None, "page_size": 200}
                for name in ("host", "level", "component", "request_id", "client_request_id", "platform", "model", "q"):
                    value = getattr(args, name, None)
                    if value:
                        params[name] = value
                for name in ("user_id", "api_key_id", "account_id"):
                    value = getattr(args, name, None)
                    if value is not None:
                        params[name] = value
                output_value(client.request("GET", "/api/v1/admin/ops/system-logs", params=params), args.format, args.output)
                return 0
            if not args.filter_file:
                raise AdminError("system-logs cleanup requires --filter-file")
            confirm(args, "system-logs cleanup")
            payload = json.loads(Path(args.filter_file).read_text(encoding="utf-8"))
            output_value(client.request("POST", "/api/v1/admin/ops/system-logs/cleanup", body=payload), args.format, args.output)
            return 0

        since, until = time_window(args)
        status_codes = [int(value) for value in args.status_codes.split(",")] if getattr(args, "status_codes", None) else None
        if args.command == "errors" and args.action == "get":
            if not args.id:
                raise AdminError("errors get requires --id")
            output_value(client.error_detail(args.id), args.format, args.output)
            return 0
        if args.command == "errors" and args.action == "request-upstream":
            if not args.id:
                raise AdminError("errors request-upstream requires --id")
            output_value(client.request_error_upstream(args.id, params={"include_detail": "true"}), args.format, args.output)
            return 0
        if args.command == "errors" and args.action == "resolve":
            if not args.id or args.resolved is None:
                raise AdminError("errors resolve requires --id and --resolved")
            confirm(args, "errors resolve")
            output_value(client.request("PUT", "/api/v1/admin/ops/errors/%s/resolve" % args.id, body={"resolved": args.resolved == "true"}), args.format, args.output)
            return 0
        if args.command in ("ops-report", "account-report", "errors"):
            records, source_counts = client.collect_error_records(
                since, until, getattr(args, "account_id", None) if args.command == "errors" else None, status_codes
            )
            if args.command == "errors" and args.action == "list":
                output_value(records, args.format, args.output)
                return 0
            if args.command == "errors" and args.action == "analyze":
                output_value({"generated_at": iso_now(), "window": {"since": since.isoformat(), "until": until.isoformat() if until else None}, "sources": source_counts, "summary": aggregate_errors(records), "recommendations": recommendations(records)}, args.format, args.output)
                return 0
            overview = None
            try:
                overview = client.request("GET", "/api/v1/admin/ops/dashboard/overview", params={"start_time": since.isoformat(), "end_time": until.isoformat() if until else None})
            except AdminError:
                overview = None
            report = {
                "generated_at": iso_now(),
                "window": {"since": since.isoformat(), "until": until.isoformat() if until else None},
                "sources": source_counts,
                "traffic": traffic_metrics(overview, len(records)),
                "summary": aggregate_errors(records),
                # /upstream-errors may include recovered/inference rows with a
                # 2xx status.  Top-account error volume should count actual
                # HTTP errors only, while the full summary remains available.
                "top_accounts": account_error_report(
                    [row for row in records if as_int(first(row, "status_code", "status", default=0)) >= 400], []
                )[:3],
            }
            if args.command == "account-report":
                ids = [int(item.strip()) for item in args.ids.split(",") if item.strip()]
                report["accounts"] = account_error_report(records, ids)
                account_stats = {}
                days = max(1, int((dt.datetime.now(dt.timezone.utc) - since).total_seconds() / 86400) + 1)
                for account_id in ids:
                    try:
                        account_stats[str(account_id)] = client.request("GET", "/api/v1/admin/accounts/%s/stats" % account_id, params={"days": days})
                    except AdminError:
                        account_stats[str(account_id)] = {"unavailable": True}
                report["account_stats"] = redact(account_stats)
            report["recommendations"] = recommendations(records)
            output_value(report, args.format, args.output)
            return 0
        raise AdminError("unsupported command")
    except (AdminError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(redact(str(exc)), file=sys.stderr)
        return 2


def recommendations(records: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    summary = aggregate_errors(records)
    suggestions = []
    if summary["status_counts"].get("503"):
        suggestions.append({"cause": "upstream_unavailable_or_overloaded", "action": "检查上游健康、代理可达性、并发/限流和重试风暴；不要仅凭 503 暂停全部账号。"})
    if summary["status_counts"].get("502"):
        suggestions.append({"cause": "upstream_gateway_or_transport", "action": "按账号/代理/request_id 钻取，检查代理连接、TLS、上游响应和 Nginx 转发；确认是否为单一代理集中失败。"})
    if summary["category_counts"].get("account_or_auth"):
        suggestions.append({"cause": "account_authentication_or_quota", "action": "检查账号凭据、额度、临时不可调度状态，并先做单账号测试。"})
    if not suggestions:
        suggestions.append({"cause": "insufficient_context", "action": "扩大时间窗口并查询 request-errors/upstream-errors 详情，以获得 request_id、upstream_status_code 和代理上下文。"})
    return suggestions


if __name__ == "__main__":
    sys.exit(main())
