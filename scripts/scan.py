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

# Built from fragments so the detector's own source never looks like a path.
_POSIX_HOME = "/Use" + "rs/"
_LINUX_HOME = "/ho" + "me/"

DEFAULT_PATTERNS = {
    "posix-home": _POSIX_HOME + r"[^/\s\"'():;,`]+",
    "linux-home": _LINUX_HOME + r"[^/\s\"'():;,`]+",
    "windows-home": r"[A-Za-z]:\\Users\\[^\\\s\"'():;,`]+",
    "email": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    "github-token": r"gh[pousr]_[A-Za-z0-9]{20,}",
    "github-pat": r"github_pat_[A-Za-z0-9_]{20,}",
    "aws-key-id": r"AKIA[0-9A-Z]{16}",
    "slack-token": r"xox[baprs]-[A-Za-z0-9-]{10,}",
    "private-key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "jwt": r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b",
    "basic-auth-url": r"\b[a-z][a-z0-9+.-]*://[^\s/:@]+:[^\s/@]+@",
    "npm-token": r"\bnpm_[A-Za-z0-9]{30,}\b",
    "pypi-token": r"\bpypi-[A-Za-z0-9_-]{40,}\b",
    "docker-token": r"\bdckr_pat_[A-Za-z0-9_-]{20,}\b",
    "aws-secret": r"aws_secret_access_key\s*[:=]\s*[\"']?[A-Za-z0-9/+=]{40}",
    "credential-assignment": r"(?i)\b(password|passwd|pwd|secret|client[_-]?secret|api[_-]?key|access[_-]?key|auth[_-]?token|token)\b\s*[:=]\s*[\"']?[^\s\"',;]{8,}",
    "cookie": r"\b(?:cf_clearance|PHPSESSID|JSESSIONID|sessionid|session_id|csrf_token|xsrf_token|XSRF-TOKEN|auth_token)\s*=\s*[^\s;,\"']{8,}",
    "bearer-token": r"\bBearer\s+[A-Za-z0-9._~+/=-]{20,}",
    "openai-key": r"\bsk-[A-Za-z0-9_-]{20,}\b",
    "google-api-key": r"\bAIza[0-9A-Za-z_-]{30,}\b",
}

HOME_PATTERNS = {"posix-home", "linux-home", "windows-home"}

DEFAULT_PLACEHOLDERS = [
    "privateperson", "<user>", "<email>", "<token>", "<home>", "<redacted>",
    "example.com", "EXAMPLE", "dummy", "placeholder", "redacted", "yourname",
    "someuser", "testuser", "user@", "/Users/<", "/home/<",
]

# A placeholder excuses a value only when the whole value is one. Substring
# matching let a real token containing "dummy" pass as documentation.
PLACEHOLDER_VALUE_PATTERNS = (
    re.compile(r"^<[A-Za-z0-9_.:/ -]+>$"),
    re.compile(r"^\$\{[A-Za-z0-9_.]+\}$"),
    re.compile(r"(?i)^(example|sample|demo|dummy|placeholder|redacted|privateperson|yourname|someuser|testuser|your[-_]?[a-z0-9]*)([-_][a-z0-9]+)*$"),
)

DEFAULT_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", ".build", "dist", ".mypy_cache"}

# Addresses under these domains are documentation/test data, never a real person.
RESERVED_EMAIL_DOMAINS = ("example.com", "example.org", "example.net", ".invalid", ".test", ".localhost", "localhost", "users.noreply.github.com")

