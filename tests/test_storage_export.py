import json
from pathlib import Path
import tempfile
import unittest

import yaml

from helpers import example_workflow
from skill_workflow.catalog import digest_bytes
from skill_workflow.exporter import export_workflow, render_skill
from skill_workflow.storage import read_json_versioned, save_json


class StorageExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.flow = example_workflow(self.root)

    def test_json_backup_and_optimistic_conflict_protect_existing_content(self):
        target = self.root / "flow.json"
        version = save_json(target, {"value": 1}, expected_digest=None)
        previous = target.read_bytes()
        data, read_version = read_json_versioned(target)
        self.assertEqual((data, read_version), ({"value": 1}, version))
        save_json(target, {"value": 2}, expected_digest=version)
        self.assertTrue(any(p.read_bytes() == previous for p in (self.root / ".workflow-backups").iterdir()))
        with self.assertRaises(ValueError):
            save_json(target, {"value": 3}, expected_digest=version)
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"value": 2})
        with self.assertRaises(ValueError):
            save_json(target, {"value": 3}, expected_digest=None)

    def test_export_contains_valid_skill_workflow_and_source_locks(self):
        target = self.root / "exported"
        export_workflow(self.flow, target)
        text = (target / "SKILL.md").read_text(encoding="utf-8")
        front = yaml.safe_load(text.split("---", 2)[1])
        self.assertEqual(front["name"], "example-flow")
        self.assertLess(text.index("prepare"), text.index("approve"))
        self.assertIn("人工审核", text)
        exported = json.loads((target / "workflow.json").read_text(encoding="utf-8"))
        self.assertEqual(exported, self.flow)
        lock = json.loads((target / "sources.lock.json").read_text(encoding="utf-8"))
        self.assertEqual(lock["sources"][0]["sha256"], self.flow["steps"][0]["skill_sha256"])

    def test_export_existing_directory_is_never_overwritten(self):
        target = self.root / "existing"
        target.mkdir()
        sentinel = target / "SKILL.md"
        sentinel.write_text("important", encoding="utf-8")
        with self.assertRaises(ValueError):
            export_workflow(self.flow, target)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "important")

    def test_source_drift_prevents_export_and_creates_no_target(self):
        Path(self.flow["steps"][0]["skill_path"]).write_text("changed", encoding="utf-8")
        target = self.root / "exported"
        with self.assertRaises(ValueError):
            export_workflow(self.flow, target)
        self.assertFalse(target.exists())

    def test_export_does_not_copy_private_source_content(self):
        text = render_skill(self.flow)
        self.assertNotIn("# Read the input", text)
        self.assertIn(self.flow["steps"][0]["skill_sha256"], text)

    def test_existing_destination_lock_prevents_mutation(self):
        target = self.root / "locked.json"
        lock = self.root / ".locked.json.workflow-lock"
        lock.write_text("another writer", encoding="utf-8")
        with self.assertRaises(ValueError):
            save_json(target, {"value": 1}, expected_digest=None)
        self.assertFalse(target.exists())
        self.assertTrue(lock.exists())
