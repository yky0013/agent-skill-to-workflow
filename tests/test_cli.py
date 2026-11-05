import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

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

    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-X", "utf8", "-m", "skill_workflow", *map(str, args)], capture_output=True, encoding="utf-8", timeout=20)

    def test_full_skill_workflow_cli_roundtrip(self):
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
        self.assertIn("transform", self.cli("status", run))
        self.cli("complete", run, "transform", "--note", "converted", "--artifact", "converted.md", "--apply")
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

    def test_compose_creates_v2_skill_only_workflow(self):
        target = self.root / "composed.json"
        self.cli("compose", "composed-flow", "--description", "test", "--skill", self.flow["steps"][0]["skill_path"], "--output", target, "--apply")
        data = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(data["schemaVersion"], 2)
        self.assertEqual([s["kind"] for s in data["steps"]], ["skill"])
        self.cli("validate", target)

    def test_review_command_and_review_after_option_are_removed(self):
        run_result = self.run_cli("review", self.root / "run.json", "step", "approved", "--note", "ok")
        compose_result = self.run_cli(
            "compose", "composed-flow", "--description", "test",
            "--skill", self.flow["steps"][0]["skill_path"], "--review-after", "1",
            "--output", self.root / "composed.json",
        )
        self.assertEqual(run_result.returncode, 2)
        self.assertEqual(compose_result.returncode, 2)
        self.assertIn("invalid choice", run_result.stderr)
        self.assertIn("unrecognized arguments", compose_result.stderr)

    def test_legacy_workflow_is_upgraded_for_validate_export_and_run(self):
        legacy = copy.deepcopy(self.flow)
        legacy["schemaVersion"] = 1
        review = {"id": "review", "kind": "review", "title": "review", "instruction": "check",
                  "depends_on": ["prepare"], "criteria": "ok", "outputs": []}
        legacy["steps"][1]["depends_on"] = ["review"]
        legacy["steps"] = [legacy["steps"][0], review, *legacy["steps"][1:]]
        legacy_path = self.root / "legacy.json"
        legacy_path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")

        self.cli("validate", legacy_path)
        destination = self.root / "legacy-export"
        self.cli("export", legacy_path, destination, "--apply")
        exported = json.loads((destination / "workflow.json").read_text(encoding="utf-8"))
        self.assertEqual(exported["schemaVersion"], 2)
        self.assertEqual([step["id"] for step in exported["steps"]], ["prepare", "transform", "publish"])
        self.assertEqual(exported["steps"][1]["depends_on"], ["prepare"])
        run_path = self.root / "legacy.run.json"
        self.cli("run", legacy_path, run_path, "--apply")
        run = json.loads(run_path.read_text(encoding="utf-8"))
        self.assertEqual(run["schemaVersion"], 2)
        self.assertEqual(set(run["states"]), {"prepare", "transform", "publish"})
        self.assertEqual(json.loads(legacy_path.read_text(encoding="utf-8")), legacy)

    def test_inventory_command_accepts_custom_home_and_repeated_projects(self):
        home = self.root / "codex-home"
        first = self.root / "project-one"
        second = self.root / "project-two"
        for path in (home, first, second):
            path.mkdir()
        output = self.cli("inventory", "--codex-home", home, "--project", first, "--project", second)
        data = json.loads(output)
        self.assertTrue({"catalog", "mcps", "plugins", "roots", "config_path", "issues"} <= set(data))

    def test_gui_forwards_custom_inventory_paths(self):
        from skill_workflow.cli import main
        fake_gui = types.ModuleType("skill_workflow.gui")
        calls = []
        fake_gui.launch = lambda **kwargs: calls.append(kwargs)
        with patch.dict(sys.modules, {"skill_workflow.gui": fake_gui}):
            code = main(["gui", "--root", "skills", "--atlas", "atlas.json", "--workflow", "flow.json",
                         "--codex-home", "codex", "--project", "one", "--project", "two"])
        self.assertEqual(code, 0)
        self.assertEqual(calls, [{"roots": ["skills"], "atlas": "atlas.json", "workflow_path": "flow.json",
                                  "codex_home": Path("codex"), "projects": [Path("one"), Path("two")]}])

    def test_example_creates_two_skill_v2_workflow_without_review_language(self):
        target = self.root / "demo.json"
        result = subprocess.run([sys.executable, "-X", "utf8", "examples/create_demo.py", str(target), "--apply"],
                                capture_output=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        workflow = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(workflow["schemaVersion"], 2)
        self.assertEqual([step["id"] for step in workflow["steps"]], ["extract", "summarize"])
        self.assertEqual(workflow["steps"][1]["depends_on"], ["extract"])
        self.assertNotIn("审核", json.dumps(workflow, ensure_ascii=False))

    def test_status_missing_run_id_is_readable_validation_error(self):
        from skill_workflow.runner import create_run
        run = create_run(self.flow)
        del run["id"]
        target = self.root / "broken.run.json"
        target.write_text(json.dumps(run), encoding="utf-8")
        self.cli("status", target, code=2)

    def test_status_rejects_legacy_run_with_create_new_guidance(self):
        from skill_workflow.runner import create_run
        run = create_run(self.flow)
        run["schemaVersion"] = 1
        target = self.root / "legacy.run.json"
        target.write_text(json.dumps(run), encoding="utf-8")
        result = self.run_cli("status", target)
        self.assertEqual(result.returncode, 2)
        self.assertIn("新建运行", result.stderr)
