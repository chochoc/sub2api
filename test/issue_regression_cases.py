#!/usr/bin/env python3
"""Real deployment regression cases for the five reported OpenAI contract issues.

This runner intentionally reports observed cache metrics as N/A when the upstream
does not return cached_tokens. It does not invent a hit rate or save response
content. The API key is read only from SUB2API_API_KEY.
"""

from __future__ import annotations

import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
import uuid
from typing import Any


BASE_URL = os.environ.get("SUB2API_BASE_URL", "https://127.0.0.1:8443").rstrip("/")
API_KEY = os.environ.get("SUB2API_API_KEY", "")
REPORT = os.environ.get("SUB2API_ISSUE_REPORT", os.path.join(os.path.dirname(__file__), "issue-regression-report.json"))
MODEL_OVERRIDE = os.environ.get("SUB2API_MODEL", "")
CTX = ssl._create_unverified_context()


def request(path: str, payload: Any = None, accept: str = "application/json") -> dict[str, Any]:
    headers = {
        "Accept": accept,
        "User-Agent": "sub2api-issue-regression/1.0",
        "X-Client-Request-Id": str(uuid.uuid4()),
    }
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE_URL + path, data=data, headers=headers,
                                 method="POST" if data is not None else "GET")
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=120, context=CTX) as response:
            body = response.read()
            status = response.status
            response_headers = {k.lower(): v for k, v in response.headers.items()}
    except urllib.error.HTTPError as error:
        body = error.read()
        status = error.code
        response_headers = {k.lower(): v for k, v in error.headers.items()}
    return {
        "status": status,
        "headers": response_headers,
        "body": body,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
    }


def json_body(result: dict[str, Any]) -> dict[str, Any] | None:
    try:
        value = json.loads(result["body"].decode("utf-8", errors="replace"))
        return value if isinstance(value, dict) else None
    except (ValueError, UnicodeDecodeError):
        return None


def usage(result: dict[str, Any]) -> dict[str, Any] | None:
    payload = json_body(result)
    value = payload.get("usage") if payload else None
    return value if isinstance(value, dict) else None


def message_content(result: dict[str, Any]) -> str:
    payload = json_body(result)
    try:
        return str(payload["choices"][0]["message"].get("content") or "")
    except (AttributeError, IndexError, KeyError, TypeError):
        return ""


def finish_reason(result: dict[str, Any]) -> str | None:
    payload = json_body(result)
    try:
        return payload["choices"][0].get("finish_reason")
    except (AttributeError, IndexError, KeyError, TypeError):
        return None


def cache_fields(value: dict[str, Any] | None) -> tuple[int | None, int | None]:
    if not value:
        return None, None
    prompt = value.get("prompt_tokens")
    details = value.get("prompt_tokens_details")
    cached = details.get("cached_tokens") if isinstance(details, dict) else None
    return (prompt if isinstance(prompt, int) else None,
            cached if isinstance(cached, int) else None)


