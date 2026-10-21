#!/usr/bin/env python3
"""Rewrite secrets and personal data in a copy of a tree.

This is the replacement half of the gate: scan.py reports, redact.py rewrites.
It is meant for an *exported copy* — documentation, transcripts, logs, sample
configs — never for the private working tree. A secret that already reached a
commit must be rotated; rewriting the file does not remove it from history.

    python3 redact.py /tmp/export --dry-run
    python3 redact.py /tmp/export
    python3 redact.py /tmp/export --config gate.json

Exit status: 0 clean, 1 changes were required in --dry-run, 2 misuse.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", ".build", "dist", ".mypy_cache"}
TEXT_LIMIT = 8 * 1024 * 1024

HOME = "~"

RULES = [
    ("posix-home", re.compile(r"/(?:Users|home)/[^/\s\"'():;,]+"), HOME),
    ("windows-home", re.compile(r"[A-Za-z]:\\Users\\[^\\\s\"'():;,]+"), "<home>"),
    ("posix-home-root", re.compile(r"/(?:Users|home)/"), HOME + "/"),
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"), "<private-key>"),
    ("basic-auth-url", re.compile(r"\b([a-z][a-z0-9+.-]*)://([^\s/:@]+):([^\s/@]+)@", re.IGNORECASE), None),
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "<email>"),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "<token>"),
    ("github-pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), "<token>"),
    ("aws-key-id", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "<token>"),
    ("aws-secret", re.compile(r"(aws_secret_access_key\s*[:=]\s*[\"']?)[A-Za-z0-9/+=]{40}", re.IGNORECASE), None),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "<token>"),
    ("openai-key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), "<token>"),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"), "<token>"),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"), "<token>"),
    ("bearer-token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{20,}", re.IGNORECASE), "Bearer <token>"),
    ("npm-token", re.compile(r"\bnpm_[A-Za-z0-9]{30,}\b"), "<token>"),
    ("pypi-token", re.compile(r"\bpypi-[A-Za-z0-9_-]{40,}\b"), "<token>"),
    ("docker-token", re.compile(r"\bdckr_pat_[A-Za-z0-9_-]{20,}\b"), "<token>"),
    ("credential-assignment", re.compile(r"(?<![\w-])(password|passwd|pwd|secret|client[_-]?secret|api[_-]?key|access[_-]?key|auth[_-]?token|token)(\s*[:=]\s*)([\"']?)([^\s\"',;]{8,})\3", re.IGNORECASE), None),
    ("cookie", re.compile(r"\b(?:cf_clearance|PHPSESSID|JSESSIONID|sessionid|session_id|csrf_token|xsrf_token|XSRF-TOKEN|auth_token|remember_token)\s*=\s*[^\s;,\"']{8,}", re.IGNORECASE), None),
    ("cookie-header", re.compile(r"\b(?:Set-Cookie|Cookie)\s*:\s*[^\n]{10,}", re.IGNORECASE), "Cookie: <redacted>"),
]


def looks_secret(value: str) -> bool:
    if len(value) < 12:
        return False
    if value.startswith("<") or ("$" + "{") in value or "$(" in value:
        return False
    if value.startswith(("process.env", "os.environ", "os.getenv", "System.getenv", "getenv")):
        return False
    if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", value) and not any(ch.isdigit() for ch in value):
        return False
    return any(ch.isdigit() for ch in value) or any(not ch.isalnum() for ch in value)


def replace_rule(kind: str, match: re.Match[str], replacement) -> str:
    if replacement is not None:
        return replacement
    if kind == "basic-auth-url":
        return match.group(1) + "://" + match.group(2) + ":<redacted>@"
    if kind == "aws-secret":
        return match.group(1) + "<redacted>"
    if kind == "credential-assignment":
        key, sep, quote, value = match.group(1), match.group(2), match.group(3), match.group(4)
        if not looks_secret(value):
            return match.group(0)
        return key + sep + quote + "<redacted>" + quote
    if kind == "cookie":
        name = match.group(0).split("=", 1)[0]
        return name + "=<redacted>"
    return match.group(0)


def load_config(path: Path | None) -> dict:
    if path is None:
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print("invalid config " + str(path) + ": " + str(error), file=sys.stderr)
        raise SystemExit(2)


def main() -> int:
    parser = argparse.ArgumentParser(description="Rewrite secrets and personal data in an exported copy.")
    parser.add_argument("root", help="directory to rewrite (an exported copy, not the private checkout)")
    parser.add_argument("--config", help="JSON config with literals and extra patterns")
    parser.add_argument("--dry-run", action="store_true", help="report without writing")
    parser.add_argument("--allow-git", action="store_true", help="allow a directory that contains .git")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print("not a directory: " + str(root), file=sys.stderr)
        return 2
    if (root / ".git").exists() and not args.allow_git:
        print("refusing to rewrite a git checkout: " + str(root), file=sys.stderr)
        print("rewriting the working tree does not remove a committed secret; export a copy first", file=sys.stderr)
        return 2

    config = load_config(Path(args.config) if args.config else None)
    rules = list(RULES)
    for literal in config.get("literals", []):
        rules.append(("literal", re.compile(re.escape(literal)), "<redacted>"))
    for name, pattern in config.get("patterns", {}).items():
        rules.append(("custom:" + name, re.compile(pattern), "<redacted>"))

    counts = {}
    changed_files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.stat().st_size > TEXT_LIMIT:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        original = text
        for kind, pattern, replacement in rules:
            def substitute(match, kind=kind, replacement=replacement):
                value = replace_rule(kind, match, replacement)
                if value != match.group(0):
                    counts[kind] = counts.get(kind, 0) + 1
                return value
            text = pattern.sub(substitute, text)
        if text != original:
            changed_files.append(path.relative_to(root).as_posix())
            if not args.dry_run:
                path.write_text(text, encoding="utf-8")

    print("scanned " + str(root))
    if not counts:
        print("RESULT: nothing to redact")
        return 0
    print()
    print(f"{'category':24} {'hits':>6}")
    for kind in sorted(counts):
        print(f"{kind:24} {counts[kind]:>6}")
    print()
    print("files: " + str(len(changed_files)))
    for name in changed_files[:20]:
        print("  " + name)
    if len(changed_files) > 20:
        print("  ... " + str(len(changed_files) - 20) + " more")
    print()
    if args.dry_run:
        print("RESULT: " + str(sum(counts.values())) + " hit(s) would be rewritten (dry run)")
        return 1
    print("RESULT: rewrote " + str(sum(counts.values())) + " hit(s) in " + str(len(changed_files)) + " file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
