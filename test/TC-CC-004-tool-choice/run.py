#!/usr/bin/env python3
"""Black-box CC004 tool-choice and prompt-cache test for Sub2API."""

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
from typing import Any


DEFAULT_BASE_URL = "https://127.0.0.1:8443"
DEFAULT_TIMEOUT = 120.0
DEFAULT_REPEATS = 3

TOOL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "lookup_city",
        "description": "Look up a city and return its country.",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
            "additionalProperties": False,
        },
    },
}

MATRIX = (
    ("BASE", None, "base", 0),
    ("NONE", "none", "none", 0),
    ("AUTO-TEXT", "auto", "auto-text", 0),
    ("AUTO-TOOL", "auto", "auto-tool", 1),
    ("REQ", "required", "required", 1),
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
            "User-Agent": "sub2api-cc004-tool-choice-cache-test/1.0",
            "X-Client-Request-Id": str(uuid.uuid4()),
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
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
                return HttpResult(response.status, {k.lower(): v for k, v in response.headers.items()}, response.read(), int((time.monotonic() - started) * 1000))
        except urllib.error.HTTPError as error:
            return HttpResult(error.code, {k.lower(): v for k, v in error.headers.items()}, error.read(), int((time.monotonic() - started) * 1000))
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            return HttpResult(0, {}, str(error).encode("utf-8", errors="replace"), int((time.monotonic() - started) * 1000))


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
    if isinstance(details, dict) and isinstance(details.get("cached_tokens"), int) and not isinstance(details.get("cached_tokens"), bool):
        return prompt, details["cached_tokens"], "prompt_tokens_details.cached_tokens"
    cached = usage.get("cached_tokens")
    if isinstance(cached, int) and not isinstance(cached, bool):
        return prompt, cached, "cached_tokens"
    return prompt, None, None


def parse_json(result: HttpResult) -> dict[str, Any]:
    payload = json_object(result.body) or {}
    choices = payload.get("choices")
    choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    calls = message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else []
    return {
        "content": message.get("content") if isinstance(message.get("content"), str) else "",
        "calls": calls,
        "reasons": [choice["finish_reason"]] if isinstance(choice.get("finish_reason"), str) else [],
        "usage": payload.get("usage") if isinstance(payload.get("usage"), dict) else None,
        "usage_count": 1 if isinstance(payload.get("usage"), dict) else 0,
        "done_count": None,
    }


def parse_sse(result: HttpResult) -> dict[str, Any]:
    content: list[str] = []
    reasons: list[str] = []
    calls: dict[int, dict[str, Any]] = {}
    id_frame_counts: dict[int, int] = {}
    id_values: dict[int, str] = {}
    name_values: dict[int, str] = {}
    identity_conflicts: list[int] = []
    usage: dict[str, Any] | None = None
    usage_count = 0
    done_count = 0
    for frame in result.text.replace("\r\n", "\n").split("\n\n"):
        lines = [line[5:].lstrip() for line in frame.split("\n") if line.startswith("data:")]
        if not lines:
            continue
        data = "\n".join(lines)
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
            delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
            if isinstance(delta.get("content"), str):
                content.append(delta["content"])
            if isinstance(choice.get("finish_reason"), str):
                reasons.append(choice["finish_reason"])
            for raw_call in delta.get("tool_calls", []):
                if not isinstance(raw_call, dict):
                    continue
                index = raw_call.get("index", 0)
                if not isinstance(index, int):
                    continue
                call = calls.setdefault(index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                if isinstance(raw_call.get("id"), str) and raw_call["id"]:
                    id_frame_counts[index] = id_frame_counts.get(index, 0) + 1
                    if index in id_values and id_values[index] != raw_call["id"] and index not in identity_conflicts:
                        identity_conflicts.append(index)
                    id_values[index] = raw_call["id"]
                    call["id"] = raw_call["id"]
                function = raw_call.get("function") if isinstance(raw_call.get("function"), dict) else {}
                if isinstance(function.get("name"), str) and function["name"]:
                    if index in name_values and name_values[index] != function["name"] and index not in identity_conflicts:
                        identity_conflicts.append(index)
                    name_values[index] = function["name"]
                    call["function"]["name"] = function["name"]
                if isinstance(function.get("arguments"), str):
                    call["function"]["arguments"] += function["arguments"]
    return {"content": "".join(content), "calls": [calls[i] for i in sorted(calls)], "reasons": reasons, "usage": usage, "usage_count": usage_count, "done_count": done_count, "id_frame_counts": id_frame_counts, "identity_conflicts": identity_conflicts}


def parsed(result: HttpResult, mode: str) -> dict[str, Any]:
    return parse_sse(result) if mode == "sse" else parse_json(result)


def valid_calls(calls: list[Any], expected_name: str = "lookup_city") -> bool:
    if not calls:
        return False
    ids: list[str] = []
    for call in calls:
        if not isinstance(call, dict) or not isinstance(call.get("id"), str) or not call["id"]:
            return False
        function = call.get("function")
        if not isinstance(function, dict) or function.get("name") != expected_name or not isinstance(function.get("arguments"), str):
            return False
        try:
            arguments = json.loads(function["arguments"])
        except (ValueError, TypeError):
            return False
        if not isinstance(arguments, dict) or not isinstance(arguments.get("city"), str):
            return False
        ids.append(call["id"])
    return len(ids) == len(set(ids))


def summarize(samples: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [item for item in samples if item["status"] == 200]
    valid = [item for item in successful if item.get("valid_usage")]
    warm_valid = [item for item in samples[1:] if item["status"] == 200 and item.get("valid_usage")]

    def metric(window: list[dict[str, Any]]) -> dict[str, Any]:
        prompt = sum(item["prompt_tokens"] for item in window)
        cached = sum(item["cached_tokens"] for item in window)
        return {
            "requests": len(window),
            "request_hit_rate": sum(item["cached_tokens"] > 0 for item in window) / len(window) if window else None,
            "token_hit_rate": cached / prompt if prompt else None,
            "prompt_tokens_sum": prompt if window else None,
            "cached_tokens_sum": cached if window else None,
        }

    all_window = metric(valid)
    return {
        "requests": len(samples),
        "successful_requests": len(successful),
        "valid_usage_samples": len(valid),
        "invalid_or_missing_usage": len(successful) - len(valid),
        "usage_coverage": len(valid) / len(successful) if successful else None,
        "request_hit_rate": all_window["request_hit_rate"],
        "token_hit_rate": all_window["token_hit_rate"],
        "prompt_tokens_sum": all_window["prompt_tokens_sum"],
        "cached_tokens_sum": all_window["cached_tokens_sum"],
        "all_window": all_window,
        "warm_window": metric(warm_valid),
    }


def reference_text(path: str | None) -> str:
    if path:
        value = Path(path).read_text(encoding="utf-8")
        if not value.strip():
            raise ValueError("--context-file is empty")
        return value
    return "\n\n".join(f"Stable CC004 cache section {index:02d}. Preserve the exact input prefix for usage measurement." for index in range(1, 65))


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


def request_body(model: str, context: str, run_name: str, choice: str | None, scenario: str, strict: bool, stream: bool) -> dict[str, Any]:
    if scenario == "auto-tool" or scenario == "required":
        prompt = "Use lookup_city to look up Paris. You must obtain the city data by calling the function."
    elif scenario == "auto-text":
        prompt = "Reply with the single word Paris. Do not call any tool."
    elif scenario == "none":
        prompt = "Reply with the single word Paris and do not call a tool."
    else:
        prompt = "Reply with the single word Paris."
    tool = json.loads(json.dumps(TOOL_SCHEMA))
    if strict:
        tool["function"]["strict"] = True
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "system", "content": f"CC004 stable cache fixture {run_name}.\n{context}"}, {"role": "user", "content": prompt}],
        "stream": stream,
        "temperature": 0,
    }
    if choice is not None:
        body["tools"] = [tool]
        body["tool_choice"] = choice
        body["parallel_tool_calls"] = False
    if stream:
        body["stream_options"] = {"include_usage": True}
    return body


