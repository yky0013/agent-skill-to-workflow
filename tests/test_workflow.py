import copy
from pathlib import Path
import tempfile
import unittest

from helpers import example_workflow
from skill_workflow.workflow import ordered_steps, upgrade_workflow, validate_workflow


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
        self.assertEqual([s["id"] for s in ordered_steps(self.flow)], ["prepare", "transform", "publish"])

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

    def test_only_skill_steps_with_instructions_are_supported(self):
        self.flow["steps"][1]["kind"] = "review"
        self.flow["steps"][0]["instruction"] = ""
        self.assertTrue({"field", "kind"} <= self.codes())

    def test_invalid_names_are_rejected_for_export_safety(self):
        for name in ("../escape", "CON", "bad/name", "a\nname", ""):
            flow = copy.deepcopy(self.flow)
            flow["name"] = name
            self.assertIn("name", self.codes(flow))

    def test_upgrade_legacy_reviews_rewires_to_nearest_skill_ancestors(self):
        legacy = copy.deepcopy(self.flow)
        legacy["schemaVersion"] = 1
        prepare, transform, publish = legacy["steps"]
        review_a = {"id": "review-a", "kind": "review", "title": "A", "instruction": "check",
                    "depends_on": ["prepare"], "criteria": "ok", "outputs": []}
        review_b = {"id": "review-b", "kind": "review", "title": "B", "instruction": "check",
                    "depends_on": ["transform", "review-a"], "criteria": "ok", "outputs": []}
        transform["depends_on"] = ["review-a"]
        publish["depends_on"] = ["review-b", "prepare"]
        legacy["steps"] = [prepare, review_a, transform, review_b, publish]
        before = copy.deepcopy(legacy)

        upgraded = upgrade_workflow(legacy)

        self.assertEqual(legacy, before)
        self.assertEqual(upgraded["schemaVersion"], 2)
        self.assertEqual([step["id"] for step in upgraded["steps"]], ["prepare", "transform", "publish"])
        self.assertEqual(upgraded["steps"][1]["depends_on"], ["prepare"])
        self.assertEqual(upgraded["steps"][2]["depends_on"], ["transform", "prepare"])
        self.assertEqual(self.codes(upgraded), set())

    def test_upgrade_rejects_invalid_legacy_graph_before_removing_reviews(self):
        missing = copy.deepcopy(self.flow)
        missing["schemaVersion"] = 1
        missing["steps"][1]["depends_on"] = ["missing"]
        duplicate = copy.deepcopy(self.flow)
        duplicate["schemaVersion"] = 1
        duplicate["steps"][1]["id"] = "prepare"
        cycle = copy.deepcopy(self.flow)
        cycle["schemaVersion"] = 1
        review = {"id": "review", "kind": "review", "title": "review", "instruction": "check",
                  "depends_on": ["publish"], "criteria": "ok", "outputs": []}
        cycle["steps"][2]["depends_on"] = ["review"]
        cycle["steps"].append(review)

        for invalid in (missing, duplicate, cycle):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                upgrade_workflow(invalid)

    def test_upgrade_rejects_review_only_unknown_kinds_and_versions(self):
        review_only = {"schemaVersion": 1, "name": "legacy", "description": "legacy", "steps": [
            {"id": "review", "kind": "review", "title": "review", "instruction": "check",
             "depends_on": [], "criteria": "ok", "outputs": []}
        ]}
        unknown_kind = copy.deepcopy(self.flow)
        unknown_kind["schemaVersion"] = 1
        unknown_kind["steps"][0]["kind"] = ["script"]
        unsupported = copy.deepcopy(self.flow)
        unsupported["schemaVersion"] = 3

        for invalid in (review_only, unknown_kind, unsupported):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                upgrade_workflow(invalid)

    def test_upgrade_copies_v2_without_mutating_its_graph(self):
        current = copy.deepcopy(self.flow)
        current["steps"][1]["depends_on"] = ["missing"]
        upgraded = upgrade_workflow(current)
        self.assertEqual(upgraded, current)
        self.assertIsNot(upgraded, current)
        self.assertIsNot(upgraded["steps"], current["steps"])
