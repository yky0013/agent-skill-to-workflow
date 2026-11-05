import copy
from pathlib import Path
import tempfile
import unittest

from helpers import example_workflow
from skill_workflow.catalog import inspect_skill
from skill_workflow.editor import Workbench


class EditorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.flow = example_workflow(self.temp.name)
        self.skill = inspect_skill(self.flow["steps"][0]["skill_path"])
        self.model = Workbench()

    def test_add_move_remove_maintain_linear_dependencies(self):
        self.model.add_skill(self.skill)
        self.model.add_review()
        self.model.add_skill(self.skill)
        self.model.move_step(2, -1)
        self.assertEqual([s["kind"] for s in self.model.workflow["steps"]], ["skill", "skill", "review"])
        self.model.remove_step(1)
        a, b = self.model.workflow["steps"]
        self.assertEqual(a["depends_on"], [])
        self.assertEqual(b["depends_on"], [a["id"]])

    def test_dag_edit_refuses_silent_dependency_rewiring(self):
        self.model.workflow = copy.deepcopy(self.flow)
        self.model.workflow["steps"][2]["depends_on"] = ["prepare"]
        before = copy.deepcopy(self.model.workflow)
        with self.assertRaises(ValueError):
            self.model.move_step(1, 1)
        self.assertEqual(self.model.workflow, before)

    def test_disabled_or_invalid_skills_cannot_be_added(self):
        self.skill.enabled = False
        with self.assertRaises(ValueError):
            self.model.add_skill(self.skill)
        self.assertEqual(self.model.workflow["steps"], [])

    def test_source_drift_since_selection_is_rejected(self):
        Path(self.skill.path).write_text("changed", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.model.add_skill(self.skill)
