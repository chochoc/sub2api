import json
import os
import sys
import threading
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from tempfile import NamedTemporaryFile

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import sub2api_admin as ops  # noqa: E402


class Handler(BaseHTTPRequestHandler):
    seen = {}

    def do_GET(self):
        Handler.seen["authorization"] = self.headers.get("Authorization")
        body = json.dumps({"data": {"errors": [{"id": 1, "status_code": 503, "phase": "upstream", "error_source": "upstream_http", "account_id": 32}]}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


class OpsTests(unittest.TestCase):
    def test_keychain_lookup_never_prints_secret(self):
        completed = type("Completed", (), {"returncode": 0, "stdout": "admin-secret-value\n"})()
        with patch.object(ops.platform, "system", return_value="Darwin"), patch.object(ops.subprocess, "run", return_value=completed) as run:
            self.assertEqual(ops.keychain_token("https://host"), "admin-secret-value")
        self.assertEqual(run.call_args.args[0][:4], ["security", "find-generic-password", "-s", "sub2api-admin"])

    def test_fetch_all_pages_rejects_repeated_page(self):
        class Client:
            def request(self, *_args, **_kwargs):
                return {"data": {"items": [{"id": 1}], "total": 3}}
        with self.assertRaises(ops.AdminError):
            ops.fetch_all_pages(Client(), "/admin/users", {"page_size": 1}, max_pages=3)

    def test_page_items_unwraps_envelope(self):
        rows, total = ops.page_items({"data": {"items": [{"id": 2}], "total": 1}})
        self.assertEqual(rows, [{"id": 2}])
        self.assertEqual(total, 1)

    def test_duration_and_classification(self):
        start = ops.parse_since("1h")
        self.assertEqual((ops.dt.datetime.now(ops.dt.timezone.utc) - start).seconds // 3600, 1)
        result = ops.classify_error({"status_code": 502, "phase": "upstream", "error_source": "upstream_http"})
        self.assertEqual(result["category"], "upstream_or_proxy")
        self.assertEqual(result["probable_cause"], "upstream_gateway_or_transport")

    def test_aggregate_and_accounts(self):
        rows = [
            {"status_code": 503, "phase": "upstream", "account_id": 27},
            {"status_code": 502, "phase": "network", "account_id": 32},
            {"status_code": 200, "phase": "routing", "account_id": 32},
        ]
        summary = ops.aggregate_errors(rows)
        self.assertEqual(summary["status_counts"], {"503": 1, "502": 1, "200": 1})
        report = ops.account_error_report(rows, [27, 32, 33])
        self.assertEqual(report[0]["account_id"], 32)
        self.assertEqual(report[-1]["error_count"], 0)

    def test_top_accounts_is_sorted_by_error_count(self):
        rows = [{"account_id": 1, "status_code": 502}] * 2 + [{"account_id": 2, "status_code": 503}]
        report = ops.account_error_report(rows, [])
        self.assertEqual([item["account_id"] for item in report[:2]], [1, 2])

    def test_redaction(self):
        value = {"Authorization": "Bearer very-secret-token", "message": "admin-012345678901234567890123"}
        safe = ops.redact(value)
        self.assertNotIn("very-secret", json.dumps(safe))
        self.assertNotIn("admin-012345", json.dumps(safe))

    def test_traffic_metrics(self):
        metrics = ops.traffic_metrics({"data": {"total_requests": 10, "success_count": 8}}, 3)
        self.assertEqual(metrics["total_calls"], 10)
        self.assertEqual(metrics["successful_calls"], 8)
        self.assertEqual(metrics["error_calls"], 2)
        self.assertEqual(metrics["error_rate"], 0.2)

    def test_http_client_uses_bearer_without_leaking(self):
        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = ops.AdminClient("http://127.0.0.1:%s" % server.server_port, "replaceable-token")
            rows = client.list_errors(ops.parse_since("1h"))
            self.assertEqual(rows[0]["account_id"], 32)
            self.assertEqual(Handler.seen["authorization"], "Bearer replaceable-token")
        finally:
            server.shutdown()
            server.server_close()

    def test_admin_prefix_defaults_to_api_key(self):
        args = ops.build_parser().parse_args(["errors", "list", "--base-url", "http://example", "--token", "admin-replaceable"])
        client = ops.build_client(args)
        self.assertEqual(client.auth_mode, "api-key")
        self.assertEqual(client._headers()["x-api-key"], "admin-replaceable")

    def test_config_supplies_base_url_and_auth_mode(self):
        with NamedTemporaryFile("w", encoding="utf-8") as handle:
            json.dump({"base_url": "http://config.example", "auth_mode": "bearer"}, handle)
            handle.flush()
            with patch.dict(os.environ, {"SUB2API_CONFIG_FILE": handle.name}, clear=False), \
                    patch.object(ops, "keychain_token", return_value="jwt-from-keychain"):
                args = ops.build_parser().parse_args(["errors", "list"])
                client = ops.build_client(args)
        self.assertEqual(client.base_url, "http://config.example")
        self.assertEqual(client.auth_mode, "bearer")
        self.assertEqual(client.token, "jwt-from-keychain")

    def test_remote_compound_command_is_passed_to_ssh(self):
        with NamedTemporaryFile("w", encoding="utf-8") as handle:
            handle.write("ssh host\n")
            handle.flush()
            remote = ops.RemoteDiagnostics(handle.name)
            argv = remote._argv(remote.COMMANDS["service"])
            self.assertEqual(argv[-1], remote.COMMANDS["service"])

    def test_markdown_output_redacts_secrets(self):
        with NamedTemporaryFile() as handle:
            ops.output_value({"Authorization": "Bearer very-secret-token-value-123456789"}, "markdown", handle.name)
            self.assertNotIn("very-secret", Path(handle.name).read_text())

    def test_mutation_requires_confirmation(self):
        args = type("Args", (), {"confirm": False})()
        with self.assertRaises(ops.AdminError):
            ops.confirm(args, "cleanup")


if __name__ == "__main__":
    unittest.main()
