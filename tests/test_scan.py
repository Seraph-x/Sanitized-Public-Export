"""Regression tests for the leak gate."""
from __future__ import annotations
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN = ROOT / "scripts" / "scan.py"

# Build token-shaped strings at runtime so this file itself stays clean when the
# gate is pointed at the repository.
GITHUB_TOKEN = "ghp_" + "a" * 36
BEARER = "Bearer " + "abcdefghijklmnopqrstuvwxyz012345"
DEMO_KEY = "sk-demo-" + "0123456789abcdefghij"


def run_scan(directory: Path, config: dict | None = None) -> dict:
    command = [sys.executable, str(SCAN), str(directory), "--json"]
    config_path = None
    if config is not None:
        # Keep the config outside the scanned tree, otherwise its own literals
        # show up as hits and the counts stop meaning anything.
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(config, handle)
            config_path = handle.name
        command += ["--config", config_path]
    result = subprocess.run(command, capture_output=True, text=True)
    report = json.loads(result.stdout)
    report["exit"] = result.returncode
    if config_path is not None:
        Path(config_path).unlink(missing_ok=True)
    return report


class ScanTests(unittest.TestCase):
    def test_placeholder_does_not_excuse_the_whole_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "notes.txt"
            target.write_text("token: " + GITHUB_TOKEN + " example.com\n", encoding="utf-8")
            report = run_scan(Path(tmp))
            self.assertEqual(report["patterns"]["github-token"]["unexpected"], 1)

    def test_domain_that_only_contains_example_is_still_a_leak(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.txt").write_text("mail: person@" + "notexample.com\n", encoding="utf-8")
            report = run_scan(Path(tmp))
            self.assertEqual(report["patterns"]["email"]["unexpected"], 1)

    def test_reserved_domain_is_a_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.txt").write_text("mail: person@example.com\n", encoding="utf-8")
            report = run_scan(Path(tmp))
            self.assertEqual(report["patterns"]["email"]["unexpected"], 0)

    def test_non_ascii_user_name_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.txt").write_text("home: /Users/" + "张三/project\n", encoding="utf-8")
            report = run_scan(Path(tmp))
            self.assertEqual(report["patterns"]["posix-home"]["unexpected"], 1)

    def test_path_without_a_user_name_is_a_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.txt").write_text("prefix: /Users/ alone\n", encoding="utf-8")
            report = run_scan(Path(tmp))
            self.assertEqual(report["patterns"]["posix-home"]["unexpected"], 0)

    def test_bearer_token_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.txt").write_text("auth: " + BEARER + "\n", encoding="utf-8")
            report = run_scan(Path(tmp))
            self.assertEqual(report["patterns"]["bearer-token"]["unexpected"], 1)

    def test_retained_value_passes_the_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.txt").write_text("key: " + DEMO_KEY + "\n", encoding="utf-8")
            report = run_scan(Path(tmp), {"retain": [DEMO_KEY]})
            self.assertEqual(report["unexpected"], 0)
            self.assertEqual(report["patterns"]["openai-key"]["retained"], 1)

    def test_findings_are_masked_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.txt").write_text("key: " + GITHUB_TOKEN + "\n", encoding="utf-8")
            report = run_scan(Path(tmp))
            snippet = report["findings"][0]["snippet"]
            self.assertNotIn(GITHUB_TOKEN, snippet)
            self.assertIn("…", snippet)

    def test_every_token_on_a_line_is_masked(self):
        second = "ghp_" + "b" * 36
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.txt").write_text("one " + GITHUB_TOKEN + " two " + second + "\n", encoding="utf-8")
            report = run_scan(Path(tmp))
            snippet = report["findings"][0]["snippet"]
            self.assertNotIn(GITHUB_TOKEN, snippet)
            self.assertNotIn(second, snippet)

    def test_a_token_containing_a_placeholder_word_is_still_a_leak(self):
        token = "ghp_dummy" + "c" * 32
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.txt").write_text("key: " + token + "\n", encoding="utf-8")
            report = run_scan(Path(tmp))
            self.assertEqual(report["patterns"]["github-token"]["unexpected"], 1)

    def test_placeholder_value_is_a_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.txt").write_text("password: <password>\n", encoding="utf-8")
            report = run_scan(Path(tmp))
            self.assertEqual(report["patterns"]["credential-assignment"]["unexpected"], 0)

if __name__ == "__main__":
    unittest.main()
