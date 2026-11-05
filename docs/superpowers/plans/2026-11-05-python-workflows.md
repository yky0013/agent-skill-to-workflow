# Python Skill Workflows Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Deliver a Python desktop and CLI workflow builder with evidence-aware skill selection, persisted human review gates, and composite skill export.

**Architecture:** A small shared Python domain layer powers Tkinter and argparse clients. Scanning and atlas import are read-only; workflow/run persistence and export have explicit destinations and atomic writes.

**Tech Stack:** Python 3.11+, Tkinter, PyYAML >=6,<7, unittest.

**Spec:** `docs/superpowers/specs/2026-11-05-python-workflows-design.md`

## Global Constraints

- New product code is Python; preserve the existing Tauri app.
- No automatic execution of skills, shell commands, model calls, or installation.
- Distinguish current file evidence from historical runtime checks.
- Source identities are paths and SHA-256; exports fail on source drift.
- Human review cannot be completed through the ordinary step-completion path.

## Review Focus

1. Same-name skills and stale atlas hashes must not silently select another source.
2. Invalid graph/schema or missing sources must fail before creating an export/run.
3. Rejected reviews must block every dependent step, including after reload.
4. Export paths, symlinks and concurrent state writes must not overwrite unrelated files.
5. UI cancellation, stale selections and worker errors must preserve existing user work.

## Task 1: Skill inventory and evidence

Files: `skill_workflow/catalog.py`, package metadata, `tests/test_catalog.py`.

Interfaces: `scan_roots(roots) -> Catalog`; `import_atlas(path) -> Catalog`; Skill records include path/name/description/sha256/issues/historical; `Catalog.skills` and `Catalog.issues` are serializable.

- [x] Write and run failing tests for duplicate names, bad frontmatter, missing links, excluded dependency directories, stale historical atlas and missing roots.
- [x] Implement safe YAML parsing, stable path identity, link checks and atlas reconciliation.
- [x] Run `python -m unittest discover -s tests -v`; expected all catalog tests pass.

## Task 2: Workflow validation, tracking and export

Files: `skill_workflow/workflow.py`, `storage.py`, `runner.py`, `exporter.py`; corresponding tests.

Interfaces: `validate_workflow(dict) -> list[Issue]`, `ordered_steps(dict) -> list[dict]`, `create_run(workflow) -> dict`, `complete_step(run,id,note,artifacts)`, `review_step(run,id,decision,note)`, `ready_steps(run)`, `render_skill(workflow) -> str`, `export_workflow(workflow,destination)`; `save_json(path,data,expected_digest)`.

- [x] Add failing graph/schema/source-drift tests, review-gate transition tests, atomic persistence/conflict tests and export collision tests.
- [x] Implement validation, source locking, explicit state transitions, backups and staged export.
- [x] Run the full Python suite, expected all tests pass.

## Task 3: Desktop, CLI, documentation and delivery

Files: `skill_workflow/cli.py`, `gui.py`, `__main__.py`, `tests/test_cli.py`, `tests/test_gui.py`, examples, README, Python CI.

- [x] Add CLI integration tests completing an actual temporary fixture workflow and tests exercising desktop controller transitions.
- [x] Implement Chinese Tkinter catalog/workflow/run/preview views plus argparse commands using the shared core.
- [x] Run tests with actual Tk widgets and read-only import of existing local atlas (234 entries, 224 matching sources, 10 unavailable, 16 snapshot-disabled). Native screenshot layout inspection is pending: Windows desktop is locked.
- [x] Update root README with the new quick start, evidence limitations, artifact locations and retained legacy entry point; add an architecture document and examples.
- [x] Perform a fresh independent whole-branch review; fix important findings with regression tests and run the full suite. Five confirmed findings fixed; 46/46 tests passed.
- [ ] Commit the validated branch and prepare a draft PR if GitHub connectivity and permissions allow. Do not merge the default branch.
