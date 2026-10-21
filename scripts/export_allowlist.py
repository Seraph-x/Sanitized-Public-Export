#!/usr/bin/env python3
"""Export only the tracked files you meant to publish.

A whitelist exporter: the file list comes from "git ls-files", so untracked
scratch notes, build output, and local logs can never ride along. Includes are
path prefixes; root files are exact names at the repository root.

    python3 export_allowlist.py --repo . --output /tmp/public \
        --include Sources/ --include Resources/ --include scripts/ \
        --root-file README.md --root-file .gitignore \
        --rename PUBLIC_README.md=README.md \
        --license-from Resources/ThirdParty/MPL-2.0.txt --license-to LICENSE
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

NUL = chr(0)


def tracked_files(repo: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-z"],
        check=True, capture_output=True,
    )
    return [name for name in result.stdout.decode("utf-8").split(NUL) if name]


def select(files: list[str], includes: list[str], root_files: list[str]) -> list[str]:
    chosen = []
    for name in files:
        if name in root_files or any(name.startswith(prefix) for prefix in includes):
            chosen.append(name)
    return chosen


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a whitelisted subset of a git repository.")
    parser.add_argument("--repo", default=".", help="repository root (default: .)")
    parser.add_argument("--output", required=True, help="destination directory")
    parser.add_argument("--include", action="append", default=[], help="path prefix to include (repeatable)")
    parser.add_argument("--root-file", action="append", default=[], help="root-level file to include (repeatable)")
    parser.add_argument("--rename", action="append", default=[], help="OLD=NEW path rewrite (repeatable)")
    parser.add_argument("--license-from", help="file to copy as the licence")
    parser.add_argument("--license-to", default="LICENSE", help="licence file name in the output (default: LICENSE)")
    parser.add_argument("--force", action="store_true", help="allow a non-empty output directory")
    parser.add_argument("--manifest", help="write a JSON manifest of the exported files")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    output = Path(args.output).resolve()
    if not (repo / ".git").exists():
        print("not a git repository: " + str(repo), file=sys.stderr)
        return 2
    if output.exists() and any(output.iterdir()) and not args.force:
        print("output is not empty (use --force): " + str(output), file=sys.stderr)
        return 2

    renames = {}
    for item in args.rename:
        if "=" not in item:
            print("bad --rename value: " + item, file=sys.stderr)
            return 2
        old, new = item.split("=", 1)
        renames[old] = new

    files = select(tracked_files(repo), args.include, args.root_file)
    if not files:
        print("no files matched the include list", file=sys.stderr)
        return 2

    exported = []
    total = 0
    collisions = []
    for name in files:
        source = repo / name
        if not source.is_file():
            continue
        target = output / renames.get(name, name)
        if target.exists():
            collisions.append(name + " -> " + target.relative_to(output).as_posix())
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        total += target.stat().st_size
        exported.append({"source": name, "target": target.relative_to(output).as_posix()})

    if args.license_from:
        licence_source = repo / args.license_from
        if not licence_source.is_file():
            print("licence source missing: " + str(licence_source), file=sys.stderr)
            return 2
        shutil.copy2(licence_source, output / args.license_to)
        exported.append({"source": args.license_from, "target": args.license_to})

    if args.manifest:
        payload = {"repo": str(repo), "count": len(exported), "bytes": total, "files": exported}
        Path(args.manifest).write_text(json.dumps(payload, indent=2) + chr(10), encoding="utf-8")

    print("exported " + str(len(exported)) + " files (" + str(round(total / 1048576, 1)) + " MiB) to " + str(output))
    for old, new in sorted(renames.items()):
        print("  renamed " + old + " -> " + new)
    for item in collisions:
        print("  skipped (target already written): " + item)
    return 0


if __name__ == "__main__":
    sys.exit(main())
