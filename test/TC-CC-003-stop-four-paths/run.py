#!/usr/bin/env python3
"""Black-box CC003 stop-path and prompt-cache test for Sub2API.

The runner exercises JSON/SSE client responses through the public
``/v1/chat/completions`` endpoint.  It records only response metadata, usage
and redacted assertions; prompts and response bodies are never written to the
report.  Upstream transport labels are deployment metadata: a public
Sub2API response cannot prove whether the selected channel used JSON or SSE.
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
DEFAULT_TIMEOUT = 120.0
STOP = "<END>"
OMITTED = object()

# The four labels mirror the MAAS matrix.  The upstream column is an expected
# deployment/fixture mode and is deliberately marked unverified in reports.
PATHS = (
    ("CC003-JJ", "json", "json"),
    ("CC003-SJ", "json", "sse"),
    ("CC003-SS", "sse", "sse"),
    ("CC003-JS", "sse", "json"),
)

BOUNDARY_CASES: tuple[tuple[str, str, Any, str], ...] = (
    ("cross", "hello<END>secret", [STOP], "hello"),
    ("first", "<END>secret", [STOP], ""),
    ("last", "hello<END>", [STOP], "hello"),
    ("absent", "hello<EN", [STOP], "hello<EN"),
    ("unicode", "你好🌍结束秘密", ["🌍结束"], "你好"),
    ("overlap-long", "abc", ["abc", "b"], ""),
    ("overlap-short", "abx", ["abc", "b"], "a"),
    ("four", "helloENDsecret", ["ZZ", "END", "ENDsecret", "Z"], "hello"),
    ("null", "hello<END>secret", None, "hello<END>secret"),
    ("omitted", "hello<END>secret", OMITTED, "hello<END>secret"),
)

INVALID_STOP_CASES: tuple[tuple[str, Any], ...] = (
    ("empty-string", ""),
    ("empty-array", []),
    ("empty-item", [""]),
    ("too-many", ["a", "b", "c", "d", "e"]),
    ("wrong-number", 42),
    ("wrong-object", {}),
    ("wrong-item-type", [1]),
    ("too-long", ["x" * 65537]),
)


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
            "User-Agent": "sub2api-cc003-stop-cache-test/1.0",
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
        except (urllib.error.URLError, TimeoutError, OSError) as error:
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


def cache_fields(usage: dict[str, Any] | None) -> tuple[int | None, int | None, str | None]:
    if not usage:
        return None, None, None
    prompt = usage.get("prompt_tokens")
    prompt = prompt if isinstance(prompt, int) and not isinstance(prompt, bool) else None
    details = usage.get("prompt_tokens_details")
    if isinstance(details, dict) and isinstance(details.get("cached_tokens"), int):
        return prompt, details["cached_tokens"], "prompt_tokens_details.cached_tokens"
    if isinstance(usage.get("cached_tokens"), int):
        return prompt, usage["cached_tokens"], "cached_tokens"
    return prompt, None, None


def parse_sse(result: HttpResult) -> dict[str, Any]:
    content: list[str] = []
    fragments: list[str] = []
    reasons: list[str] = []
    usage: dict[str, Any] | None = None
    done_count = 0
    usage_count = 0
    normalized = result.text.replace("\r\n", "\n")
    for frame in normalized.split("\n\n"):
        data_lines = [line[5:].lstrip() for line in frame.split("\n") if line.startswith("data:")]
        if not data_lines:
            continue
        data = "\n".join(data_lines)
        if data == "[DONE]":
            done_count += 1
            continue
        try:
            payload = json.loads(data)
        except ValueError:
            continue
        if not isinstance(payload, dict):
            continue
        if isinstance(payload.get("usage"), dict):
            usage = payload["usage"]
            usage_count += 1
        for choice in payload.get("choices", []):
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta")
            if isinstance(delta, dict) and isinstance(delta.get("content"), str):
                fragments.append(delta["content"])
                content.append(delta["content"])
            if isinstance(choice.get("finish_reason"), str):
                reasons.append(choice["finish_reason"])
    return {
        "content": "".join(content),
        "fragments": fragments,
        "reasons": reasons,
        "usage": usage,
        "usage_count": usage_count,
        "done_count": done_count,
    }


def parse_json(result: HttpResult) -> dict[str, Any]:
    payload = json_object(result.body) or {}
    choices = payload.get("choices")
    choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    return {
        "content": message.get("content") if isinstance(message.get("content"), str) else "",
        "fragments": [message["content"]] if isinstance(message.get("content"), str) else [],
        "reasons": [choice["finish_reason"]] if isinstance(choice.get("finish_reason"), str) else [],
        "usage": payload.get("usage") if isinstance(payload.get("usage"), dict) else None,
        "usage_count": 1 if isinstance(payload.get("usage"), dict) else 0,
        "done_count": None,
    }


def parsed(result: HttpResult, mode: str) -> dict[str, Any]:
    return parse_sse(result) if mode == "sse" else parse_json(result)


def oracle(text: str, stops: Iterable[str]) -> str:
    positions = [text.find(stop) for stop in stops if stop]
    positions = [position for position in positions if position >= 0]
    return text[: min(positions)] if positions else text


def sample(
    result: HttpResult,
    mode: str,
    path: str,
    case: str,
    expected: str | None = None,
    stop_enabled: bool = True,
) -> dict[str, Any]:
    data = parsed(result, mode)
    prompt, cached, cached_field = cache_fields(data["usage"])
    valid_usage = (
        result.status == 200
        and isinstance(prompt, int)
        and prompt >= 0
        and isinstance(cached, int)
        and 0 <= cached <= prompt
    )
    content = data["content"]
    stop_ok = expected is None or content == expected
    forbidden = ("<EN", STOP, "secret") if stop_enabled else ()
    leaked = any(fragment.find(token) >= 0 for fragment in data["fragments"] for token in forbidden)
    return {
        "path": path,
        "case": case,
        "status": result.status,
        "elapsed_ms": result.elapsed_ms,
        "content_type": result.headers.get("content-type", ""),
        "content_bytes": len(content.encode("utf-8")),
        "finish_reasons": data["reasons"],
        "finish_reason_stop": data["reasons"] == ["stop"],
        "done_count": data["done_count"],
        "usage_count": data["usage_count"],
        "usage_seen": data["usage"] is not None,
        "prompt_tokens": prompt,
        "cached_tokens": cached,
        "cached_tokens_field": cached_field,
        "valid_usage": valid_usage,
        "stop_content_ok": stop_ok,
        "stop_text_leaked": leaked,
    }


def summarize(samples: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [sample for sample in samples if sample["status"] == 200]
    valid = [sample for sample in successful if sample.get("valid_usage")]
    prompts = sum(sample["prompt_tokens"] for sample in valid)
    cached = sum(sample["cached_tokens"] for sample in valid)
    return {
        "requests": len(samples),
        "successful_requests": len(successful),
        "valid_usage_samples": len(valid),
        "invalid_or_missing_usage": len(successful) - len(valid),
        "usage_coverage": len(valid) / len(successful) if successful else None,
        "request_hit_rate": sum(sample["cached_tokens"] > 0 for sample in valid) / len(valid) if valid else None,
        "token_hit_rate": cached / prompts if prompts else None,
        "prompt_tokens_sum": prompts if valid else None,
        "cached_tokens_sum": cached if valid else None,
    }


def reference_text(path: str | None) -> str:
    if path:
        value = Path(path).read_text(encoding="utf-8")
        if not value.strip():
            raise ValueError("--context-file is empty")
        return value
    return "\n\n".join(
        f"Stable cache section {index:02d}. The gateway preserves role, order and model while reporting upstream cached input tokens."
        for index in range(1, 65)
    )


def discover_model(client: Client, override: str | None) -> str:
    result = client.request("/v1/models")
    payload = json_object(result.body)
    ids = [item.get("id") for item in (payload or {}).get("data", []) if isinstance(item, dict) and item.get("id")]
    if result.status != 200 or not ids:
        raise RuntimeError(f"model discovery failed: HTTP {result.status}")
    if override:
        return override
    preferred = [model for model in ids if any(name in model.lower() for name in ("codex", "gpt-5", "gpt-4", "o3"))]
    return (preferred or ids)[0]


def body_for(model: str, context: str, path: str, stops: Any = (STOP,)) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": f"CC003 cache fixture {path}.\n{context}"},
            {"role": "user", "content": "Reply exactly with hello<END>secret and no other text."},
        ],
    }
    if stops is not OMITTED:
        body["stop"] = stops
    return body


def run_path(client: Client, model: str, context: str, path: str, mode: str, upstream: str, repeats: int) -> dict[str, Any]:
    samples: list[dict[str, Any]] = []
    failures: list[str] = []
    for index in range(repeats):
        body = body_for(model, context, path)
        body["stream"] = mode == "sse"
        if mode == "sse":
            body["stream_options"] = {"include_usage": True}
        result = client.request("/v1/chat/completions", body, "text/event-stream" if mode == "sse" else "application/json")
        current = sample(result, mode, path, f"core-{index}", "hello")
        current["upstream_mode_expected"] = upstream
        current["upstream_mode_verified"] = False
        samples.append(current)
        if result.status != 200:
            failures.append(f"core-{index}: HTTP {result.status}")
        elif not current["stop_content_ok"] or current["stop_text_leaked"] or not current["finish_reason_stop"]:
            failures.append(f"core-{index}: stop assertion failed")
        if mode == "sse" and current["done_count"] != 1:
            failures.append(f"core-{index}: expected one [DONE]")
        if mode == "sse" and current["usage_count"] != 1:
            failures.append(f"core-{index}: expected one terminal usage chunk")
    return {
        "path": path,
        "client_mode": mode,
        "upstream_mode_expected": upstream,
        "upstream_mode_verified": False,
        "samples": samples,
        "metrics": summarize(samples),
        "failures": failures,
    }


def run_boundaries(client: Client, model: str, context: str, boundary_modes: tuple[str, ...]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for path, mode, upstream in PATHS:
        if mode not in boundary_modes:
            continue
        for name, text, stops, expected in BOUNDARY_CASES:
            body = body_for(model, context, f"{path}-{name}", stops)
            body["messages"][1]["content"] = f"Return this fixture exactly: {text}"
            body["stream"] = mode == "sse"
            if mode == "sse":
                body["stream_options"] = {"include_usage": True}
            result = client.request("/v1/chat/completions", body, "text/event-stream" if mode == "sse" else "application/json")
            stop_enabled = stops is not None and stops is not OMITTED
            item = sample(result, mode, path, name, expected, stop_enabled)
            item["boundary_assertions_ok"] = (
                result.status == 200
                and item["stop_content_ok"]
                and not item["stop_text_leaked"]
                and (not stop_enabled or item["finish_reason_stop"])
                and (mode != "sse" or (item["done_count"] == 1 and item["usage_count"] == 1))
            )
            item.update({"upstream_mode_expected": upstream, "upstream_mode_verified": False})
            results.append(item)
    return results


def run_invalid_stops(client: Client, model: str, context: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for name, stops in INVALID_STOP_CASES:
        body = body_for(model, context, f"invalid-{name}", stops)
        result = client.request("/v1/chat/completions", body)
        results.append({"case": name, "status": result.status, "expected_status": 400, "passed": result.status == 400})
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("SUB2API_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--api-key", default=os.environ.get("SUB2API_API_KEY", ""))
    parser.add_argument("--model", default=os.environ.get("SUB2API_MODEL"))
    parser.add_argument("--repeats", type=int, default=int(os.environ.get("SUB2API_CC003_REPEATS", "3")))
    parser.add_argument("--boundary", choices=("none", "all"), default=os.environ.get("SUB2API_CC003_BOUNDARY", "none"))
    parser.add_argument("--timeout", type=float, default=float(os.environ.get("SUB2API_TIMEOUT", str(DEFAULT_TIMEOUT))))
    parser.add_argument("--report", default=os.environ.get("SUB2API_CC003_REPORT", str(Path(__file__).with_name("report.json"))))
    parser.add_argument("--context-file", default=os.environ.get("SUB2API_CACHE_CONTEXT_FILE"))
    parser.add_argument("--verify-tls", action="store_true", default=os.environ.get("SUB2API_VERIFY_TLS") == "1")
    args = parser.parse_args(argv)
    if args.repeats < 1:
        parser.error("--repeats must be positive")
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
        context = reference_text(args.context_file)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"configuration failed: {error}", file=sys.stderr)
        return 1

    paths = [run_path(client, model, context, path, mode, upstream, args.repeats) for path, mode, upstream in PATHS]
    boundaries = run_boundaries(client, model, context, ("json", "sse")) if args.boundary == "all" else []
    invalid_stops = run_invalid_stops(client, model, context) if args.boundary == "all" else []
    report = {
        "test_case": "TC-CC-003-stop-four-paths",
        "base_url": args.base_url.rstrip("/"),
        "api_key": "configured",
        "model": model,
        "repeats_per_path": args.repeats,
        "boundary_mode": args.boundary,
        "reference_bytes": len(context.encode("utf-8")),
        "upstream_mode_note": "Expected labels are not verified by the public client response; use gateway/upstream logs or a fixture for this evidence.",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "duration_seconds": round(time.time() - started, 1),
        "paths": paths,
        "boundaries": boundaries,
        "invalid_stops": invalid_stops,
    }
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"model": model, "paths": len(paths), "boundaries": len(boundaries), "report": str(report_path)}, ensure_ascii=False))

    failures = [failure for path in paths for failure in path["failures"]]
    failures.extend(
        f"{item['path']}/{item['case']}: boundary assertion failed"
        for item in boundaries
        if not item["boundary_assertions_ok"]
    )
    failures.extend(item["case"] + ": expected HTTP 400" for item in invalid_stops if not item["passed"])
    missing_usage = any(path["metrics"]["valid_usage_samples"] < path["metrics"]["successful_requests"] for path in paths)
    if failures:
        print(f"FAILED: {len(failures)} stop/path assertions", file=sys.stderr)
        return 1
    if missing_usage:
        print("BLOCKED: successful responses did not all expose verifiable cached_tokens", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
