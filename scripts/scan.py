#!/usr/bin/env python3
"""Leak gate for any directory about to leave your control.

Scans text and binary files for personal paths, user names, e-mail addresses,
and credentials, then separates *fixture* hits (the detector's own test data)
from real leaks. Exit status is non-zero when an unexpected hit remains.

    python3 scan.py /tmp/exported-tree
    python3 scan.py /tmp/exported-tree --config gate.json --json
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from pathlib import Path

DEFAULT_PATTERNS = {
    "posix-home": r"/Users/",
    "linux-home": r"/home/",
    "windows-home": r"[A-Za-z]:\\Users\\",
    "email": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    "github-token": r"gh[pousr]_[A-Za-z0-9]{20,}",
    "github-pat": r"github_pat_[A-Za-z0-9_]{20,}",
    "aws-key-id": r"AKIA[0-9A-Z]{16}",
    "slack-token": r"xox[baprs]-[A-Za-z0-9-]{10,}",
    "private-key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
}

HOME_PATTERNS = {"posix-home", "linux-home", "windows-home"}

DEFAULT_PLACEHOLDERS = [
    "privateperson", "<user>", "<email>", "<token>", "<home>", "<redacted>",
    "example.com", "EXAMPLE", "dummy", "placeholder", "redacted", "yourname",
    "someuser", "testuser", "user@", "/Users/<", "/home/<",
]

DEFAULT_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", ".build", "dist", ".mypy_cache"}

# Addresses under these domains are documentation/test data, never a real person.
RESERVED_EMAIL_DOMAINS = ("example.com", "example.org", "example.net", ".invalid", ".test", ".localhost", "localhost", "users.noreply.github.com")

# Vendored archives and images are full of upstream authors' addresses; only
# credentials and personal paths are worth reporting inside binary payloads.
BINARY_PATTERNS = {
    "posix-home", "linux-home", "windows-home",
    "github-token", "github-pat", "aws-key-id", "slack-token", "private-key",
}

NAME_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")


def load_config(path: str | None) -> dict:
    if path is None:
        return {}
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print("invalid gate config " + path + ": " + str(error), file=sys.stderr)
        raise SystemExit(2)


def build_patterns(config: dict) -> dict[str, re.Pattern[str]]:
    raw = dict(DEFAULT_PATTERNS)
    raw.update(config.get("patterns", {}))
    for literal in config.get("literals", []):
        raw["literal:" + literal] = re.escape(literal)
    return {name: re.compile(pattern) for name, pattern in raw.items()}


def is_fixture(name: str, text: str, match: re.Match[str], rel: str, config: dict, placeholders: list[str]) -> bool:
    detector_files = set(config.get("detector_files", []))
    if rel in detector_files:
        return True
    line_start = text.rfind("\n", 0, match.start()) + 1
    line_end = text.find("\n", match.end())
    line = text[line_start: line_end if line_end != -1 else len(text)]
    if any(token in line for token in placeholders):
        return True
    if name == "email":
        domain = match.group(0).rsplit("@", 1)[-1].lower()
        return any(domain == item.lstrip(".") or domain.endswith(item) for item in RESERVED_EMAIL_DOMAINS)
    if name in HOME_PATTERNS:
        following = text[match.end(): match.end() + 1]
        return following not in NAME_CHARS
    return False


def scan(root: Path, config: dict) -> dict:
    patterns = build_patterns(config)
    placeholders = list(DEFAULT_PLACEHOLDERS) + list(config.get("placeholders", []))
    skip_dirs = set(DEFAULT_SKIP_DIRS) | set(config.get("skip_dirs", []))
    skip_globs = config.get("skip_globs", [])
    allowed = set(config.get("allow", []))
    binary_patterns = set(BINARY_PATTERNS) | {name for name in patterns if name.startswith("literal:")}
    binary_patterns |= set(config.get("binary_patterns", []))
    results = {}
    findings = []
    files = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(root).as_posix()
        if any(part in skip_dirs for part in path.relative_to(root).parts):
            continue
        if any(fnmatch.fnmatch(rel, pattern) for pattern in skip_globs):
            continue
        files += 1
        data = path.read_bytes()
        try:
            text = data.decode("utf-8")
            binary = False
        except UnicodeDecodeError:
            text = data.decode("latin-1")
            binary = True
        if not binary and b"\x00" in data[:8192]:
            binary = True
        for name, pattern in patterns.items():
            if name in allowed or (binary and name not in binary_patterns):
                continue
            for match in pattern.finditer(text):
                fixture = is_fixture(name, text, match, rel, config, placeholders)
                line_no = text.count("\n", 0, match.start()) + 1
                entry = results.setdefault(name, {"total": 0, "fixture": 0, "unexpected": 0})
                entry["total"] += 1
                entry["fixture" if fixture else "unexpected"] += 1
                if not fixture:
                    line_end = text.find("\n", match.start())
                    snippet = text[match.start(): line_end if line_end != -1 else match.start() + 120]
                    findings.append({"pattern": name, "file": rel, "line": line_no, "snippet": snippet[:160]})
    unexpected = sum(entry["unexpected"] for entry in results.values())
    return {"root": str(root), "files": files, "patterns": results, "findings": findings, "unexpected": unexpected}


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan a tree for personal data and credentials before publishing.")
    parser.add_argument("root", help="directory to scan")
    parser.add_argument("--config", help="JSON gate config (patterns, literals, detector_files, placeholders)")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    parser.add_argument("--allow", action="append", default=[], help="pattern name to ignore (repeatable)")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    if not root.is_dir():
        print("not a directory: " + str(root), file=sys.stderr)
        return 2
    report = scan(root, load_config(args.config))
    for name in args.allow:
        report["patterns"].pop(name, None)
        report["findings"] = [item for item in report["findings"] if item["pattern"] != name]
    report["unexpected"] = len(report["findings"])
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 1 if report["unexpected"] else 0
    print("scanned " + str(report["files"]) + " files under " + report["root"])
    print()
    print(f"{'pattern':22} {'total':>7} {'fixture':>8} {'unexpected':>11}")
    for name in sorted(report["patterns"]):
        entry = report["patterns"][name]
        flag = "" if entry["unexpected"] == 0 else "  LEAK"
        print(f"{name:22} {entry['total']:>7} {entry['fixture']:>8} {entry['unexpected']:>11}{flag}")
    if report["findings"]:
        print()
        print("unexpected hits:")
        for item in report["findings"]:
            print("  " + item["file"] + ":" + str(item["line"]) + " [" + item["pattern"] + "] " + item["snippet"])
    print()
    print("RESULT: " + ("clean" if report["unexpected"] == 0 else "LEAK — " + str(report["unexpected"]) + " unexpected hit(s)"))
    return 1 if report["unexpected"] else 0


if __name__ == "__main__":
    sys.exit(main())
