"""Regression tests for the allowlist exporter."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPORT = ROOT / "scripts" / "export_allowlist.py"


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


class ExportTests(unittest.TestCase):
    def make_repo(self, tmp: Path) -> Path:
        repo = tmp / "repo"
        (repo / "src").mkdir(parents=True)
        (repo / "src" / "a.txt").write_text("inside\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        git(repo, "config", "user.email", "t@example.com")
        git(repo, "config", "user.name", "t")
        return repo

    def export(self, repo: Path, out: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(EXPORT), "--repo", str(repo), "--output", str(out), "--include", "src/"],
            capture_output=True, text=True,
        )

    def test_symlink_escaping_the_repository_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = self.make_repo(tmp_path)
            outside = tmp_path / "outside.txt"
            outside.write_text("secret outside\n", encoding="utf-8")
            os.symlink(outside, repo / "src" / "escape.txt")
            git(repo, "add", "-A")
            git(repo, "commit", "-qm", "init")
            out = tmp_path / "out"
            result = self.export(repo, out)
            self.assertIn("symlink escapes", result.stdout)
            self.assertFalse((out / "src" / "escape.txt").exists())

    def test_symlink_inside_the_repository_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = self.make_repo(tmp_path)
            os.symlink("a.txt", repo / "src" / "link.txt")
            git(repo, "add", "-A")
            git(repo, "commit", "-qm", "init")
            out = tmp_path / "out"
            self.export(repo, out)
            copied = out / "src" / "link.txt"
            self.assertTrue(copied.is_symlink())
            self.assertEqual(os.readlink(copied), "a.txt")


if __name__ == "__main__":
    unittest.main()
