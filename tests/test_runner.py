import json
from pathlib import Path
import tempfile
import unittest

from helpers import example_workflow
from skill_workflow.runner import complete_step, create_run, ready_steps, review_step, validate_run


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.flow = example_workflow(self.temp.name)
        self.run = create_run(self.flow)

    def test_review_gate_blocks_downstream_and_survives_reload(self):
        self.assertEqual(ready_steps(self.run), ["prepare"])
        with self.assertRaises(ValueError):
            complete_step(self.run, "publish", "premature", ["report.md"])
        complete_step(self.run, "prepare", "checked", ["report.md"])
        self.assertEqual(ready_steps(self.run), ["approve"])
        with self.assertRaises(ValueError):
            complete_step(self.run, "approve", "bypass", [])
        review_step(self.run, "approve", "rejected", "请补充证据")
        self.run = json.loads(json.dumps(self.run))
        self.assertEqual(ready_steps(self.run), ["approve"])
        with self.assertRaises(ValueError):
            complete_step(self.run, "publish", "still blocked", ["report.md"])
        review_step(self.run, "approve", "approved", "补充证据已核实")
        complete_step(self.run, "publish", "finished", ["report.md"])
        self.assertEqual(self.run["status"], "completed")
        self.assertEqual(len(self.run["events"]), 4)
        validate_run(self.run)

    def test_notes_and_output_evidence_are_required(self):
        for note, artifacts in (("", ["report.md"]), ("done", []), ("done", [""])):
            with self.assertRaises(ValueError):
                complete_step(self.run, "prepare", note, artifacts)
        self.assertEqual(self.run["states"]["prepare"]["status"], "pending")

    def test_completed_step_cannot_be_changed_or_approval_revoked(self):
        complete_step(self.run, "prepare", "done", ["report.md"])
        review_step(self.run, "approve", "approved", "reviewed")
        with self.assertRaises(ValueError):
            review_step(self.run, "approve", "rejected", "too late")
        with self.assertRaises(ValueError):
            complete_step(self.run, "prepare", "changed", ["different.md"])

    def test_loaded_run_with_impossible_dependency_state_is_rejected(self):
        self.run["states"]["publish"]["status"] = "completed"
        with self.assertRaises(ValueError):
            validate_run(self.run)

    def test_source_changes_before_next_step_are_blocked(self):
        Path(self.flow["steps"][0]["skill_path"]).write_text("changed", encoding="utf-8")
        with self.assertRaises(ValueError):
            complete_step(self.run, "prepare", "done", ["report.md"])