# Vendored archives and images are full of upstream authors' addresses; only
# credentials and personal paths are worth reporting inside binary payloads.
BINARY_PATTERNS = {
    "posix-home", "linux-home", "windows-home",
    "github-token", "github-pat", "aws-key-id", "aws-secret", "slack-token", "private-key",
    "jwt", "npm-token", "pypi-token", "docker-token",
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


def is_placeholder_value(value: str, placeholders: list[str]) -> bool:
    if value in placeholders or value in DEFAULT_PLACEHOLDERS:
        return True
    return any(pattern.match(value) for pattern in PLACEHOLDER_VALUE_PATTERNS)


def is_fixture(name: str, text: str, match: re.Match[str], rel: str, config: dict, placeholders: list[str]) -> bool:
    detector_files = set(config.get("detector_files", []))
    if rel in detector_files:
        return True
    value = match.group(0)
    # A placeholder excuses the value only when the value itself is one: an
    # exact token, a <bracketed> form, a shell variable, or a placeholder word.
    # A real token that merely contains "dummy" stays a leak.
    if name != "email" and is_placeholder_value(value, placeholders):
        return True
    if name == "basic-auth-url":
        return "<" in match.group(0)
    if name in ("credential-assignment", "cookie"):
        value = match.group(0)
        return "<" in value or "${" in value or "process.env" in value
    if name == "email":
        domain = value.rsplit("@", 1)[-1].lower()
        for item in RESERVED_EMAIL_DOMAINS:
            bare = item.lstrip(".")
            if item.startswith("."):
                if domain.endswith(item):
                    return True
            elif domain == bare or domain.endswith("." + bare):
                return True
        return False
    if name in HOME_PATTERNS:
        # The pattern captures prefix plus name; a placeholder name is a fixture.
        segment = re.split(r"[/\\]", value)[-1]
        return segment == "" or is_placeholder_value(segment, placeholders)
    return False


def mask_line(line: str, patterns: dict[str, re.Pattern[str]]) -> str:
    """Mask every sensitive value on the line, not just the one being reported."""
    masked = line
    for pattern in patterns.values():
        masked = pattern.sub(lambda match: mask(match.group(0)), masked)
    return masked


def mask(value: str) -> str:
    if len(value) <= 8:
        return value[:2] + "…"
    return value[:4] + "…" + value[-2:]


def scan(root: Path, config: dict, show_values: bool = False) -> dict:
    patterns = build_patterns(config)
    placeholders = list(DEFAULT_PLACEHOLDERS) + list(config.get("placeholders", []))
    skip_dirs = set(DEFAULT_SKIP_DIRS) | set(config.get("skip_dirs", []))
    skip_globs = config.get("skip_globs", [])
    allowed = set(config.get("allow", []))
    retained_values = [value for value in config.get("retain", []) if isinstance(value, str) and value]
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
                line_no = text.count("\n", 0, match.start()) + 1
                entry = results.setdefault(name, {"total": 0, "fixture": 0, "retained": 0, "unexpected": 0})
                entry["total"] += 1
                if any(value in match.group(0) for value in retained_values):
                    entry["retained"] += 1
                    continue
                fixture = is_fixture(name, text, match, rel, config, placeholders)
                entry["fixture" if fixture else "unexpected"] += 1
                if not fixture:
                    line_start = text.rfind("\n", 0, match.start()) + 1
                    line_end = text.find("\n", match.end())
                    line = text[line_start: line_end if line_end != -1 else len(text)]
                    snippet = line if show_values else mask_line(line, patterns)
                    findings.append({"pattern": name, "file": rel, "line": line_no, "snippet": snippet[:160]})
    unexpected = sum(entry["unexpected"] for entry in results.values())
    return {"root": str(root), "files": files, "patterns": results, "findings": findings, "unexpected": unexpected}


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan a tree for personal data and credentials before publishing.")
    parser.add_argument("root", help="directory to scan")
    parser.add_argument("--config", help="JSON gate config (patterns, literals, detector_files, placeholders)")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    parser.add_argument("--allow", action="append", default=[], help="pattern name to ignore (repeatable)")
    parser.add_argument("--show-values", action="store_true", help="print matched values unmasked (local use only)")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    if not root.is_dir():
        print("not a directory: " + str(root), file=sys.stderr)
        return 2
    report = scan(root, load_config(args.config), show_values=args.show_values)
    for name in args.allow:
        report["patterns"].pop(name, None)
        report["findings"] = [item for item in report["findings"] if item["pattern"] != name]
    report["unexpected"] = len(report["findings"])
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 1 if report["unexpected"] else 0
    print("scanned " + str(report["files"]) + " files under " + report["root"])
    print()
    print(f"{'pattern':22} {'total':>7} {'fixture':>8} {'retained':>9} {'unexpected':>11}")
    for name in sorted(report["patterns"]):
        entry = report["patterns"][name]
        flag = "" if entry["unexpected"] == 0 else "  LEAK"
        print(f"{name:22} {entry['total']:>7} {entry['fixture']:>8} {entry.get('retained', 0):>9} {entry['unexpected']:>11}{flag}")
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
