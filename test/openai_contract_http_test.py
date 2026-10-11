#!/usr/bin/env python3
"""Black-box tests for the deployed Sub2API OpenAI-compatible contract.

The test intentionally uses only Python's standard library.  It never writes an
API key to a report.  A deployment with no usable balance is reported as
BLOCKED and contract cases that would spend upstream quota are skipped.

Usage:
  SUB2API_API_KEY=... python3 test/openai_contract_http_test.py
  python3 test/openai_contract_http_test.py --base-url https://127.0.0.1:8443 \
      --api-key "$SUB2API_API_KEY" --report test/openai-contract-report.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import sys
import time
import unittest
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any


INSUFFICIENT_BALANCE = "INSUFFICIENT_BALANCE"


def _redact(value: str) -> str:
    return re.sub(r"sk-[A-Za-z0-9_-]+", "sk-<redacted>", value)


@dataclass
class HttpResult:
    status: int
    headers: dict[str, str]
    body: bytes
    elapsed_ms: int

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.text)


class ContractClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 90.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.ssl_context = ssl._create_unverified_context()

    def request(self, path: str, payload: Any = None, auth: bool = True,
                accept: str = "application/json") -> HttpResult:
        headers = {
            "Accept": accept,
            "User-Agent": "sub2api-openai-contract-test/1.0",
            "X-Client-Request-Id": str(uuid.uuid4()),
        }
        if auth and self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base_url + path, data=data,
                                         headers=headers, method="POST" if data else "GET")
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout,
                                        context=self.ssl_context) as response:
                body = response.read()
                return HttpResult(response.status,
                                  {k.lower(): v for k, v in response.headers.items()},
                                  body, int((time.monotonic() - started) * 1000))
        except urllib.error.HTTPError as error:
            body = error.read()
            return HttpResult(error.code,
                              {k.lower(): v for k, v in error.headers.items()},
                              body, int((time.monotonic() - started) * 1000))


class ContractTest(unittest.TestCase):
    client: ContractClient
    report_path: str
    records: list[dict[str, Any]]
    model: str | None = None
    balance_blocked = False
    balance_reason = ""
    expected_policy = "legacy"
    expected_stop_mode = "reject"
    expected_max_mode = "auto"

    @classmethod
    def setUpClass(cls) -> None:
        cls.records = []
        cls.base_url = os.environ.get("SUB2API_BASE_URL", "https://127.0.0.1:8443")
        cls.api_key = os.environ.get("SUB2API_API_KEY", "")
        cls.report_path = os.environ.get(
            "SUB2API_REPORT", os.path.join(os.path.dirname(__file__), "openai-contract-report.json")
        )
        cls.expected_policy = os.environ.get("SUB2API_EXPECT_POLICY", "legacy").strip().lower()
        cls.expected_stop_mode = os.environ.get("SUB2API_EXPECT_STOP_MODE", "reject").strip().lower()
        cls.expected_max_mode = os.environ.get("SUB2API_EXPECT_MAX", "auto").strip().lower()
        if cls.expected_policy not in {"legacy", "strict"}:
            raise RuntimeError("SUB2API_EXPECT_POLICY must be legacy or strict")
        if cls.expected_stop_mode not in {"reject", "text"}:
            raise RuntimeError("SUB2API_EXPECT_STOP_MODE must be reject or text")
        if cls.expected_max_mode not in {"auto", "accept", "reject"}:
            raise RuntimeError("SUB2API_EXPECT_MAX must be auto, accept or reject")
        cls.client = ContractClient(cls.base_url, cls.api_key)
        health = cls.client.request("/health", auth=False)
        cls._record("health", health, expected="200", outcome="pass" if health.status == 200 else "fail")
        if health.status != 200:
            raise RuntimeError(f"deployment health check failed: HTTP {health.status} {_redact(health.text[:300])}")

        if not cls.api_key:
            cls.balance_blocked = True
            cls.balance_reason = "SUB2API_API_KEY is not set"
            return

        models = cls.client.request("/v1/models")
        if models.status == 403 and INSUFFICIENT_BALANCE in models.text:
            cls.balance_blocked = True
            cls.balance_reason = "API key rejected by quota gate: INSUFFICIENT_BALANCE"
            cls._record("models", models, expected="200 with data[]", outcome="blocked",
                        error=cls.balance_reason)
        elif models.status == 200:
            try:
                data = models.json().get("data", [])
                ids = [item.get("id") for item in data if isinstance(item, dict) and item.get("id")]
                preferred = [m for m in ids if any(x in m.lower() for x in ("gpt-5", "gpt-4", "o3", "codex"))]
                cls.model = os.environ.get("SUB2API_MODEL") or (preferred + ids)[0] if (preferred + ids) else None
                cls._record("models", models, expected="200 with data[]", outcome="pass" if cls.model else "fail",
                            model=cls.model, model_count=len(ids))
            except (ValueError, AttributeError, IndexError) as exc:
                cls._record("models", models, expected="valid JSON model list", outcome="fail", error=str(exc))
        else:
            cls._record("models", models, expected="200", outcome="fail",
                        error=_redact(models.text[:300]))

    @classmethod
    def tearDownClass(cls) -> None:
        report = {
            "base_url": cls.base_url,
            "api_key": "configured" if cls.api_key else "missing",
            "model": cls.model,
            "expected_policy": cls.expected_policy,
            "expected_stop_mode": cls.expected_stop_mode,
            "expected_max_mode": cls.expected_max_mode,
            "blocked": cls.balance_blocked,
            "blocked_reason": cls.balance_reason,
            "records": cls.records,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        os.makedirs(os.path.dirname(cls.report_path) or ".", exist_ok=True)
        with open(cls.report_path, "w", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        print(f"\nReport: {cls.report_path}")
        if cls.balance_blocked:
            print(f"BLOCKED: {cls.balance_reason}")

    @classmethod
    def _record(cls, case: str, result: HttpResult | None = None,
                expected: str = "", outcome: str = "", **extra: Any) -> None:
        record: dict[str, Any] = {"case": case, "expected": expected, "outcome": outcome}
        if result is not None:
            record.update({"http_status": result.status, "elapsed_ms": result.elapsed_ms,
                           "content_type": result.headers.get("content-type", "")})
        record.update(extra)
        cls.records.append(record)

    def require_live_model(self) -> str:
        if self.__class__.balance_blocked:
            self.skipTest(self.__class__.balance_reason)
        if not self.__class__.model:
            self.skipTest("/v1/models returned no usable model")
        return self.__class__.model

    def max_is_rejected(self) -> bool:
        if self.expected_max_mode == "reject":
            return True
        if self.expected_max_mode == "accept" or self.expected_policy != "strict":
            return False
        return "codex" in (self.__class__.model or "").lower()

    def max_body(self, value: int) -> dict[str, int]:
        return {} if self.max_is_rejected() else {"max_completion_tokens": value}

    def post_chat(self, body: dict[str, Any]) -> HttpResult:
        result = self.client.request("/v1/chat/completions", body,
                                     accept="text/event-stream" if body.get("stream") else "application/json")
        return result

    def post_chat_path(self, path: str, body: dict[str, Any]) -> HttpResult:
        return self.client.request(path, body,
                                   accept="text/event-stream" if body.get("stream") else "application/json")

    def test_auth_missing_key_is_rejected(self) -> None:
        result = ContractClient(self.client.base_url, "").request("/v1/models", auth=False)
        self._record("auth-missing", result, expected="401 API_KEY_REQUIRED",
                     outcome="pass" if result.status == 401 and "API_KEY_REQUIRED" in result.text else "fail")
        self.assertEqual(result.status, 401)
        self.assertIn("API_KEY_REQUIRED", result.text)

    def test_auth_invalid_key_is_rejected(self) -> None:
        result = ContractClient(self.client.base_url, "invalid-test-key").request("/v1/models")
        self._record("auth-invalid", result, expected="401 INVALID_API_KEY",
                     outcome="pass" if result.status == 401 and "INVALID_API_KEY" in result.text else "fail")
        self.assertEqual(result.status, 401)
        self.assertIn("INVALID_API_KEY", result.text)

    def test_stop_json(self) -> None:
        model = self.require_live_model()
        marker = "<SUB2API_STOP>"
        result = self.post_chat({"model": model, "messages": [
            {"role": "user", "content": f"Reply with the word alpha followed by {marker} and then omega."}],
            "stop": [marker], "stream": False, **self.max_body(32)})
        content = ""
        finish = None
        if result.status == 200:
            payload = result.json()
            choice = payload.get("choices", [{}])[0]
            content = ((choice.get("message") or {}).get("content") or "")
            finish = choice.get("finish_reason")
        if self.expected_policy == "legacy":
            valid = result.status == 200
            expected = "legacy: 200; marker behavior observed"
        elif self.expected_stop_mode == "text":
            valid = result.status == 200 and marker not in content
            expected = "strict/text: 200; content excludes stop marker"
        else:
            valid = result.status == 400
            expected = "strict/reject: 400 unsupported stop"
        outcome = "pass" if valid else "fail"
        self._record("S-01-stop-json", result, expected=expected,
                     outcome=outcome, finish_reason=finish, marker_present=marker in content,
                     policy=self.expected_policy, stop_mode=self.expected_stop_mode)
        self.assertTrue(valid, result.text[:500])

    def test_stop_sse(self) -> None:
        model = self.require_live_model()
        marker = "<SUB2API_SSE_STOP>"
        result = self.post_chat({"model": model, "messages": [
            {"role": "user", "content": f"Write alpha, then {marker}, then omega."}],
            "stop": marker, "stream": True, **self.max_body(32)})
        text = result.text
        if self.expected_policy == "legacy":
            valid = result.status == 200
            expected = "legacy: 200; marker behavior observed"
        elif self.expected_stop_mode == "text":
            valid = result.status == 200 and marker not in text
            expected = "strict/text: 200 SSE; no stop marker in deltas"
        else:
            valid = result.status == 400
            expected = "strict/reject: 400 unsupported stop"
        self._record("S-01-stop-sse", result, expected=expected,
                     outcome="pass" if valid else "fail",
                     marker_present=marker in text, done_count=text.count("data: [DONE]"),
                     policy=self.expected_policy, stop_mode=self.expected_stop_mode)
        self.assertTrue(valid, text[:500])

    def test_stop_json_array(self) -> None:
        """The array spelling is part of the OpenAI stop contract."""
        model = self.require_live_model()
        marker = "<SUB2API_ARRAY_STOP>"
        result = self.post_chat({"model": model, "messages": [
            {"role": "user", "content": f"Reply alpha, then {marker}, then omega."}],
            "stop": [marker], "stream": False, **self.max_body(32)})
        content = ""
        finish = None
        if result.status == 200:
            payload = result.json()
            choice = payload.get("choices", [{}])[0]
            content = ((choice.get("message") or {}).get("content") or "")
            finish = choice.get("finish_reason")
        if self.expected_policy == "legacy":
            valid = result.status == 200
            expected = "legacy: 200; marker behavior observed"
        elif self.expected_stop_mode == "text":
            valid = result.status == 200 and marker not in content
            expected = "strict/text: 200; array stop marker excluded"
        else:
            valid = result.status == 400
            expected = "strict/reject: 400 unsupported stop"
        outcome = "pass" if valid else "fail"
        self._record("S-01-stop-json-array", result,
                     expected=expected,
                     outcome=outcome, finish_reason=finish,
                     marker_present=marker in content, policy=self.expected_policy,
                     stop_mode=self.expected_stop_mode)
        self.assertTrue(valid, result.text[:500])

    def test_chat_completions_alias(self) -> None:
        """The plan explicitly promises the unversioned alias."""
        model = self.require_live_model()
        result = self.post_chat_path("/chat/completions", {
            "model": model,
            "messages": [{"role": "user", "content": "Reply exactly alias-ok."}],
            **self.max_body(8),
            "stream": False,
        })
        content_type = result.headers.get("content-type", "")
        valid = result.status == 200 and "json" in content_type.lower()
        self._record("R-01-chat-completions-alias", result,
                     expected="200 JSON Chat Completions response",
                     outcome="pass" if valid else "fail",
                     json_content_type="json" in content_type.lower())
        self.assertTrue(valid, result.text[:500])
        if valid:
            payload = result.json()
            self.assertIsInstance(payload.get("choices"), list)

    def test_usage_shape(self) -> None:
        model = self.require_live_model()
        result = self.post_chat({
            "model": model,
            "messages": [{"role": "user", "content": "Reply with one short word."}],
            **self.max_body(8),
            "stream": False,
        })
        valid = False
        usage = None
        if result.status == 200:
            usage = result.json().get("usage")
            valid = isinstance(usage, dict) and all(
                isinstance(usage.get(field), int) for field in ("prompt_tokens", "completion_tokens", "total_tokens")
            )
            if valid:
                valid = usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]
        self._record("C-03-usage-shape", result,
                     expected="200; integer prompt/completion/total usage with additive total",
                     outcome="pass" if valid else "fail", usage=usage if isinstance(usage, dict) else None)
        self.assertEqual(result.status, 200, result.text[:500])
        self.assertTrue(valid, result.text[:500])

    def test_max_completion_tokens_is_accepted(self) -> None:
        model = self.require_live_model()
        result = self.post_chat({"model": model, "messages": [{"role": "user", "content": "Reply briefly: alpha."}],
                                 "max_completion_tokens": 1, "stream": False})
        if self.max_is_rejected():
            valid = result.status == 400 and "unsupported_parameter" in result.text and "max_completion_tokens" in result.text
            expected = "strict/Codex: 400 unsupported max_completion_tokens"
        else:
            valid = result.status == 200
            expected = "200; explicit value accepted"
        outcome = "pass" if valid else "fail"
        finish = None
        if result.status == 200:
            finish = result.json().get("choices", [{}])[0].get("finish_reason")
        self._record("L-01-max-completion-tokens-1", result, expected=expected,
                     outcome=outcome, finish_reason=finish, max_mode="reject" if self.max_is_rejected() else "accept")
        self.assertTrue(valid, result.text[:500])

    def test_max_completion_tokens_boundaries(self) -> None:
        model = self.require_live_model()
        for limit in (1, 16, 127, 128):
            with self.subTest(max_completion_tokens=limit):
                result = self.post_chat({
                    "model": model,
                    "messages": [{"role": "user", "content": "Reply exactly OK."}],
                    "max_completion_tokens": limit,
                    "stream": False,
                })
                finish = None
                if result.status == 200:
                    finish = result.json().get("choices", [{}])[0].get("finish_reason")
                if self.max_is_rejected():
                    valid = result.status == 400 and "unsupported_parameter" in result.text and "max_completion_tokens" in result.text
                    expected = "strict/Codex: 400 unsupported max_completion_tokens"
                else:
                    valid = result.status == 200
                    expected = "2xx; explicit boundary accepted"
                self._record(f"L-01-max-completion-tokens-{limit}", result,
                             expected=expected, outcome="pass" if valid else "fail",
                             finish_reason=finish, max_mode="reject" if self.max_is_rejected() else "accept")
                self.assertTrue(valid, result.text[:500])

    def test_invalid_contract_parameters_rejected(self) -> None:
        """Strict mode must reject invalid stop/max before an upstream call."""
        model = self.require_live_model()
        cases = (
            ("S-04-stop-empty", {"stop": ""}, "stop"),
            ("S-04-stop-null-item", {"stop": [None]}, "stop"),
            ("L-01-max-zero", {"max_completion_tokens": 0}, "max_completion_tokens"),
            ("L-01-max-negative", {"max_completion_tokens": -1}, "max_completion_tokens"),
        )
        for case, extra, param in cases:
            with self.subTest(case=case):
                body = {
                    "model": model,
                    "messages": [{"role": "user", "content": "Reply with one word."}],
                    "stream": False,
                }
                body.update(extra)
                result = self.post_chat(body)
                text = result.text.lower()
                if self.expected_policy == "legacy":
                    valid = result.status == 200
                    expected = "legacy: request accepted; strict validation not active"
                else:
                    valid = result.status == 400 and param in text
                    expected = f"strict: 400 invalid_parameter with param={param}"
                self._record(case, result,
                             expected=expected,
                             outcome="pass" if valid else "fail",
                             error_param_present=param in text, policy=self.expected_policy)
                self.assertTrue(valid, result.text[:500])

    def test_tools_none_auto_required(self) -> None:
        model = self.require_live_model()
        tool = {"type": "function", "function": {"name": "get_weather", "description": "Get weather",
                "parameters": {"type": "object", "properties": {"city": {"type": "string"}},
                                "required": ["city"], "additionalProperties": False}}}
        for choice in ("none", "auto", "required"):
            with self.subTest(tool_choice=choice):
                result = self.post_chat({"model": model, "messages": [{"role": "user", "content": "What is the weather in Paris?"}],
                                         "tools": [tool], "tool_choice": choice, "stream": False, **self.max_body(64)})
                valid = result.status == 200
                tool_calls = []
                if valid:
                    payload = result.json()
                    message = payload.get("choices", [{}])[0].get("message") or {}
                    tool_calls = message.get("tool_calls") or []
                    if choice == "none" and tool_calls:
                        valid = False
                    if choice == "required" and not tool_calls:
                        valid = False
                    for call in tool_calls:
                        function = call.get("function") or {}
                        if not function.get("name") or "arguments" not in function:
                            valid = False
                self._record(f"T-01-tools-{choice}", result, expected="200; choice semantics preserved",
                             outcome="pass" if valid else "fail", tool_call_count=len(tool_calls))
                self.assertEqual(result.status, 200, result.text[:500])
                self.assertTrue(valid, f"invalid {choice} tool result: {result.text[:500]}")

    def test_tools_specified_function(self) -> None:
        model = self.require_live_model()
        tool = {"type": "function", "function": {"name": "get_weather", "description": "Get weather",
                "parameters": {"type": "object", "properties": {"city": {"type": "string"}},
                                "required": ["city"], "additionalProperties": False}}}
        result = self.post_chat({
            "model": model,
            "messages": [{"role": "user", "content": "Call get_weather for Paris."}],
            "tools": [tool],
            "tool_choice": {"type": "function", "function": {"name": "get_weather"}},
            **self.max_body(64),
            "stream": False,
        })
        calls = []
        valid = result.status == 200
        if valid:
            message = result.json().get("choices", [{}])[0].get("message") or {}
            calls = message.get("tool_calls") or []
            valid = bool(calls) and all(
                (call.get("function") or {}).get("name") == "get_weather" and
                "arguments" in (call.get("function") or {}) for call in calls
            )
        self._record("T-02-tools-specified-function", result,
                     expected="200; requested function preserved",
                     outcome="pass" if valid else "fail", tool_call_count=len(calls))
        self.assertEqual(result.status, 200, result.text[:500])
        self.assertTrue(valid, result.text[:500])

    def test_cache_usage_observation(self) -> None:
        model = self.require_live_model()
        body = {"model": model, "messages": [{"role": "system", "content": "Stable cache probe."},
                 {"role": "user", "content": "Reply with one short word."}], "stream": False, **self.max_body(8)}
        observations = []
        for index in range(2):
            result = self.post_chat(body)
            usage = None
            if result.status == 200:
                usage = result.json().get("usage")
            observations.append({"status": result.status, "usage_seen": usage is not None,
                                 "cached_tokens": ((usage or {}).get("prompt_tokens_details") or {}).get("cached_tokens")})
            self._record(f"C-02-cache-repeat-{index + 1}", result, expected="200; record usage presence",
                         outcome="pass" if result.status == 200 else "fail", usage_seen=usage is not None)
            self.assertEqual(result.status, 200, result.text[:500])
        self._record("C-02-cache-summary", expected="observe, do not invent hit rate", outcome="pass",
                     observations=observations)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", help="override SUB2API_BASE_URL")
    parser.add_argument("--api-key", help="override SUB2API_API_KEY")
    parser.add_argument("--report", help="override SUB2API_REPORT")
    args = parser.parse_args()
    if args.base_url:
        os.environ["SUB2API_BASE_URL"] = args.base_url
    if args.api_key:
        os.environ["SUB2API_API_KEY"] = args.api_key
    if args.report:
        os.environ["SUB2API_REPORT"] = args.report
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ContractTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 1 if result.failures or result.errors else 0


if __name__ == "__main__":
    sys.exit(main())
