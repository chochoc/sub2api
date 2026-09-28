"""Exercise the gate against real temporary Git repositories (no network)."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from check_architecture_index import END, GUIDE, START, ci_range


SCRIPT = Path(__file__).with_name("check_architecture_index.py").resolve()


class ArchitectureIndexTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Gate Test")
        self.git("config", "user.email", "gate@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.write(GUIDE, f"# Guide\n\n{START}\n\n- Historic: `backend/main.go`\n\n{END}\n")
        self.write("backend/main.go", "package main\n")
        self.commit()
        self.base = self.git("rev-parse", "HEAD").strip()

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root, stderr=subprocess.PIPE, text=True)

    def write(self, path, content):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def commit(self):
        self.git("add", "-A")
        self.git("commit", "-qm", "test snapshot")

    def record(self, *paths):
        guide = self.root / GUIDE
        guide.write_text(guide.read_text().replace(END, "- Change: " + ", ".join(f"`{p}`" for p in paths) + "\n" + END))

    def gate(self, expected, *args):
        result = subprocess.run([sys.executable, "-B", str(SCRIPT), *args], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def test_old_index_or_body_only_edit_cannot_cover_new_code(self):
        self.write("backend/main.go", "package changed\n")
        self.gate(1)
        guide = self.root / GUIDE
        guide.write_text("Mention `backend/main.go` outside the ledger\n" + guide.read_text())
        self.gate(1)
        self.record("backend/main.go")
        self.gate(0)

    def test_every_file_including_untracked_assets_config_tests_and_prompts(self):
        paths = ["frontend/src/Asset.vue", "deploy/example.yaml", "backend/main_test.go", "frontend/pnpm-lock.yaml", "backend/internal/service/prompts/example.txt"]
        for path in paths:
            self.write(path, "changed\n")
        self.record(*paths[:-1])
        self.gate(1)
        self.record(paths[-1])
        self.gate(0)

    def test_rename_and_delete_need_old_paths(self):
        self.git("mv", "backend/main.go", "backend/renamed.go")
        self.record("backend/renamed.go")
        self.gate(1)
        self.record("backend/main.go")
        self.gate(0)
        self.commit()
        (self.root / "backend/renamed.go").unlink()
        self.gate(1)
        self.record("backend/renamed.go")
        self.gate(0)

    def test_staged_check_cannot_use_unstaged_guide(self):
        self.write("backend/main.go", "package changed\n")
        self.git("add", "backend/main.go")
        self.record("backend/main.go")
        self.gate(1, "--staged")
        self.git("add", GUIDE)
        self.gate(0, "--staged")

    def test_committed_range_ignores_worktree_guide(self):
        self.write("backend/main.go", "package changed\n")
        self.commit()
        self.record("backend/main.go")
        self.gate(1, "--base", self.base, "--head", "HEAD")
        self.commit()
        self.gate(0, "--base", self.base, "--head", "HEAD")

    def test_prose_is_exempt_but_embedded_legal_text_is_not(self):
        self.write("docs/notes.md", "notes\n")
        self.gate(0)
        self.write("docs/legal/admin-compliance.zh.md", "legal text\n")
        self.gate(1)
        self.record("docs/legal/admin-compliance.zh.md")
        self.gate(0)

    def test_missing_guide_or_invalid_marker_or_history_fails_closed(self):
        self.write("backend/main.go", "package changed\n")
        (self.root / GUIDE).unlink()
        self.gate(1)
        self.write(GUIDE, f"{END}\n`backend/main.go`\n{START}")
        self.gate(1)
        self.gate(1, "--base", "does-not-exist")

    def test_ignored_outputs_do_not_trigger_gate(self):
        self.write(".gitignore", "build/\n")
        self.record(".gitignore")
        self.commit()
        self.write("build/output.js", "generated\n")
        self.gate(0)

    def test_ci_push_pr_and_new_branch_ranges(self):
        self.git("update-ref", "refs/remotes/origin/main", self.base)
        self.write("backend/main.go", "package changed\n")
        self.record("backend/main.go")
        self.commit()
        head = self.git("rev-parse", "HEAD").strip()
        push = {"before": self.base, "after": head, "repository": {"default_branch": "main"}}
        self.assertEqual(ci_range(self.root, push, "push"), (self.base, head))
        push["before"] = "0" * 40
        self.assertEqual(ci_range(self.root, push, "push"), (self.base, head))
        pr = {"pull_request": {"base": {"sha": self.base}, "head": {"sha": head}}}
        self.assertEqual(ci_range(self.root, pr, "pull_request"), (self.base, head))
        self.gate(0, "--base", self.base, "--head", head)

    def test_ci_cli_uses_event_range_and_rejects_unindexed_commit(self):
        self.write("backend/main.go", "package changed\n")
        self.commit()
        event_file = self.root / "event.json"
        env = dict(os.environ, GITHUB_EVENT_PATH=str(event_file), GITHUB_EVENT_NAME="push")
        for expected in (1, 0):
            event_file.write_text(json.dumps({"before": self.base, "after": self.git("rev-parse", "HEAD").strip()}))
            result = subprocess.run([sys.executable, "-B", str(SCRIPT), "--ci"], cwd=self.root, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
            event_file.unlink()
            if expected:
                self.record("backend/main.go")
                self.commit()

    def test_deleting_guide_is_rejected_even_without_code_changes(self):
        (self.root / GUIDE).unlink()
        self.gate(1)


if __name__ == "__main__":
    unittest.main()
