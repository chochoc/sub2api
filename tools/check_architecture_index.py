#!/usr/bin/env python3
"""Require changed code paths in newly added architecture change-index lines."""

import argparse
import difflib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


GUIDE = "docs/ARCHITECTURE_AND_MODIFICATION_GUIDE.md"
START = "<!-- architecture-change-index:start -->"
END = "<!-- architecture-change-index:end -->"


def git(root, *args, input=None):
    result = subprocess.run(
        ["git", "-C", str(root), *args], input=input,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if result.returncode:
        raise ValueError(result.stderr.decode(errors="replace").strip())
    return result.stdout.decode("utf-8", errors="surrogateescape")


def code_path(path):
    # Only prose Markdown is exempt. Unknown extensions, prompts, SQL, assets,
    # generated files, lockfiles, tests and CI all count. Legal text is embedded.
    return not path.lower().endswith(".md") or path.startswith("docs/legal/")


def index_section(text):
    if text.count(START) != 1 or text.count(END) != 1:
        raise ValueError(f"{GUIDE}: expected exactly one change-index marker pair")
    start, end = text.index(START), text.index(END)
    if start >= end:
        raise ValueError(f"{GUIDE}: change-index markers are out of order")
    return text[start + len(START):end].splitlines()


def check(changed, before, after):
    current = index_section(after)
    required = sorted(path for path in changed if code_path(path))
    if not required:
        return []
    previous = index_section(before) if before else []
    # Read only additions inside the ledger. An existing directory map or an
    # unchanged historic entry cannot satisfy a new change to the same file.
    added = []
    matcher = difflib.SequenceMatcher(a=previous, b=current, autojunk=False)
    for tag, _, _, first, last in matcher.get_opcodes():
        if tag in ("insert", "replace"):
            added.extend(current[first:last])
    indexed = set(re.findall(r"`([^`\n]+)`", "\n".join(added)))
    return [path for path in required if path not in indexed]


def committed_guide(root, revision):
    if not git(root, "ls-tree", "--name-only", revision, "--", GUIDE).strip():
        return ""
    return git(root, "show", f"{revision}:{GUIDE}")


def ci_range(root, event, event_name):
    if event_name == "pull_request":
        head = event["pull_request"]["head"]["sha"]
        base = git(root, "merge-base", event["pull_request"]["base"]["sha"], head).strip()
        return base, head
    if event_name != "push":
        raise ValueError(f"unsupported CI event: {event_name}")
    head = event["after"]
    if not head.strip("0"):
        raise ValueError("deleted-ref pushes have no code snapshot to check")
    base = event["before"]
    if base.strip("0"):
        return base, head
    # New branch/tag: compare with the default branch, never silently skip it.
    default = event["repository"]["default_branch"]
    base = git(root, "merge-base", f"refs/remotes/origin/{default}", head).strip()
    if base == head:
        parents = git(root, "rev-list", "--parents", "-n", "1", head).split()[1:]
        base = parents[0] if parents else git(root, "hash-object", "-w", "-t", "tree", "--stdin", input=b"").strip()
    return base, head


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="baseline revision; defaults to HEAD for a local check")
    parser.add_argument("--head", help="compare committed snapshots instead of the working tree")
    parser.add_argument("--staged", action="store_true", help="check only the index against HEAD")
    parser.add_argument("--ci", action="store_true", help="resolve range from GitHub push/PR event")
    args = parser.parse_args(argv)
    if args.staged and (args.base or args.head or args.ci):
        parser.error("--staged cannot be combined with --base, --head or --ci")
    if args.ci and (args.base or args.head):
        parser.error("--ci cannot be combined with --base or --head")
    try:
        root = Path(git(Path.cwd(), "rev-parse", "--show-toplevel").strip())
        base, head = args.base or "HEAD", args.head
        if args.ci:
            event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
            base, head = ci_range(root, event, os.environ["GITHUB_EVENT_NAME"])
        # Validate revisions even when a missing guide would otherwise look like
        # an initial baseline. Missing history must fail, not become a no-op.
        git(root, "rev-parse", "--verify", f"{base}^{{tree}}")
        diff_args = ["diff", "--name-only", "-z", "--no-renames"]
        if args.staged:
            diff_args.append("--cached")
        diff_args.append(base)
        if head:
            git(root, "rev-parse", "--verify", f"{head}^{{commit}}")
            diff_args.append(head)
        changed = set(git(root, *diff_args, "--").split("\0")) - {""}
        if not head and not args.staged:
            changed.update(git(root, "ls-files", "--others", "--exclude-standard", "-z").split("\0"))
            changed.discard("")
        before = committed_guide(root, base)
        if head:
            after = committed_guide(root, head)
        elif args.staged:
            after = git(root, "show", f":{GUIDE}") if GUIDE in git(root, "ls-files", "-z", "--", GUIDE).split("\0") else ""
        else:
            path = root / GUIDE
            after = path.read_text(encoding="utf-8") if path.exists() else ""
        missing = check(changed, before, after)
        if missing:
            print(f"FAIL: add each changed code path to new lines in {GUIDE} §11:", file=sys.stderr)
            for path in missing:
                print(f"  `{path}`", file=sys.stderr)
            return 1
        print(f"Architecture index OK ({sum(code_path(p) for p in changed)} code paths checked).")
        return 0
    except (ValueError, OSError, KeyError) as error:
        print(f"Architecture index check failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
