"""Regression tests for the mirror sync."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYNC = ROOT / "scripts" / "mirror_sync.py"


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)
    return result.stdout.strip()


class MirrorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bare = self.root / "public.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.bare)], check=True)
        self.private = self.root / "private"
        (self.private / "src").mkdir(parents=True)
        (self.private / "src" / "a.txt").write_text("hello\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(self.private)], check=True)
        git(self.private, "config", "user.email", "t@example.com")
        git(self.private, "config", "user.name", "t")
        git(self.private, "add", "-A")
        git(self.private, "commit", "-qm", "init")
        self.gate = self.root / "gate.json"
        self.gate.write_text("{}", encoding="utf-8")
        self.config = self.root / "mirror.json"
        self.config.write_text(json.dumps({
            "repo_url": str(self.bare),
            "mirror_dir": str(self.root / "work"),
            "branch": "main",
            "private_repo": str(self.private),
            "author": {"name": "bot", "email": "bot@users.noreply.github.com"},
            "include": ["src/"],
            "gate_config": str(self.gate),
            "protect": [".git"],
        }), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def sync(self, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SYNC), "--config", str(self.config), *extra],
            capture_output=True, text=True,
        )

    def test_dry_run_does_not_modify_an_existing_mirror(self):
        self.assertEqual(self.sync("--yes").returncode, 0)
        work = self.root / "work"
        before = git(work, "status", "--porcelain")
        (self.private / "src" / "b.txt").write_text("new\n", encoding="utf-8")
        git(self.private, "add", "-A")
        git(self.private, "commit", "-qm", "add b")
        result = self.sync("--dry-run")
        self.assertIn("dry run", result.stdout)
        self.assertEqual(git(work, "status", "--porcelain"), before)
        self.assertFalse((work / "src" / "b.txt").exists())

    def test_publish_is_idempotent(self):
        self.assertEqual(self.sync("--yes").returncode, 0)
        second = self.sync("--yes")
        self.assertEqual(second.returncode, 0)
        self.assertIn("already matches", second.stdout)


if __name__ == "__main__":
    unittest.main()
