import json
import copy
from pathlib import Path
import tempfile
import unittest

from helpers import example_workflow
from skill_workflow.runner import complete_step, create_run, ready_steps, validate_run


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.flow = example_workflow(self.temp.name)
        self.run = create_run(self.flow)

    def test_skill_completion_unlocks_downstream_and_survives_reload(self):
        self.assertEqual(self.run["schemaVersion"], 2)
        self.assertEqual(ready_steps(self.run), ["prepare"])
        with self.assertRaises(ValueError):
            complete_step(self.run, "publish", "premature", ["report.md"])
        complete_step(self.run, "prepare", "checked", ["report.md"])
        self.assertEqual(ready_steps(self.run), ["transform"])
        self.run = json.loads(json.dumps(self.run))
        complete_step(self.run, "transform", "converted", ["report.md"])
        self.assertEqual(ready_steps(self.run), ["publish"])
        complete_step(self.run, "publish", "finished", ["report.md"])
        self.assertEqual(self.run["status"], "completed")
        self.assertEqual(len(self.run["events"]), 3)
        validate_run(self.run)

    def test_notes_and_output_evidence_are_required(self):
        for note, artifacts in (("", ["report.md"]), ("done", []), ("done", [""])):
            with self.assertRaises(ValueError):
                complete_step(self.run, "prepare", note, artifacts)
        self.assertEqual(self.run["states"]["prepare"]["status"], "pending")

    def test_completed_step_cannot_be_changed(self):
        complete_step(self.run, "prepare", "done", ["report.md"])
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

    def test_completion_without_matching_event_cannot_unlock_downstream(self):
        complete_step(self.run, "prepare", "done", ["report.md"])
        self.run["states"]["transform"] = {"status": "completed", "note": "forged", "artifacts": ["report.md"]}
        with self.assertRaises(ValueError):
            ready_steps(self.run)

    def test_invalid_record_metadata_or_events_are_rejected(self):
        variants = []
        missing_id = copy.deepcopy(self.run)
        del missing_id["id"]
        variants.append(missing_id)
        bad_event = copy.deepcopy(self.run)
        bad_event["events"] = [{}]
        variants.append(bad_event)
        for run in variants:
            with self.subTest(run=run), self.assertRaises(ValueError):
                validate_run(run)

    def test_out_of_order_events_are_rejected(self):
        complete_step(self.run, "prepare", "done", ["report.md"])
        complete_step(self.run, "transform", "converted", ["report.md"])
        self.run["events"].reverse()
        with self.assertRaises(ValueError):
            validate_run(self.run)

    def test_non_skill_event_status_is_rejected(self):
        complete_step(self.run, "prepare", "done", ["report.md"])
        self.run["events"][0]["status"] = "approved"
        self.run["states"]["prepare"]["status"] = "approved"
        with self.assertRaises(ValueError):
            validate_run(self.run)

    def test_completed_event_requires_a_completion_note(self):
        complete_step(self.run, "prepare", "done", ["report.md"])
        self.run["events"][0]["note"] = ""
        self.run["states"]["prepare"]["note"] = ""
        with self.assertRaisesRegex(ValueError, "^完成事件缺少说明$"):
            validate_run(self.run)

    def test_legacy_run_is_rejected_without_fabricating_progress(self):
        legacy = copy.deepcopy(self.run)
        legacy["schemaVersion"] = 1
        before = copy.deepcopy(legacy)
        with self.assertRaisesRegex(ValueError, "新建运行"):
            validate_run(legacy)
        self.assertEqual(legacy, before)

    def test_boolean_schema_version_is_not_treated_as_legacy_v1(self):
        invalid = copy.deepcopy(self.run)
        invalid["schemaVersion"] = True
        with self.assertRaisesRegex(ValueError, "^不支持的运行记录格式$"):
            validate_run(invalid)