def sample(result: HttpResult, mode: str, choice: str | None, expected_calls: int) -> dict[str, Any]:
    data = parsed(result, mode)
    prompt, cached, cached_field = cache_fields(data["usage"])
    valid_usage = result.status == 200 and isinstance(prompt, int) and prompt >= 0 and isinstance(cached, int) and 0 <= cached <= prompt
    calls = data["calls"]
    semantic_ok = (len(calls) == 0 if expected_calls == 0 else valid_calls(calls))
    if choice == "required":
        semantic_ok = semantic_ok and data["reasons"] == ["tool_calls"]
    if mode == "sse":
        identity_ok = not data["identity_conflicts"] and all(count == 1 for count in data["id_frame_counts"].values())
        semantic_ok = semantic_ok and data["done_count"] == 1 and data["usage_count"] == 1 and identity_ok
    return {
        "status": result.status,
        "elapsed_ms": result.elapsed_ms,
        "content_type": result.headers.get("content-type", ""),
        "finish_reasons": data["reasons"],
        "tool_call_count": len(calls),
        "tool_calls_valid": valid_calls(calls) if calls else expected_calls == 0,
        "tool_call_ids": [call.get("id") for call in calls if isinstance(call, dict) and isinstance(call.get("id"), str)],
        "tool_call_names": [call.get("function", {}).get("name") for call in calls if isinstance(call, dict) and isinstance(call.get("function"), dict)],
        "semantic_ok": result.status == 200 and semantic_ok,
        "done_count": data["done_count"],
        "usage_count": data["usage_count"],
        "tool_identity_ok": not data.get("identity_conflicts") and all(count == 1 for count in data.get("id_frame_counts", {}).values()),
        "usage_seen": data["usage"] is not None,
        "prompt_tokens": prompt,
        "cached_tokens": cached,
        "cached_tokens_field": cached_field,
        "valid_usage": valid_usage,
    }


