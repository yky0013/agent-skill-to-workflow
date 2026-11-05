import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from helpers import example_workflow


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.flow = example_workflow(self.root)
        self.path = self.root / "flow.json"
        self.path.write_text(json.dumps(self.flow, ensure_ascii=False), encoding="utf-8")

    def cli(self, *args, code=0):
        result = subprocess.run([sys.executable, "-X", "utf8", "-m", "skill_workflow", *map(str, args)], capture_output=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return result.stdout

    def test_full_review_workflow_cli_roundtrip(self):
        self.assertIn("source", self.cli("scan", self.root))
        self.cli("validate", self.path)
        destination = self.root / "exported"
        self.cli("export", self.path, destination)
        self.assertFalse(destination.exists())
        self.cli("export", self.path, destination, "--apply")
        run = self.root / "run.json"
        self.cli("run", self.path, run)
        self.assertFalse(run.exists())
        self.cli("run", self.path, run, "--apply")
        self.cli("complete", run, "publish", "--note", "blocked", "--artifact", "report.md", "--apply", code=2)
        self.cli("complete", run, "prepare", "--note", "ready", "--artifact", "report.md", "--apply")
        self.cli("review", run, "approve", "rejected", "--note", "fix", "--apply")
        self.assertIn("approve", self.cli("status", run))
        self.cli("review", run, "approve", "approved", "--note", "verified", "--apply")
        self.cli("complete", run, "publish", "--note", "done", "--artifact", "final.md", "--apply")
        self.assertEqual(json.loads(run.read_text(encoding="utf-8"))["status"], "completed")

    def test_preview_does_not_change_run_and_backup_can_be_restored(self):
        run = self.root / "run.json"
        self.cli("run", self.path, run, "--apply")
        original = run.read_bytes()
        self.cli("complete", run, "prepare", "--note", "ready", "--artifact", "report.md")
        self.assertEqual(run.read_bytes(), original)
        self.cli("complete", run, "prepare", "--note", "ready", "--artifact", "report.md", "--apply")
        backup = next((self.root / ".workflow-backups").iterdir())
        self.cli("restore", backup, run, "--apply")
        self.assertEqual(json.loads(run.read_text(encoding="utf-8"))["states"]["prepare"]["status"], "pending")

    def test_bad_json_produces_error_without_traceback(self):
        self.path.write_text("{broken", encoding="utf-8")
        result = subprocess.run([sys.executable, "-m", "skill_workflow", "validate", str(self.path)], capture_output=True, encoding="utf-8")
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)

    def test_scan_invalid_skill_returns_inventory_and_error_exit(self):
        Path(self.flow["steps"][0]["skill_path"]).write_text("no frontmatter", encoding="utf-8")
        self.assertIn("frontmatter", self.cli("scan", self.root, code=2))

    def test_compose_creates_source_locked_workflow_with_review(self):
        target = self.root / "composed.json"
        self.cli("compose", "composed-flow", "--description", "test", "--skill", self.flow["steps"][0]["skill_path"], "--review-after", "1", "--output", target, "--apply")
        data = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual([s["kind"] for s in data["steps"]], ["skill", "review"])
        self.cli("validate", target)

    def test_status_missing_run_id_is_readable_validation_error(self):
        from skill_workflow.runner import create_run
        run = create_run(self.flow)
        del run["id"]
        target = self.root / "broken.run.json"
        target.write_text(json.dumps(run), encoding="utf-8")
        self.cli("status", target, code=2)