def summarize_cache(samples: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [s for s in samples if s["status"] == 200]
    usable = [s for s in successful if isinstance(s.get("prompt_tokens"), int)
              and isinstance(s.get("cached_tokens"), int)]
    prompt_total = sum(s["prompt_tokens"] for s in usable)
    cached_total = sum(s["cached_tokens"] for s in usable)
    return {
        "requests": len(samples),
        "successful_requests": len(successful),
        "usage_samples": sum(s.get("usage_seen", False) for s in successful),
        "cached_token_samples": len(usable),
        "request_hit_rate": (sum(s["cached_tokens"] > 0 for s in usable) / len(usable)
                              if usable else None),
        "token_hit_rate": (cached_total / prompt_total if prompt_total else None),
        "prompt_tokens_sum": prompt_total if usable else None,
        "cached_tokens_sum": cached_total if usable else None,
    }


def main() -> int:
    records: list[dict[str, Any]] = []
    failures = 0
    started = time.time()

    health = request("/health")
    if health["status"] != 200:
        raise SystemExit(f"health check failed: HTTP {health['status']}")
    models = request("/v1/models")
    model_list = []
    models_body = json_body(models)
    if models_body:
        model_list = [m.get("id") for m in models_body.get("data", [])
                      if isinstance(m, dict) and m.get("id")]
    model = MODEL_OVERRIDE or next((m for m in model_list if "codex" in m.lower()), None)
    model = model or (model_list[0] if model_list else None)
    if models["status"] != 200 or not model:
        raise SystemExit(f"model discovery failed: HTTP {models['status']}")

    def add(case: str, result: dict[str, Any], expected: str, passed: bool, **extra: Any) -> None:
        nonlocal failures
        if not passed:
            failures += 1
        records.append({"case": case, "status": result["status"],
                        "elapsed_ms": result["elapsed_ms"], "content_type": result["headers"].get("content-type", ""),
                        "expected": expected, "outcome": "pass" if passed else "fail", **extra})

    # C1: one initial request followed by ten appended turns with the same prefix.
    conversation = [{"role": "system", "content": "You are a concise cache regression assistant."},
                    {"role": "user", "content": "Start the cache regression session. Reply OK."}]
    multi_samples: list[dict[str, Any]] = []
    for turn in range(11):
        result = request("/v1/chat/completions", {"model": model, "messages": conversation,
                         "stream": False})
        prompt, cached = cache_fields(usage(result))
        sample = {"turn": turn, "status": result["status"], "usage_seen": usage(result) is not None,
                  "prompt_tokens": prompt, "cached_tokens": cached}
        multi_samples.append(sample)
        if result["status"] == 200:
            conversation.append({"role": "assistant", "content": message_content(result) or "OK"})
            conversation.append({"role": "user", "content": f"Continue cache turn {turn + 1}; reply OK."})
    add("C1-multi-turn-cache", {"status": 200, "headers": {}, "elapsed_ms": 0},
        "1 initial + 10 appended turns; report real cached_tokens",
        all(s["status"] == 200 for s in multi_samples), metrics=summarize_cache(multi_samples), samples=multi_samples)

    # C2: one warm-up followed by twenty identical requests.
    repeated_samples: list[dict[str, Any]] = []
    repeat_body = {"model": model, "messages": [{"role": "system", "content": "Stable repeated cache prefix."},
                   {"role": "user", "content": "Reply with OK for the repeated cache test."}],
                   "stream": False}
    for index in range(21):
        result = request("/v1/chat/completions", repeat_body)
        prompt, cached = cache_fields(usage(result))
        repeated_samples.append({"request": index, "status": result["status"], "usage_seen": usage(result) is not None,
                                 "prompt_tokens": prompt, "cached_tokens": cached})
    add("C2-repeated-cache", {"status": 200, "headers": {}, "elapsed_ms": 0},
        "1 warm-up + 20 identical requests; report real cached_tokens",
        all(s["status"] == 200 for s in repeated_samples), metrics=summarize_cache(repeated_samples), samples=repeated_samples)

    # S1: multiple stop spellings and streaming behavior.
    stop_cases = [
        ("S1-string", "<STOP_STRING>", "<STOP_STRING>"),
        ("S1-array", ["<STOP_ARRAY>", "<SECOND>"], "<STOP_ARRAY>"),
        ("S1-first-character", ["X"], "X"),
    ]
    for case, stop, marker in stop_cases:
        result = request("/v1/chat/completions", {"model": model, "messages": [{"role": "user", "content":
            f"Write alpha, then {marker}, then omega."}], "stop": stop, "stream": False})
        content = message_content(result)
        add(case, result, "2xx and response content excludes the earliest stop string",
            result["status"] == 200 and marker not in content,
            finish_reason=finish_reason(result), marker_present=marker in content)
    stream_marker = "<STOP_STREAM>"
    stream_result = request("/v1/chat/completions", {"model": model, "messages": [{"role": "user", "content":
        f"Write alpha, then {stream_marker}, then omega."}], "stop": stream_marker, "stream": True},
        accept="text/event-stream")
    stream_text = stream_result["body"].decode("utf-8", errors="replace")
    add("S1-sse", stream_result, "2xx SSE without stop string and exactly one [DONE]",
        stream_result["status"] == 200 and stream_marker not in stream_text and stream_text.count("data: [DONE]") == 1,
        marker_present=stream_marker in stream_text, done_count=stream_text.count("data: [DONE]"))

    # T1: three tool_choice values, each as an independent request.
    tool = {"type": "function", "function": {"name": "get_weather", "description": "Get weather",
            "parameters": {"type": "object", "properties": {"city": {"type": "string"}},
                            "required": ["city"], "additionalProperties": False}}}
    for choice in ("none", "auto", "required"):
        result = request("/v1/chat/completions", {"model": model, "messages": [{"role": "user", "content":
            "What is the weather in Paris?"}], "tools": [tool], "tool_choice": choice,
            "stream": False})
        payload = json_body(result) or {}
        try:
            calls = payload["choices"][0]["message"].get("tool_calls") or []
        except (AttributeError, IndexError, KeyError, TypeError):
            calls = []
        valid = result["status"] == 200 and (choice != "none" or not calls) and (choice != "required" or bool(calls))
        add(f"T1-tool-choice-{choice}", result, "HTTP 2xx; none/auto/required semantics preserved", valid,
            tool_call_count=len(calls))

    # L1: force a long answer with max_completion_tokens=1 and inspect finish_reason.
    result = request("/v1/chat/completions", {"model": model, "messages": [{"role": "user", "content":
        "Write a 200-word explanation of why the sky is blue. Do not stop early."}],
        "max_completion_tokens": 1, "stream": False})
    reason = finish_reason(result)
    add("L1-max-completion-tokens", result, "HTTP 2xx and finish_reason=length",
        result["status"] == 200 and reason == "length", finish_reason=reason,
        usage=usage(result))

    report = {"base_url": BASE_URL, "model": model, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "duration_seconds": round(time.time() - started, 1), "records": records,
              "summary": {"cases": len(records), "failed": failures}}
    os.makedirs(os.path.dirname(REPORT) or ".", exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps(report["summary"], ensure_ascii=False))
    print(f"Report: {REPORT}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
