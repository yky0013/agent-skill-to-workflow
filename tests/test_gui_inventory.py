import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from skill_workflow.gui import App


class GuiInventoryTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.codex = self.home / ".codex"
        skill = self.codex / "skills" / "actual-skill" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("---\nname: actual-skill\ndescription: Real discovered test skill\n---\n# Task\n", encoding="utf-8")
        (self.codex / "config.toml").write_text('[mcp_servers.example]\ncommand="python"\nenabled=true\n[plugins."example-plugin@test-market"]\nenabled=false\n', encoding="utf-8")
        manifest = self.codex / "plugins/cache/test-market/example-plugin/1.0.0/.codex-plugin/plugin.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({"name": "example-plugin", "version": "1.0.0", "description": "Test plugin"}), encoding="utf-8")

    def settle(self, app):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            self.root.update()
            if app.inventory is not None and not app._scanning:
                return
            time.sleep(0.01)
        self.fail("Initial inventory did not complete")

    def test_default_startup_populates_skill_mcp_and_plugin_lists(self):
        with patch("pathlib.Path.home", return_value=self.home), patch.dict("os.environ", {"CODEX_HOME": str(self.codex)}):
            app = App(self.root)
            self.settle(app)
        self.assertEqual(app.notebook.select(), str(app.catalog_tab))
        self.assertTrue(any(app.catalog_tree.item(i, "values")[0] == "actual-skill" for i in app.catalog_tree.get_children()))
        self.assertTrue(any(app.mcp_tree.item(i, "values")[0] == "example" for i in app.mcp_tree.get_children()))
        self.assertTrue(any(app.plugin_tree.item(i, "values")[0] == "example-plugin" for i in app.plugin_tree.get_children()))
        self.assertIn("MCP", app.inventory_summary.get())

    def test_search_changes_list_without_hiding_other_inventories(self):
        with patch("pathlib.Path.home", return_value=self.home):
            app = App(self.root, codex_home=self.codex)
            self.settle(app)
        app.query.set("no-match")
        self.assertEqual(app.catalog_tree.get_children(), ())
        self.assertTrue(app.mcp_tree.get_children())
        app.query.set("actual")
        self.assertEqual(len(app.catalog_tree.get_children()), 1)

    def test_custom_roots_keep_configured_skill_disables(self):
        config = self.codex / "config.toml"
        config.write_text(config.read_text(encoding="utf-8") + '\n[[skills.config]]\nname="actual-skill"\nenabled=false\n', encoding="utf-8")
        with patch("pathlib.Path.home", return_value=self.home):
            app = App(self.root, codex_home=self.codex, autoload=False)
            app.roots = [str(self.codex / "skills")]
            app.source_mode = "roots"
            app.load_initial_inventory()
            self.settle(app)
        self.assertIs(app.catalog.skills[0].enabled, False)
        with self.assertRaises(ValueError):
            app.add_selected_skill()

    def test_changing_roots_during_startup_keeps_mcp_and_plugin_lists(self):
        import threading
        from skill_workflow.inventory import discover_local
        entered, release = threading.Event(), threading.Event()
        custom = self.home / "custom"
        custom.mkdir()
        (custom / "SKILL.md").write_text("---\nname: custom\ndescription: Custom task\n---\n", encoding="utf-8")
        calls = []
        def slow_discovery(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                entered.set()
                release.wait(3)
            return discover_local(**kwargs)
        with patch("pathlib.Path.home", return_value=self.home), patch("skill_workflow.gui.discover_local", side_effect=slow_discovery):
            app = App(self.root, codex_home=self.codex)
            deadline = time.monotonic() + 2
            while not entered.is_set() and time.monotonic() < deadline:
                self.root.update()
                time.sleep(0.01)
            self.assertTrue(entered.is_set())
            with patch("skill_workflow.gui.filedialog.askdirectory", return_value=str(custom)):
                app.choose_root()
            release.set()
            self.settle(app)
        self.assertEqual([s.name for s in app.catalog.skills], ["custom"])
        self.assertEqual(len(app.mcp_tree.get_children()), 1)
        self.assertEqual(len(app.plugin_tree.get_children()), 1)
