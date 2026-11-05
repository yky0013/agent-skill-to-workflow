import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from skill_workflow.catalog import import_atlas, scan_roots


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def skill(self, folder, text=None):
        path = self.root / folder / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text or "---\nname: example\ndescription: Example task\n---\n# Example\n", encoding="utf-8")
        return path

    def test_same_name_skills_keep_distinct_path_ids_and_report_overlap(self):
        self.skill("first")
        self.skill("second")
        catalog = scan_roots([self.root, self.root / "first"])
        self.assertEqual(len(catalog.skills), 2)
        self.assertEqual(len({s.id for s in catalog.skills}), 2)
        self.assertTrue(all(any(i.code == "duplicate_name" for i in s.issues) for s in catalog.skills))

    def test_safe_yaml_block_description_and_missing_local_resource(self):
        self.skill("good", "---\nname: good\ndescription: >-\n  Read papers\n  carefully\n---\n[missing](references/no.md)\n[web](https://example.org)\n")
        skill = scan_roots([self.root]).skills[0]
        self.assertEqual(skill.description, "Read papers carefully")
        self.assertEqual([i.code for i in skill.issues], ["missing_resource"])
        self.assertEqual(skill.issues[0].line, 7)

    def test_invalid_yaml_is_visible_and_never_executed(self):
        self.skill("bad", "---\nname: !!python/object/apply:os.system ['echo forbidden']\n---\n")
        skill = scan_roots([self.root]).skills[0]
        self.assertTrue(any(i.code == "frontmatter" and i.severity == "error" for i in skill.issues))

    def test_dependency_directories_are_not_discovered(self):
        self.skill("real")
        self.skill("real/node_modules/trace")
        self.skill(".venv/cached")
        self.assertEqual(len(scan_roots([self.root]).skills), 1)

    def test_missing_root_is_reported_instead_of_empty_success(self):
        catalog = scan_roots([self.root / "absent"])
        self.assertFalse(catalog.skills)
        self.assertEqual(catalog.issues[0].code, "missing_root")

    def test_atlas_preserves_historical_evidence_but_flags_changed_sources(self):
        path = self.skill("source")
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        atlas = self.root / "atlas.json"
        atlas.write_text(json.dumps({"schemaVersion": 1, "capturedAt": "2026-10-31", "skills": [{
            "path": str(path), "sha256": before, "enabled": False,
            "historical": {"status": "pass", "date": "2026-10-28"},
            "references": [{"kind": "call", "target": "other", "line": 9}],
        }]}), encoding="utf-8")
        path.write_text(path.read_text(encoding="utf-8") + "changed\n", encoding="utf-8")
        skill = import_atlas(atlas).skills[0]
        self.assertEqual(skill.historical["status"], "pass")
        self.assertFalse(skill.evidence_matches)
        self.assertEqual(skill.references, [])
        self.assertFalse(skill.enabled)
        self.assertTrue(any(i.code == "source_changed" for i in skill.issues))

    def test_atlas_missing_source_does_not_become_healthy_snapshot(self):
        atlas = self.root / "atlas.json"
        atlas.write_text(json.dumps({"schemaVersion": 1, "skills": [{"path": str(self.root / "lost/SKILL.md"), "name": "lost"}]}), encoding="utf-8")
        self.assertTrue(any(i.code == "unreadable" for i in import_atlas(atlas).skills[0].issues))

    def test_visibility_disabled_with_unknown_enabled_is_still_blocked(self):
        path = self.skill("disabled")
        atlas = self.root / "atlas.json"
        atlas.write_text(json.dumps({"schemaVersion": 1, "skills": [{"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "enabled": None, "visibility": "disabled"}]}), encoding="utf-8")
        skill = import_atlas(atlas).skills[0]
        self.assertIs(skill.enabled, False)
        self.assertEqual(skill.visibility, "disabled")

    def test_conflicting_duplicate_atlas_records_are_not_silently_dropped(self):
        path = self.skill("conflict")
        atlas = self.root / "atlas.json"
        records = [{"path": str(path), "enabled": True}, {"path": str(path), "enabled": False}]
        atlas.write_text(json.dumps({"schemaVersion": 1, "skills": records}), encoding="utf-8")
        with self.assertRaises(ValueError):
            import_atlas(atlas)

    def test_atlas_schema_and_relative_source_paths_are_rejected(self):
        atlas = self.root / "atlas.json"
        for content in ({"schemaVersion": 9, "skills": []}, {"schemaVersion": 1, "skills": [{"path": "../../SKILL.md"}]}):
            atlas.write_text(json.dumps(content), encoding="utf-8")
            with self.assertRaises(ValueError):
                import_atlas(atlas)


if __name__ == "__main__":
    unittest.main()
