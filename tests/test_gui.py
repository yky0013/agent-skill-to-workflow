import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from helpers import example_workflow
from skill_workflow.gui import App
from skill_workflow.catalog import Catalog, inspect_skill
from skill_workflow.runner import create_run


class GuiTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.flow = example_workflow(self.temp.name)
        self.app = App(self.root, autoload=False)

    def test_edit_save_reload_and_cancelled_preview(self):
        self.app.model.workflow = copy.deepcopy(self.flow)
        self.app.show_workflow()
        self.app.step_tree.selection_set("prepare")
        self.app.select_step()
        self.app.title_var.set("核查输入")
        self.app.commit_editor()
        target = Path(self.temp.name) / "workflow.json"
        with patch.object(self.app, "confirm_preview", return_value=False):
            self.app.save_workflow(target)
        self.assertFalse(target.exists())
        with patch.object(self.app, "confirm_preview", return_value=True):
            self.app.save_workflow(target)
        self.app.model.workflow["steps"][0]["title"] = "modified"
        self.app.load_workflow(target)
        self.assertEqual(self.app.model.workflow["steps"][0]["title"], "核查输入")

    def test_reordering_preserves_step_instruction_without_review_controls(self):
        self.app.model.workflow = copy.deepcopy(self.flow)
        self.app.show_workflow()
        self.app.step_tree.selection_set("prepare")
        self.app.select_step()
        self.app.instruction_text.delete("1.0", "end")
        self.app.instruction_text.insert("1.0", "先检查输入")
        self.app.move_step(1)
        step = next(s for s in self.app.model.workflow["steps"] if s["id"] == "prepare")
        self.assertEqual(step["instruction"], "先检查输入")
        self.assertEqual(len(self.app.model.workflow["steps"]), 3)
        self.assertFalse(hasattr(self.app, "approve_button"))
        self.assertFalse(hasattr(self.app, "criteria_text"))

    def test_switching_run_steps_preserves_unsent_notes(self):
        self.app.run = create_run(self.flow)
        self.app.refresh_run()
        self.app.note_text.insert("1.0", "未提交的执行备注")
        self.app.artifacts_text.insert("1.0", "evidence.md")
        self.app.run_tree.selection_set("transform")
        self.app.show_run_step()
        self.app.run_tree.selection_set("prepare")
        self.app.show_run_step()
        self.assertEqual(self.app.note_text.get("1.0", "end-1c"), "未提交的执行备注")
        self.assertEqual(self.app.artifacts_text.get("1.0", "end-1c"), "evidence.md")

    def test_latest_requested_scan_replaces_inflight_scan_result(self):
        import threading
        import time
        entered, release = threading.Event(), threading.Event()
        first = Catalog()
        latest = Catalog([inspect_skill(self.flow["steps"][0]["skill_path"])])
        def slow_scan():
            entered.set()
            release.wait(2)
            return first
        self.app.background_scan(slow_scan)
        self.assertTrue(entered.wait(1))
        self.app.background_scan(lambda: latest)
        release.set()
        deadline = time.monotonic() + 2
        while self.app._scanning and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertIs(self.app.catalog, latest)

    def test_close_can_preserve_unsent_run_draft(self):
        self.app.run = create_run(self.flow)
        self.app.refresh_run()
        self.app.note_text.insert("1.0", "尚未登记")
        with patch("skill_workflow.gui.messagebox.askyesno", return_value=False):
            self.app.close()
        self.assertTrue(self.root.winfo_exists())
        self.assertEqual(self.app.note_text.get("1.0", "end-1c"), "尚未登记")
