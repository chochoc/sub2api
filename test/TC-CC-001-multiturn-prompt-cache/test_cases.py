#!/usr/bin/env python3
"""Unit tests for CC001 metric and SSE parsing helpers."""

import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("run.py")
SPEC = importlib.util.spec_from_file_location("cc001_run", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class Cc001MetricTests(unittest.TestCase):
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

    def test_token_hit_rate_is_weighted(self) -> None:
        samples = [
            {"status": 200, "usage_seen": True, "valid_usage": True, "prompt_tokens": 100, "cached_tokens": 50},
            {"status": 200, "usage_seen": True, "valid_usage": True, "prompt_tokens": 300, "cached_tokens": 0},
        ]
        metrics = MODULE.summarize(samples)
        self.assertAlmostEqual(metrics["request_hit_rate"], 0.5)
        self.assertAlmostEqual(metrics["token_hit_rate"], 50 / 400)
        self.assertAlmostEqual(metrics["warm_window"]["token_hit_rate"], 0.0)

    def test_sse_usage_and_done_are_parsed(self) -> None:
        body = b"\n".join(
            [
                b'data: {"choices":[{"delta":{"content":"OK"}}]}',
                b'data: {"choices":[],"usage":{"prompt_tokens":20,"completion_tokens":1,"total_tokens":21,"prompt_tokens_details":{"cached_tokens":8}}}',
                b"data: [DONE]",
            ]
        )
        result = MODULE.HttpResult(200, {"content-type": "text/event-stream"}, body, 1)
        content, usage, done = MODULE.parse_sse(result)
        self.assertEqual(content, "OK")
        self.assertEqual(usage["prompt_tokens_details"]["cached_tokens"], 8)
        self.assertEqual(done, 1)


if __name__ == "__main__":
    unittest.main()
