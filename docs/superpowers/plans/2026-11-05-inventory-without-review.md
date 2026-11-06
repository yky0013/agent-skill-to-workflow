# Local inventories and skill-only workflows

> User correction supersedes the earlier human-review design. Implement directly in the existing feature branch using independent bounded workers where files do not overlap.

**Goal:** Remove human-review workflow gates and make real Skills, MCP and plugin inventories visible on startup.

**Architecture:** Python-only shared inventory reader powers the GUI and a read-only CLI inventory command. Skill-only workflow schema v2 replaces the review-capable v1. v1 workflow loading removes review nodes and reconnects their prerequisite edges; old run files remain untouched and cannot be silently converted to successful execution.

## Constraints

- No changes to installed skills, live Codex config, plugin enablement or MCP servers; discovery is read-only.
- Honor CODEX_HOME; default to ~/.codex. Discover ~/.agents/skills, CODEX_HOME/skills, plugin cache skill roots, and explicit project .agents/.codex skill folders.
- MCP and plugin lists describe on-disk evidence, never imply runtime connectivity. Hide credentials: no environment values, auth headers, bearer tokens, or URL credentials/query values in returned display records.
- Launch without arguments automatically scans real local data and opens the Skills tab. Explicit roots/atlas remain supported and do not silently replace user choices.
- UI tabs: Skills, MCP, Plugins, Workflow, Run. No add-review action, criteria editor, approval/rejection buttons, review CLI command, review-after option or review instructions in new exports.
- Current JSON workflow and run schemaVersion=2. Keep source hashes, dependency validation, event replay, backup/preview/atomic saves.

## Independent task ownership

1. **Inventory module** owns only `skill_workflow/inventory.py` and `tests/test_inventory.py`.
   - Public `discover_local(codex_home=None, projects=(), skill_roots=None, atlas_path=None) -> LocalInventory`; explicit roots/atlas keep MCP/plugin metadata and the same configured disable policies.
   - `LocalInventory`: `catalog: Catalog`, `mcps: list[McpServer]`, `plugins: list[PluginRecord]`, `roots: list[str]`, `config_path: str`, `issues: list[Issue]`, `to_dict()`.
   - MCP fields: `id`, `name`, `source`, `transport`, `enabled` (bool/None), `target` (sanitized), `details` (safe dict), `issues` (list[Issue]). Plugin fields: `id`, `name`, `version`, `root`, `enabled` (bool/None), `description`, `source`, `issues` (list[Issue]).
   - Include config mcp_servers, plugin manifest MCP declarations where available, configured plugin policy, discovered manifests, and configured skill disables. Cache-only plugin status stays unknown.
   - Tests: temp homes/configs, env override, disabled sources, malformed config, missing config/empty dirs, plugin versions/dedup, missing manifests, secret redaction, no side effects.
2. **Skill-only core** owns workflow/runner/editor/exporter/cli, examples and core tests (not GUI/inventory tests).
   - `upgrade_workflow(data) -> dict` handles v1 review-node removal and graph rewiring, validating cycles/missing deps before conversion. Current v2 workflows are copied without graph mutation.
   - Remove public review APIs; `complete_step` unlocks dependent skill steps. Reject old review run records with a clear instruction to create a new run; never fabricate completion.
   - CLI gains `inventory --codex-home PATH --project PATH` using discover_local, otherwise existing scan/compose/validate/export/run/status/complete/restore continue.
   - Tests prove v2 transitions, legacy DAG migration, invalid inputs and exports without gates. Existing review-specific tests are replaced, not retained as required behavior.
3. **Parent** owns GUI, GUI tests, metadata/docs, native validation, final integration and PR update.
   - Threaded initial discovery, counts, search and source details for all inventories. Empty/error states visible; new scans preserve user edits.
   - Verify real local counts, default startup, skill/MCP/plugin tabs and skill-only export; run complete suite and build wheel.

## Status

- [x] Inventory implementation and tests
- [x] Remove review core; migrate legacy workflows
- [x] GUI auto-discovery and lists
- [x] Integration tests (84 passed) and real-data Tk list population verified. Native Skills/MCP/plugin list, search/details and skill-only controls verified after unlock on 2026-11-06; packaging performed at delivery.
- [x] Push and rewrite PR #1 around final scope; default branch remains unmerged.
