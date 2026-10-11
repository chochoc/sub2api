#!/usr/bin/env python3
"""Measure prompt-cache usage for repeated, identical Sub2API requests.

The runner makes one cold request followed by repeated requests with the exact
same JSON body. It records only status, timing and usage metadata; API keys,
prompts and response bodies are never written to the report.
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


DEFAULT_BASE_URL = "https://127.0.0.1:8443"
DEFAULT_REQUESTS = 30
DEFAULT_TIMEOUT = 120.0
DEFAULT_INTERVAL_MS = 100

# Long enough for providers whose cache threshold is above a short chat prompt.
# A deployment with known production material should pass --context-file.
REFERENCE_SECTIONS = (
    "The gateway preserves message order, role, content, model and generation settings when it forwards a request.",
    "A cache key identifies the user and model scope; it must not be shared across unrelated users or groups.",
    "A cache hit is measured from upstream usage, never inferred from response latency or a local response cache.",
    "The first request warms the prefix. Later requests repeat the same body so only the upstream cache state can vary.",
    "Usage accounting keeps prompt tokens, completion tokens and total tokens additive and reports cached input tokens separately.",
    "Streaming responses expose their final usage in a terminal chunk when include_usage is enabled.",
    "Failed requests and responses without verifiable usage are excluded from both hit-rate denominators.",
    "A valid cached token count is non-negative and cannot exceed the prompt token count for that request.",
)


def default_reference() -> str:
    sections: list[str] = []
    for index in range(1, 65):
        rule = REFERENCE_SECTIONS[(index - 1) % len(REFERENCE_SECTIONS)]
        sections.append(
            f"Reference section {index:02d}. {rule} "
            f"This section is part of the cache measurement fixture and has stable identifier R-{index:02d}."
        )
    return "\n\n".join(sections)


@dataclass
class HttpResult:
    status: int
    headers: dict[str, str]
    body: bytes
    elapsed_ms: int

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


class Client:
    def __init__(self, base_url: str, api_key: str, timeout: float, verify_tls: bool) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.ssl_context = ssl.create_default_context() if verify_tls else ssl._create_unverified_context()

    def request(self, path: str, payload: Any = None, accept: str = "application/json") -> HttpResult:
        headers = {
            "Accept": accept,
            "User-Agent": "sub2api-cc002-cache-test/1.0",
            "X-Client-Request-Id": str(uuid.uuid4()),
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers=headers,
            method="POST" if data is not None else "GET",
        )
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout, context=self.ssl_context) as response:
                return HttpResult(
                    response.status,
                    {key.lower(): value for key, value in response.headers.items()},
                    response.read(),
                    int((time.monotonic() - started) * 1000),
                )
        except urllib.error.HTTPError as error:
            return HttpResult(
                error.code,
                {key.lower(): value for key, value in error.headers.items()},
                error.read(),
                int((time.monotonic() - started) * 1000),
            )
        except (urllib.error.URLError, TimeoutError) as error:
            return HttpResult(
                0,
                {},
                str(error).encode("utf-8", errors="replace"),
                int((time.monotonic() - started) * 1000),
            )


def json_object(raw: bytes) -> dict[str, Any] | None:
    try:
        value = json.loads(raw.decode("utf-8", errors="replace"))
    except (ValueError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


def usage_from_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    value = payload.get("usage") if payload else None
    return value if isinstance(value, dict) else None


def cache_fields(value: dict[str, Any] | None) -> tuple[int | None, int | None, str | None]:
    """Return prompt tokens, cached tokens and the field carrying cached tokens."""
    if not value:
        return None, None, None
    prompt = value.get("prompt_tokens")
    prompt_value = prompt if isinstance(prompt, int) else None
    details = value.get("prompt_tokens_details")
    if isinstance(details, dict) and isinstance(details.get("cached_tokens"), int):
        return prompt_value, details["cached_tokens"], "prompt_tokens_details.cached_tokens"
    # Some compatible upstreams expose the same value at the usage top level.
    if isinstance(value.get("cached_tokens"), int):
        return prompt_value, value["cached_tokens"], "cached_tokens"
    return prompt_value, None, None


def parse_sse(result: HttpResult) -> tuple[dict[str, Any] | None, int]:
    """Extract terminal usage and the number of SSE [DONE] markers."""
    usage: dict[str, Any] | None = None
    done_count = 0
    for line in result.text.splitlines():
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            done_count += 1
            continue
        try:
            payload = json.loads(data)
        except ValueError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("usage"), dict):
            usage = payload["usage"]
    return usage, done_count


def response_usage(result: HttpResult, mode: str) -> tuple[dict[str, Any] | None, int | None]:
    if mode == "sse":
        usage, done_count = parse_sse(result)
        return usage, done_count
    return usage_from_payload(json_object(result.body)), None


def sample(result: HttpResult, mode: str, request_index: int) -> dict[str, Any]:
    usage, done_count = response_usage(result, mode)
    prompt, cached, cached_field = cache_fields(usage)
    valid = (
        result.status == 200
        and isinstance(prompt, int)
        and prompt >= 0
        and isinstance(cached, int)
        and 0 <= cached <= prompt
    )
    return {
        "request": request_index,
        "status": result.status,
        "elapsed_ms": result.elapsed_ms,
        "content_type": result.headers.get("content-type", ""),
        "usage_seen": usage is not None,
        "prompt_tokens": prompt,
        "cached_tokens": cached,
        "cached_tokens_field": cached_field,
        "valid_usage": valid,
        **({"done_count": done_count} if done_count is not None else {}),
    }


def summarize(samples: list[dict[str, Any]]) -> dict[str, Any]:
    def metrics(window: Iterable[dict[str, Any]]) -> dict[str, Any]:
        window_samples = list(window)
        successful = [item for item in window_samples if item["status"] == 200]
        valid = [item for item in window_samples if item.get("valid_usage")]
        prompts = sum(item["prompt_tokens"] for item in valid)
        cached = sum(item["cached_tokens"] for item in valid)
        return {
            "requests": len(window_samples),
            "successful_requests": len(successful),
            "valid_usage_samples": len(valid),
            "usage_coverage": len(valid) / len(successful) if successful else None,
            "request_hit_rate": (
                sum(item["cached_tokens"] > 0 for item in valid) / len(valid) if valid else None
            ),
            "token_hit_rate": cached / prompts if prompts else None,
            "prompt_tokens_sum": prompts if valid else None,
            "cached_tokens_sum": cached if valid else None,
        }

    successful = [item for item in samples if item["status"] == 200]
    usable = [item for item in samples if item.get("valid_usage")]
    return {
        "requests": len(samples),
        "successful_requests": len(successful),
        "usage_samples": sum(item["usage_seen"] for item in successful),
        "valid_usage_samples": len(usable),
        "invalid_or_missing_usage": len(successful) - len(usable),
        "usage_coverage": len(usable) / len(successful) if successful else None,
        "request_hit_rate": sum(item["cached_tokens"] > 0 for item in usable) / len(usable) if usable else None,
        "token_hit_rate": (
            sum(item["cached_tokens"] for item in usable) / sum(item["prompt_tokens"] for item in usable)
            if usable and sum(item["prompt_tokens"] for item in usable)
            else None
        ),
        "prompt_tokens_sum": sum(item["prompt_tokens"] for item in usable) if usable else None,
        "cached_tokens_sum": sum(item["cached_tokens"] for item in usable) if usable else None,
        "all_window": metrics(samples),
        "warm_window": metrics(samples[1:]),
    }


def load_reference(path: str | None) -> str:
    if not path:
        return default_reference()
    reference = Path(path).read_text(encoding="utf-8")
    if not reference.strip():
        raise ValueError("SUB2API_CACHE_CONTEXT_FILE is empty")
    return reference


def discover_model(client: Client, override: str | None) -> str:
    result = client.request("/v1/models")
    payload = json_object(result.body)
    ids = [
        item.get("id")
        for item in (payload or {}).get("data", [])
        if isinstance(item, dict) and item.get("id")
    ]
    if result.status != 200 or not ids:
        raise RuntimeError(f"model discovery failed: HTTP {result.status}")
    if override:
        return override
    preferred = [model for model in ids if any(name in model.lower() for name in ("codex", "gpt-5", "gpt-4", "o3"))]
    return (preferred or ids)[0]


def request_payload(model: str, reference: str, run_id: str, mode: str) -> dict[str, Any]:
    """Build one stable body; the same object is sent for every repeat."""
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": f"Cache measurement run {run_id}.\n{reference}"},
            {"role": "user", "content": "Explain one concrete invariant in the reference in two sentences."},
        ],
        "stream": mode == "sse",
    }
    if mode == "sse":
        payload["stream_options"] = {"include_usage": True}
    return payload


def run_session(
    client: Client,
    model: str,
    reference: str,
    mode: str,
    requests: int,
    interval_seconds: float,
) -> dict[str, Any]:
    run_id = str(uuid.uuid4())
    payload = request_payload(model, reference, run_id, mode)
    samples: list[dict[str, Any]] = []
    failures: list[str] = []
    for request_index in range(requests):
        result = client.request(
            "/v1/chat/completions",
            payload,
            accept="text/event-stream" if mode == "sse" else "application/json",
        )
        current = sample(result, mode, request_index)
        samples.append(current)
        if result.status != 200:
            failures.append(f"request {request_index}: HTTP {result.status}")
        if mode == "sse" and current.get("done_count") != 1:
            failures.append(f"request {request_index}: expected one [DONE], got {current.get('done_count', 0)}")
        if request_index + 1 < requests and interval_seconds:
            time.sleep(interval_seconds)
    return {
        "run_id": run_id,
        "mode": mode,
        "requests_requested": requests,
        "samples": samples,
        "metrics": summarize(samples),
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("SUB2API_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--api-key", default=os.environ.get("SUB2API_API_KEY", ""))
    parser.add_argument("--model", default=os.environ.get("SUB2API_MODEL"))
    parser.add_argument("--mode", choices=("json", "sse", "both"), default=os.environ.get("SUB2API_CACHE_MODE", "json"))
    parser.add_argument(
        "--requests", "--rounds", dest="requests", type=int,
        default=int(os.environ.get("SUB2API_CACHE_REQUESTS", str(DEFAULT_REQUESTS))),
        help="identical requests per session (default: 30)",
    )
    parser.add_argument("--interval-ms", type=int, default=int(os.environ.get("SUB2API_CACHE_INTERVAL_MS", str(DEFAULT_INTERVAL_MS))))
    parser.add_argument("--timeout", type=float, default=float(os.environ.get("SUB2API_TIMEOUT", str(DEFAULT_TIMEOUT))))
    parser.add_argument("--report", default=os.environ.get("SUB2API_CACHE_REPORT", str(Path(__file__).with_name("report.json"))))
    parser.add_argument("--context-file", default=os.environ.get("SUB2API_CACHE_CONTEXT_FILE"))
    parser.add_argument("--verify-tls", action="store_true", default=os.environ.get("SUB2API_VERIFY_TLS") == "1")
    args = parser.parse_args(argv)
    if args.requests < 2:
        parser.error("--requests must be at least 2 (one warm-up plus one repeat)")
    if args.interval_ms < 0:
        parser.error("--interval-ms cannot be negative")
    if not args.api_key:
        print("BLOCKED: SUB2API_API_KEY is not set", file=sys.stderr)
        return 2

    started = time.time()
    client = Client(args.base_url, args.api_key, args.timeout, args.verify_tls)
    health = client.request("/health")
    if health.status != 200:
        print(f"deployment health check failed: HTTP {health.status}", file=sys.stderr)
        return 1
    try:
        model = discover_model(client, args.model)
        reference = load_reference(args.context_file)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"configuration failed: {error}", file=sys.stderr)
        return 1

    modes = ("json", "sse") if args.mode == "both" else (args.mode,)
    sessions = [run_session(client, model, reference, mode, args.requests, args.interval_ms / 1000) for mode in modes]
    report = {
        "base_url": args.base_url.rstrip("/"),
        "api_key": "configured",
        "model": model,
        "modes": list(modes),
        "requests_per_session": args.requests,
        "interval_ms": args.interval_ms,
        "reference_bytes": len(reference.encode("utf-8")),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "duration_seconds": round(time.time() - started, 1),
        "sessions": sessions,
    }
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"model": model, "sessions": len(sessions), "report": str(report_path)}, ensure_ascii=False))

    failed = any(session["failures"] for session in sessions)
    missing_usage = any(
        session["metrics"]["valid_usage_samples"] < session["metrics"]["successful_requests"]
        for session in sessions
    )
    if failed:
        return 1
    if missing_usage:
        print("BLOCKED: successful responses did not all expose verifiable cached_tokens", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
