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
import datetime
import json
import re
import subprocess
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


def mask(value: str) -> str:
    if len(value) <= 10:
        return value[:2] + "…"
    return value[:6] + "…" + value[-2:]


def history_findings(root: Path, values: list[str]) -> list[dict]:
    findings = []
    for value in values[:20]:
        try:
            result = subprocess.run(
                ["git", "-C", str(root), "log", "--all", "--oneline", "-S", value, "--max-count", "5"],
                capture_output=True, text=True, timeout=20,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        commits = [line for line in result.stdout.splitlines() if line.strip()]
        if commits:
            findings.append({"value": mask(value), "commits": commits})
    return findings


def write_report(path: Path, root: Path, counts: dict, changed_files: list[str], secrets: list[str],
                 has_git: bool, history: list[dict], dry_run: bool) -> None:
    lines = ["# Redaction report", ""]
    lines.append("- Root: " + str(root))
    lines.append("- Generated: " + datetime.datetime.now().astimezone().isoformat(timespec="seconds"))
    lines.append("- Mode: " + ("dry run (nothing written)" if dry_run else "applied"))
    lines.append("- Files rewritten: " + str(len(changed_files)))
    lines.append("")
    lines.append("## Categories")
    lines.append("")
    lines.append("| Category | Hits |")
    lines.append("| --- | --- |")
    for kind in sorted(counts):
        lines.append("| " + kind + " | " + str(counts[kind]) + " |")
    lines.append("")
    lines.append("## Files")
    lines.append("")
    for name in changed_files[:100]:
        lines.append("- " + name)
    if len(changed_files) > 100:
        lines.append("- … " + str(len(changed_files) - 100) + " more")
    lines.append("")
    lines.append("## Git history")
    lines.append("")
    if not has_git:
        lines.append("Not a git checkout: nothing to check.")
    elif history:
        lines.append("These redacted values still appear in commits:")
        lines.append("")
        for item in history:
            lines.append("- " + item["value"] + " — " + "; ".join(item["commits"]))
        lines.append("")
        lines.append("Rotate every value listed above and rewrite the history (for example with "
                     "git filter-repo) before publishing that repository.")
    else:
        lines.append("History was not searched. Re-run with --check-history to list commits that still "
                     "contain the redacted values.")
    lines.append("")
    lines.append("Redacting a working tree does not remove a secret from history: rotate it and rewrite "
                 "the history if the repository is published.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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
    parser.add_argument("--report", help="write a Markdown report of what was rewritten")
    parser.add_argument("--check-history", action="store_true", help="search git history for the redacted values (needs .git)")
    parser.add_argument("--allow-git", action="store_true", help="deprecated: a .git directory no longer blocks redaction")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print("not a directory: " + str(root), file=sys.stderr)
        return 2
    has_git = (root / ".git").exists()
    if has_git and not args.allow_git:
        print("note: " + str(root) + " is a git checkout; the report will record that history is not rewritten", file=sys.stderr)

    config = load_config(Path(args.config) if args.config else None)
    rules = list(RULES)
    for literal in config.get("literals", []):
        rules.append(("literal", re.compile(re.escape(literal)), "<redacted>"))
    for name, pattern in config.get("patterns", {}).items():
        rules.append(("custom:" + name, re.compile(pattern), "<redacted>"))

    counts = {}
    changed_files = []
    secrets_seen = []
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
                    if kind not in ("posix-home", "posix-home-root", "windows-home", "email", "literal"):
                        raw = match.group(4) if kind == "credential-assignment" else match.group(0)
                        if raw not in secrets_seen and len(secrets_seen) < 50:
                            secrets_seen.append(raw)
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
    history = history_findings(root, secrets_seen) if (has_git and args.check_history) else []
    if args.report:
        write_report(Path(args.report).resolve(), root, counts, changed_files, secrets_seen, has_git, history, args.dry_run)
        print("report: " + str(Path(args.report).resolve()))
    print()
    if args.dry_run:
        print("RESULT: " + str(sum(counts.values())) + " hit(s) would be rewritten (dry run)")
        return 1
    print("RESULT: rewrote " + str(sum(counts.values())) + " hit(s) in " + str(len(changed_files)) + " file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
