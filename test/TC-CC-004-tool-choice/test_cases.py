#!/usr/bin/env python3
"""Offline tests for CC004 tool parsing and cache metrics."""

import importlib.util
import json
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("run.py")
SPEC = importlib.util.spec_from_file_location("cc004_run", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class Cc004Tests(unittest.TestCase):
    def test_cache_fields_and_missing_usage(self) -> None:
        self.assertEqual(MODULE.cache_fields({"prompt_tokens": 20, "prompt_tokens_details": {"cached_tokens": 8}}), (20, 8, "prompt_tokens_details.cached_tokens"))
        self.assertEqual(MODULE.cache_fields({"prompt_tokens": 20, "cached_tokens": 7}), (20, 7, "cached_tokens"))
        self.assertEqual(MODULE.cache_fields({"prompt_tokens": 20}), (20, None, None))

    def test_json_required_call_is_valid(self) -> None:
        payload = {"choices": [{"message": {"content": None, "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "lookup_city", "arguments": '{"city":"Paris"}'}}]}, "finish_reason": "tool_calls"}], "usage": {"prompt_tokens": 100, "prompt_tokens_details": {"cached_tokens": 40}}}
        result = MODULE.HttpResult(200, {"content-type": "application/json"}, json.dumps(payload).encode(), 1)
        parsed = MODULE.parse_json(result)
        self.assertTrue(MODULE.valid_calls(parsed["calls"]))
        item = MODULE.sample(result, "json", "required", 1)
        self.assertTrue(item["semantic_ok"])
        self.assertEqual(item["cached_tokens"], 40)

    def test_sse_arguments_are_joined_and_done_usage_are_required(self) -> None:
        body = b"\n\n".join([
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","function":{"name":"lookup_city","arguments":"{\\"city\\":"}}]}}]}',
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\\"Paris\\"}"}}]},"finish_reason":"tool_calls"}],"usage":null}',
            b'data: {"choices":[],"usage":{"prompt_tokens":10,"prompt_tokens_details":{"cached_tokens":5}}}',
            b"data: [DONE]",
        ])
        result = MODULE.HttpResult(200, {"content-type": "text/event-stream"}, body, 1)
        parsed = MODULE.parse_sse(result)
        self.assertEqual(parsed["calls"][0]["id"], "call_1")
        self.assertEqual(json.loads(parsed["calls"][0]["function"]["arguments"]), {"city": "Paris"})
        self.assertEqual(parsed["done_count"], 1)
        self.assertEqual(parsed["usage_count"], 1)
        self.assertEqual(parsed["id_frame_counts"], {0: 1})

    def test_sse_repeated_or_changed_identity_is_visible(self) -> None:
        body = b"\n\n".join([
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","function":{"name":"lookup_city"}}]}}]}',
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_2","function":{"name":"other"}}]}}]}',
            b'data: {"choices":[],"usage":{"prompt_tokens":1,"prompt_tokens_details":{"cached_tokens":0}}}',
            b"data: [DONE]",
        ])
        parsed = MODULE.parse_sse(MODULE.HttpResult(200, {}, body, 1))
        self.assertEqual(parsed["id_frame_counts"], {0: 2})
        self.assertEqual(parsed["identity_conflicts"], [0])

    def test_summary_excludes_missing_usage_and_warm_window(self) -> None:
        samples = [
            {"status": 200, "valid_usage": True, "prompt_tokens": 100, "cached_tokens": 0},
            {"status": 200, "valid_usage": False, "prompt_tokens": 100, "cached_tokens": None},
            {"status": 200, "valid_usage": True, "prompt_tokens": 300, "cached_tokens": 150},
        ]
        metrics = MODULE.summarize(samples)
        self.assertEqual(metrics["valid_usage_samples"], 2)
        self.assertEqual(metrics["invalid_or_missing_usage"], 1)
        self.assertAlmostEqual(metrics["all_window"]["token_hit_rate"], 150 / 400)
        self.assertEqual(metrics["warm_window"]["requests"], 1)
        self.assertEqual(metrics["warm_window"]["request_hit_rate"], 1.0)

    def test_payload_choice_and_strict_are_stable(self) -> None:
        first = MODULE.request_body("model-x", "context", "run", "required", "required", True, True)
        second = MODULE.request_body("model-x", "context", "run", "required", "required", True, True)
        self.assertEqual(first, second)
        self.assertEqual(first["tool_choice"], "required")
        self.assertTrue(first["tools"][0]["function"]["strict"])
        self.assertTrue(first["stream_options"]["include_usage"])


if __name__ == "__main__":
    unittest.main()