def run_case(client: Client, model: str, context: str, name: str, choice: str | None, scenario: str, mode: str, repeats: int, strict: bool) -> dict[str, Any]:
    samples: list[dict[str, Any]] = []
    failures: list[str] = []
    last_calls: list[Any] = []
    expected_calls = 1 if scenario in ("auto-tool", "required") else 0
    for index in range(repeats):
        body = request_body(model, context, f"{name}-{mode}", choice, scenario, strict, mode == "sse")
        result = client.request("/v1/chat/completions", body, "text/event-stream" if mode == "sse" else "application/json")
        parsed_result = parsed(result, mode)
        last_calls = parsed_result["calls"]
        item = sample(result, mode, choice, expected_calls)
        item["request_index"] = index
        samples.append(item)
        if result.status != 200:
            failures.append(f"request-{index}: HTTP {result.status}")
        elif not item["semantic_ok"]:
            failures.append(f"request-{index}: tool-choice or terminal assertion failed")
    follow_up: dict[str, Any] | None = None
    if expected_calls and samples and samples[-1]["semantic_ok"]:
        # Send the observed call IDs back as a second turn without putting tool
        # arguments or response text in the report.
        body = request_body(model, context, f"{name}-{mode}", choice, scenario, strict, mode == "sse")
        observed = last_calls
        assistant = {"role": "assistant", "content": None, "tool_calls": observed}
        follow_messages = body["messages"] + [assistant] + [{"role": "tool", "tool_call_id": call["id"], "content": '{"city":"Paris","country":"France"}'} for call in observed if isinstance(call, dict) and call.get("id")]
        follow_body = dict(body)
        follow_body["messages"] = follow_messages
        follow_body["tool_choice"] = "auto"
        follow_result = client.request("/v1/chat/completions", follow_body, "text/event-stream" if mode == "sse" else "application/json")
        follow_up = {"status": follow_result.status, "returned_call_ids": [call.get("id") for call in observed if isinstance(call, dict)], "semantic_ok": follow_result.status == 200}
        if follow_result.status != 200:
            failures.append(f"follow-up: HTTP {follow_result.status}")
    return {"run_id": f"CC004-{name}-{'S' if mode == 'sse' else 'J'}", "choice": choice or "omitted", "scenario": scenario, "client_mode": mode, "strict_schema": strict, "repeats": repeats, "samples": samples, "metrics": summarize(samples), "follow_up": follow_up, "failures": failures}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("SUB2API_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--api-key", default=os.environ.get("SUB2API_API_KEY", ""))
    parser.add_argument("--model", default=os.environ.get("SUB2API_MODEL"))
    parser.add_argument("--repeats", type=int, default=int(os.environ.get("SUB2API_CC004_REPEATS", str(DEFAULT_REPEATS))))
    parser.add_argument("--mode", choices=("json", "sse", "both"), default=os.environ.get("SUB2API_CC004_MODE", "both"))
    parser.add_argument("--context-file", default=os.environ.get("SUB2API_CACHE_CONTEXT_FILE"))
    parser.add_argument("--timeout", type=float, default=float(os.environ.get("SUB2API_TIMEOUT", str(DEFAULT_TIMEOUT))))
    parser.add_argument("--strict", action="store_true", default=os.environ.get("SUB2API_CC004_STRICT") == "1")
    parser.add_argument("--verify-tls", action="store_true", default=os.environ.get("SUB2API_VERIFY_TLS") == "1")
    parser.add_argument("--report", default=os.environ.get("SUB2API_CC004_REPORT", str(Path(__file__).with_name("report.json"))))
    args = parser.parse_args(argv)
    if args.repeats < 2:
        parser.error("--repeats must be at least 2")
    if not args.api_key:
        print("BLOCKED: SUB2API_API_KEY is not set", file=sys.stderr)
        return 2
    client = Client(args.base_url, args.api_key, args.timeout, args.verify_tls)
    if client.request("/health").status != 200:
        print("deployment health check failed", file=sys.stderr)
        return 1
    try:
        model = discover_model(client, args.model)
        context = reference_text(args.context_file)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"configuration failed: {error}", file=sys.stderr)
        return 1
    modes = ("json", "sse") if args.mode == "both" else (args.mode,)
    started = time.time()
    runs = [run_case(client, model, context, name, choice, scenario, mode, args.repeats, args.strict) for mode in modes for name, choice, scenario, _ in MATRIX]
    report = {
        "test_case": "TC-CC-004-tool-choice",
        "base_url": args.base_url.rstrip("/"),
        "api_key": "configured",
        "model": model,
        "strict_schema": args.strict,
        "reference_bytes": len(context.encode("utf-8")),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "duration_seconds": round(time.time() - started, 1),
        "upstream_evidence_note": "Public Sub2API responses do not prove upstream transport, account affinity or billing; correlate request IDs with gateway/upstream logs for that claim.",
        "runs": runs,
    }
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    failures = [f"{run['run_id']}: {failure}" for run in runs for failure in run["failures"]]
    missing_usage = any(run["metrics"]["valid_usage_samples"] < run["metrics"]["successful_requests"] for run in runs)
    print(json.dumps({"model": model, "runs": len(runs), "failures": len(failures), "report": str(report_path)}, ensure_ascii=False))
    if failures:
        print(f"FAILED: {len(failures)} tool-choice assertions", file=sys.stderr)
        return 1
    if missing_usage:
        print("BLOCKED: successful responses did not all expose verifiable cached_tokens", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
