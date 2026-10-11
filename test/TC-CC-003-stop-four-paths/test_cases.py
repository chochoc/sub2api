#!/usr/bin/env python3
"""Offline tests for the CC003 parser, stop oracle and cache metrics."""

import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("run.py")
SPEC = importlib.util.spec_from_file_location("cc003_run", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class Cc003OfflineTests(unittest.TestCase):
    def test_oracle_uses_earliest_non_empty_stop(self) -> None:
        self.assertEqual(MODULE.oracle("abc", ["abc", "b"]), "")
        self.assertEqual(MODULE.oracle("abx", ["abc", "b"]), "a")
        self.assertEqual(MODULE.oracle("你好🌍结束秘密", ["🌍结束"]), "你好")

    def test_sse_parser_keeps_fragments_and_terminal_usage(self) -> None:
        body = b"\r\n".join(
            [
                b'data: {"choices":[{"delta":{"content":"hello<EN"}}]}\r\n',
                b'data: {"choices":[{"delta":{"content":"D>secret"},"finish_reason":"stop"}]}\r\n',
                b'data: {"choices":[],"usage":{"prompt_tokens":1200,"completion_tokens":8,"total_tokens":1208,"prompt_tokens_details":{"cached_tokens":1024}}}\r\n',
                b"data: [DONE]\r\n",
                b"\r\n",
            ]
        )
        result = MODULE.HttpResult(200, {"content-type": "text/event-stream"}, body, 1)
        parsed = MODULE.parse_sse(result)
        self.assertEqual(parsed["content"], "hello<END>secret")
        self.assertEqual(parsed["fragments"], ["hello<EN", "D>secret"])
        self.assertEqual(parsed["usage"]["prompt_tokens_details"]["cached_tokens"], 1024)
        self.assertEqual(parsed["done_count"], 1)

    def test_metrics_exclude_missing_usage_and_weight_tokens(self) -> None:
        samples = [
            {"status": 200, "valid_usage": True, "prompt_tokens": 100, "cached_tokens": 50},
            {"status": 200, "valid_usage": True, "prompt_tokens": 300, "cached_tokens": 0},
            {"status": 200, "valid_usage": False, "prompt_tokens": None, "cached_tokens": None},
            {"status": 500, "valid_usage": False, "prompt_tokens": None, "cached_tokens": None},
        ]
        metrics = MODULE.summarize(samples)
        self.assertEqual(metrics["valid_usage_samples"], 2)
        self.assertAlmostEqual(metrics["usage_coverage"], 2 / 3)
        self.assertAlmostEqual(metrics["request_hit_rate"], 0.5)
        self.assertAlmostEqual(metrics["token_hit_rate"], 50 / 400)

    def test_sample_marks_cross_chunk_stop_leak(self) -> None:
        result = MODULE.HttpResult(
            200,
            {"content-type": "text/event-stream"},
            b'data: {"choices":[{"delta":{"content":"hello<EN"}}]}\n\n'
            b'data: {"choices":[],"usage":{"prompt_tokens":10,"prompt_tokens_details":{"cached_tokens":2}}}\n\n'
            b'data: [DONE]\n\n',
            1,
        )
        item = MODULE.sample(result, "sse", "CC003-SS", "cross", "hello")
        self.assertTrue(item["stop_text_leaked"])
        self.assertFalse(item["stop_content_ok"])

    def test_disabled_stop_allows_marker_in_control_response(self) -> None:
        result = MODULE.HttpResult(
            200,
            {"content-type": "application/json"},
            b'{"choices":[{"message":{"content":"hello<END>secret"},"finish_reason":"length"}],'
            b'"usage":{"prompt_tokens":10,"prompt_tokens_details":{"cached_tokens":2}}}',
            1,
        )
        item = MODULE.sample(result, "json", "CC003-JJ", "omitted", "hello<END>secret", False)
        self.assertFalse(item["stop_text_leaked"])
        self.assertTrue(item["stop_content_ok"])


if __name__ == "__main__":
    unittest.main()
