#!/usr/bin/env python3
"""Publish an allowlisted, sanitized mirror of a private repository.

Pipeline: check the private tree is committed, update the public checkout,
export the allowlist, run the leak gate, mirror the tree (deleting files that
are no longer exported), commit with a noreply identity, push, and verify the
remote branch head.

    python3 mirror_sync.py --config mirror.json --dry-run
    python3 mirror_sync.py --config mirror.json --yes

Exit status: 0 published (or already identical), 1 gate/push failure, 2 misuse.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROTECTED = {".git", ".github"}
DEFAULTS = {
    "branch": "main",
    "protect": [".git", ".github"],
    "message_prefix": "Sync public source from private",
    "push_attempts": 3,
}


def run(args, cwd=None, check=True, quiet=True):
    return subprocess.run(
        args, cwd=cwd, check=check,
        stdout=subprocess.DEVNULL if quiet else None,
        stderr=subprocess.STDOUT if quiet else None,
        text=True,
    )


def capture(args, cwd=None):
    result = subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def say(text=""):
    print(text, flush=True)


def die(text):
    print("SYNC ABORTED: " + text, file=sys.stderr, flush=True)
    raise SystemExit(1)


def load_config(path: Path) -> dict:
    config = dict(DEFAULTS)
    config.update(json.loads(path.read_text(encoding="utf-8")))
    for key in ("repo_url", "mirror_dir"):
        if not config.get(key):
            die("config is missing " + key)
    return config


def check_private(root: Path, allow_dirty: bool) -> str:
    if not (root / ".git").exists():
        die("not a git checkout: " + str(root))
    if not allow_dirty:
        dirty = capture(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"])
        if dirty:
            say(dirty)
            die("private tree has uncommitted tracked changes (commit first, or pass --allow-dirty)")
    return capture(["git", "-C", str(root), "rev-parse", "--short", "HEAD"])


def update_mirror(url: str, mirror: Path, branch: str) -> None:
    if not (mirror / ".git").exists():
        say("cloning " + url + " -> " + str(mirror))
        mirror.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", "--quiet", url, str(mirror)], quiet=False)
    run(["git", "-C", str(mirror), "fetch", "--quiet", "origin"], check=False)
    has_remote = run(["git", "-C", str(mirror), "rev-parse", "--verify", "--quiet", "origin/" + branch], check=False)
    if has_remote.returncode != 0:
        # A brand-new repository has no commits yet: start an orphan branch and
        # let the first sync create it.
        run(["git", "-C", str(mirror), "checkout", "--quiet", "--orphan", branch], check=False)
        return
    run(["git", "-C", str(mirror), "checkout", "--quiet", branch])
    pull = run(["git", "-C", str(mirror), "pull", "--quiet", "--ff-only", "origin", branch], check=False)
    if pull.returncode != 0:
        die("public checkout diverged from origin/" + branch + "; reconcile " + str(mirror) + " first")
    if capture(["git", "-C", str(mirror), "status", "--porcelain"]):
        die("public checkout has local changes; commit or discard them first")


def export(config: dict, stage: Path) -> int:
    command = [sys.executable, str(HERE / "export_allowlist.py"),
               "--repo", config["private_repo"], "--output", str(stage)]
    for prefix in config.get("include", []):
        command += ["--include", prefix]
    for name in config.get("root_files", []):
        command += ["--root-file", name]
    for old, new in config.get("renames", {}).items():
        command += ["--rename", old + "=" + new]
    licence = config.get("license")
    if licence:
        command += ["--license-from", licence["from"], "--license-to", licence.get("to", "LICENSE")]
    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode != 0:
        say(result.stdout + result.stderr)
        die("allowlist export failed")
    say(result.stdout.strip())
    return len(list(stage.rglob("*")))


def gate(stage: Path, config: dict, gate_config: Path | None) -> None:
    command = [sys.executable, str(HERE / "scan.py"), str(stage)]
    if gate_config:
        command += ["--config", str(gate_config)]
    for name in config.get("allow_patterns", []):
        command += ["--allow", name]
    result = subprocess.run(command, text=True, capture_output=True)
    say(result.stdout.strip())
    if result.returncode != 0:
        die("leak gate found unexpected personal data in the export")


def tree_entries(root: Path, protect: set[str]) -> dict[str, str]:
    """Map relative path to a comparable digest (bytes or symlink target)."""
    entries = {}
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if any(part in protect for part in rel.parts):
            continue
        if path.is_symlink():
            entries[rel.as_posix()] = "link:" + os.readlink(path)
        elif path.is_file():
            entries[rel.as_posix()] = "sha:" + str(hash(path.read_bytes()))
    return entries


def preview_changes(stage: Path, mirror: Path, protect: set[str]) -> dict[str, list[str]]:
    """Describe what mirroring would change without touching the checkout."""
    wanted = tree_entries(stage, protect)
    current = tree_entries(mirror, protect)
    added = sorted(set(wanted) - set(current))
    removed = sorted(set(current) - set(wanted))
    modified = sorted(name for name in set(wanted) & set(current) if wanted[name] != current[name])
    return {"added": added, "removed": removed, "modified": modified}


def mirror_tree(stage: Path, mirror: Path, protect: set[str]) -> list[str]:
    """Copy the stage over the mirror and delete files that are no longer exported."""
    wanted = set()
    for source in stage.rglob("*"):
        if source.is_dir() and not source.is_symlink():
            continue
        rel = source.relative_to(stage)
        wanted.add(rel.as_posix())
        target = mirror / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink() or target.exists():
            target.unlink()
        if source.is_symlink():
            os.symlink(os.readlink(source), target)
            continue
        shutil.copy2(source, target)
    removed = []
    for target in sorted(mirror.rglob("*")):
        if target.is_dir():
            continue
        rel = target.relative_to(mirror)
        if rel.parts[0] in protect:
            continue
        if rel.as_posix() not in wanted:
            target.unlink()
            removed.append(rel.as_posix())
    for directory in sorted(mirror.rglob("*"), reverse=True):
        if not directory.is_dir() or any(part in protect for part in directory.relative_to(mirror).parts):
            continue
        if not any(directory.iterdir()):
            directory.rmdir()
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish a sanitized public mirror of a private repository.")
    parser.add_argument("--config", required=True, help="mirror.json describing the repository pair")
    parser.add_argument("--dry-run", action="store_true", help="export, scan and stage, but do not commit")
    parser.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    parser.add_argument("--allow-dirty", action="store_true", help="tolerate uncommitted private changes")
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    config = load_config(config_path)
    private = Path(config.get("private_repo", ".")).resolve()
    mirror = Path(config["mirror_dir"]).expanduser().resolve()
    branch = config["branch"]
    protect = set(config.get("protect", [".git", ".github"]))

    sha = check_private(private, args.allow_dirty)
    update_mirror(config["repo_url"], mirror, branch)

    workdir = Path(tempfile.mkdtemp(prefix="public-mirror-"))
    try:
        stage = workdir / "source"
        stage.mkdir()
        config["private_repo"] = str(private)
        export(config, stage)
        gate_config = config.get("gate_config")
        gate(stage, config, Path(gate_config).resolve() if gate_config else None)
        if args.dry_run:
            changes = preview_changes(stage, mirror, protect)
            say("")
            say("dry run, nothing written to " + str(mirror))
            for label in ("added", "modified", "removed"):
                names = changes[label]
                say("  " + label + ": " + str(len(names)))
                for name in names[:10]:
                    say("    " + name)
                if len(names) > 10:
                    say("    … " + str(len(names) - 10) + " more")
            return 0
        removed = mirror_tree(stage, mirror, protect)
        if removed:
            say("removed " + str(len(removed)) + " stale file(s): " + ", ".join(removed[:8]))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    if not capture(["git", "-C", str(mirror), "status", "--porcelain"]):
        say("")
        say("public repository already matches the export; nothing to publish")
        return 0

    say("")
    say("changes to publish:")
    run(["git", "-C", str(mirror), "add", "-A"])
    say(capture(["git", "-C", str(mirror), "status", "--short"]))
    say(capture(["git", "-C", str(mirror), "diff", "--cached", "--stat"]).splitlines()[-1])

    if args.dry_run:
        run(["git", "-C", str(mirror), "reset", "--quiet"])
        say("")
        say("dry run: staged in " + str(mirror) + ", nothing committed or pushed")
        return 0

    if not args.yes:
        answer = input("commit and push to " + config["repo_url"] + " " + branch + "? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            run(["git", "-C", str(mirror), "reset", "--quiet"])
            say("cancelled")
            return 0

    author = config.get("author", {})
    message = config.get("message_prefix", DEFAULTS["message_prefix"]) + " " + sha
    run(["git", "-C", str(mirror), "-c", "user.name=" + author.get("name", "public-mirror"),
         "-c", "user.email=" + author.get("email", "public-mirror@users.noreply.github.com"),
         "commit", "--quiet", "-m", message])
    commit = capture(["git", "-C", str(mirror), "rev-parse", "--short", "HEAD"])
    say("committed " + commit + ": " + message)

    attempts = int(config.get("push_attempts", DEFAULTS["push_attempts"]))
    for attempt in range(1, attempts + 1):
        if run(["git", "-C", str(mirror), "push", "--quiet", "origin", "HEAD:" + branch], check=False).returncode == 0:
            break
        if attempt == attempts:
            die("push failed after " + str(attempts) + " attempts; " + commit + " stays local")
        say("push attempt " + str(attempt) + " failed, retrying")
        time.sleep(3)

    remote = capture(["git", "-C", str(mirror), "ls-remote", "origin", "refs/heads/" + branch]).split()[0]
    local = capture(["git", "-C", str(mirror), "rev-parse", "HEAD"])
    if remote != local:
        die("remote branch head does not match the pushed commit")
    files = len(capture(["git", "-C", str(mirror), "ls-tree", "-r", "--name-only", "HEAD"]).splitlines())
    say("remote " + branch + " at " + commit + ", " + str(files) + " tracked files")
    say("")
    say("done: " + config["repo_url"] + " (" + commit + ")")
    return 0


if __name__ == "__main__":
    sys.exit(main())
