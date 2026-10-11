#!/usr/bin/env python3
"""Unit tests for CC002 repeated-request metrics and SSE parsing."""

import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("run.py")
SPEC = importlib.util.spec_from_file_location("cc002_run", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class Cc002MetricTests(unittest.TestCase):
    def test_missing_cached_tokens_is_not_a_zero_hit(self) -> None:
        samples = [
            {"status": 200, "usage_seen": True, "valid_usage": False, "prompt_tokens": 100, "cached_tokens": None},
            {"status": 200, "usage_seen": True, "valid_usage": True, "prompt_tokens": 200, "cached_tokens": 100},
        ]
        metrics = MODULE.summarize(samples)
        self.assertEqual(metrics["request_hit_rate"], 1.0)
        self.assertEqual(metrics["valid_usage_samples"], 1)
        self.assertEqual(metrics["invalid_or_missing_usage"], 1)
        self.assertAlmostEqual(metrics["usage_coverage"], 0.5)

    def test_token_hit_rate_is_weighted_and_warm_window_excludes_cold_request(self) -> None:
        samples = [
            {"status": 200, "usage_seen": True, "valid_usage": True, "prompt_tokens": 100, "cached_tokens": 0},
            {"status": 200, "usage_seen": True, "valid_usage": True, "prompt_tokens": 200, "cached_tokens": 100},
            {"status": 200, "usage_seen": True, "valid_usage": True, "prompt_tokens": 300, "cached_tokens": 150},
        ]
        metrics = MODULE.summarize(samples)
        self.assertAlmostEqual(metrics["request_hit_rate"], 2 / 3)
        self.assertAlmostEqual(metrics["token_hit_rate"], 250 / 600)
        self.assertEqual(metrics["warm_window"]["requests"], 2)
        self.assertEqual(metrics["warm_window"]["request_hit_rate"], 1.0)
        self.assertAlmostEqual(metrics["warm_window"]["token_hit_rate"], 250 / 500)

    def test_cache_fields_accepts_nested_and_top_level_forms(self) -> None:
        nested = {"prompt_tokens": 20, "prompt_tokens_details": {"cached_tokens": 8}}
        top_level = {"prompt_tokens": 20, "cached_tokens": 7}
        self.assertEqual(MODULE.cache_fields(nested), (20, 8, "prompt_tokens_details.cached_tokens"))
        self.assertEqual(MODULE.cache_fields(top_level), (20, 7, "cached_tokens"))

    def test_repeated_payload_is_stable_and_sse_usage_is_terminal(self) -> None:
        first = MODULE.request_payload("model-x", "reference", "run-id", "sse")
        second = MODULE.request_payload("model-x", "reference", "run-id", "sse")
        self.assertEqual(first, second)
        body = b"\n".join(
            [
                b'data: {"choices":[{"delta":{"content":"OK"}}]}',
                b'data: {"choices":[],"usage":{"prompt_tokens":20,"completion_tokens":1,"total_tokens":21,"prompt_tokens_details":{"cached_tokens":8}}}',
                b"data: [DONE]",
            ]
        )
        result = MODULE.HttpResult(200, {"content-type": "text/event-stream"}, body, 1)
        usage, done = MODULE.parse_sse(result)
        self.assertEqual(usage["prompt_tokens_details"]["cached_tokens"], 8)
        self.assertEqual(done, 1)


if __name__ == "__main__":
    unittest.main()
