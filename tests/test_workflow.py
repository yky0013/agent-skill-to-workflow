import copy
from pathlib import Path
import tempfile
import unittest

from helpers import example_workflow
from skill_workflow.workflow import ordered_steps, validate_workflow


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.flow = example_workflow(self.temp.name)

    def codes(self, flow=None):
        return {i.code for i in validate_workflow(self.flow if flow is None else flow) if i.severity == "error"}

    def test_valid_dag_is_ordered_by_dependencies(self):
        self.flow["steps"].reverse()
        self.assertEqual(self.codes(), set())
        self.assertEqual([s["id"] for s in ordered_steps(self.flow)], ["prepare", "approve", "publish"])

    def test_cycle_and_missing_dependency_are_rejected(self):
        self.flow["steps"][0]["depends_on"] = ["publish"]
        self.assertIn("cycle", self.codes())
        self.flow["steps"][0]["depends_on"] = ["missing"]
        self.assertIn("dependency", self.codes())

    def test_duplicate_ids_and_disabled_source_block_validation(self):
        self.flow["steps"][2]["id"] = "prepare"
        self.flow["steps"][0]["source_enabled"] = False
        self.assertTrue({"duplicate_id", "disabled"} <= self.codes())

    def test_source_drift_and_missing_files_block_validation(self):
        source = Path(self.flow["steps"][0]["skill_path"])
        source.write_text("changed", encoding="utf-8")
        self.assertIn("source_changed", self.codes())
        source.unlink()
        self.assertIn("unreadable", self.codes())

    def test_invalid_shapes_fail_cleanly(self):
        for data in (None, [], {}, {"schemaVersion": 99}, {"schemaVersion": True}, {**self.flow, "steps": [None]}):
            with self.subTest(data=data):
                self.assertTrue(self.codes(data) if data is not None else validate_workflow(None))

    def test_review_requires_criteria_and_skill_requires_task(self):
        self.flow["steps"][1]["criteria"] = ""
        self.flow["steps"][0]["instruction"] = ""
        self.assertIn("field", self.codes())

    def test_invalid_names_are_rejected_for_export_safety(self):
        for name in ("../escape", "CON", "bad/name", "a\nname", ""):
            flow = copy.deepcopy(self.flow)
            flow["name"] = name
            self.assertIn("name", self.codes(flow))
