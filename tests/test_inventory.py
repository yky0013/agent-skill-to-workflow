import json
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from skill_workflow.inventory import discover_local


SKILL_TEXT = "---\nname: {name}\ndescription: {name} task\n---\n# {name}\n"


class LocalInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.user_home = self.root / "user"
        self.codex_home = self.root / "codex-home"
        self.user_home.mkdir()
        self.codex_home.mkdir()

    def skill(self, root: Path, folder: str, name: str) -> Path:
        path = root / folder / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(SKILL_TEXT.format(name=name), encoding="utf-8")
        return path

    def discover(self, *, projects=(), **kwargs):
        with patch("skill_workflow.inventory.Path.home", return_value=self.user_home):
            return discover_local(self.codex_home, projects=projects, **kwargs)

    def plugin(self, marketplace: str, name: str, version: str, manifest=None) -> Path:
        root = self.codex_home / "plugins" / "cache" / marketplace / name / version
        root.mkdir(parents=True, exist_ok=True)
        if manifest is not None:
            path = root / ".codex-plugin" / "plugin.json"
            path.parent.mkdir()
            if isinstance(manifest, str):
                path.write_text(manifest, encoding="utf-8")
            else:
                path.write_text(json.dumps(manifest), encoding="utf-8")
        return root

    def test_discovers_all_explicit_skill_sources_and_applies_config_disables(self):
        codex_skill = self.skill(self.codex_home / "skills", "codex", "codex-skill")
        agents_skill = self.skill(self.user_home / ".agents" / "skills", "agents", "agents-skill")
        project = self.root / "project"
        project_path_skill = self.skill(project / ".codex" / "skills", "project-codex", "project-path")
        project_name_skill = self.skill(project / ".agents" / "skills", "project-agents", "project-name")
        self.codex_home.joinpath("config.toml").write_text(
            "[skills]\n"
            "config = [\n"
            f'  {{ path = "{project_path_skill.parent.as_posix()}", enabled = false }},\n'
            '  { name = "project-name", enabled = false },\n'
            "]\n",
            encoding="utf-8",
        )

        inventory = self.discover(projects=(project,))

        by_name = {skill.name: skill for skill in inventory.catalog.skills}
        self.assertEqual(set(by_name), {"codex-skill", "agents-skill", "project-path", "project-name"})
        self.assertIs(by_name["project-path"].enabled, False)
        self.assertIs(by_name["project-name"].enabled, False)
        self.assertIsNone(by_name["codex-skill"].enabled)
        self.assertIsNone(by_name["agents-skill"].enabled)
        self.assertEqual(
            set(inventory.roots),
            {
                str(codex_skill.parents[1].absolute()),
                str(agents_skill.parents[1].absolute()),
                str(project_path_skill.parents[1].absolute()),
                str(project_name_skill.parents[1].absolute()),
            },
        )
        self.assertEqual(inventory.config_path, str((self.codex_home / "config.toml").absolute()))
        rendered = inventory.to_dict()
        self.assertEqual(set(rendered), {"catalog", "mcps", "plugins", "roots", "config_path", "issues"})
        self.assertEqual(rendered["catalog"]["schemaVersion"], 1)

    def test_codex_home_environment_override_is_honored_without_writes(self):
        skill = self.skill(self.codex_home / "skills", "environment", "environment")
        before = sorted(str(path.relative_to(self.root)) for path in self.root.rglob("*"))

        with patch.dict(os.environ, {"CODEX_HOME": str(self.codex_home)}), patch(
            "skill_workflow.inventory.Path.home", return_value=self.user_home
        ):
            inventory = discover_local()

        self.assertEqual([record.path for record in inventory.catalog.skills], [str(skill.absolute())])
        self.assertEqual(inventory.config_path, str((self.codex_home / "config.toml").absolute()))
        self.assertTrue(any(issue.code == "missing_config" for issue in inventory.issues))
        after = sorted(str(path.relative_to(self.root)) for path in self.root.rglob("*"))
        self.assertEqual(after, before)

    def test_config_mcp_records_expose_only_safe_connection_metadata(self):
        executable = (self.root / "tools" / "mcp-server.exe").as_posix()
        self.codex_home.joinpath("config.toml").write_text(
            "[mcp_servers.remote]\n"
            'url = "https://url-user:URL_PASSWORD@example.test/URL_PATH_SECRET?token=URL_QUERY_SECRET"\n'
            "enabled = false\n"
            'http_headers = { Authorization = "Bearer HEADER_SECRET" }\n'
            "[mcp_servers.local]\n"
            f'command = "{executable}"\n'
            'args = ["--token", "ARG_SECRET", "--mode", "safe"]\n'
            'env = { API_TOKEN = "ENV_SECRET", ORDINARY = "value" }\n'
            'env_vars = ["INHERITED_TOKEN", "API_TOKEN"]\n',
            encoding="utf-8",
        )

        inventory = self.discover()

        by_name = {server.name: server for server in inventory.mcps}
        self.assertEqual(set(by_name), {"local", "remote"})
        self.assertEqual(by_name["remote"].transport, "http")
        self.assertEqual(by_name["remote"].target, "https://example.test")
        self.assertEqual(by_name["remote"].details, {"hostname": "example.test"})
        self.assertIs(by_name["remote"].enabled, False)
        self.assertEqual(by_name["local"].transport, "stdio")
        self.assertEqual(by_name["local"].target, executable)
        self.assertEqual(by_name["local"].details["arg_count"], 4)
        self.assertEqual(by_name["local"].details["env_keys"], ["API_TOKEN", "INHERITED_TOKEN", "ORDINARY"])
        self.assertTrue(by_name["local"].enabled)
        serialized = json.dumps(inventory.to_dict(), ensure_ascii=False)
        for secret in (
            "URL_PASSWORD",
            "URL_PATH_SECRET",
            "URL_QUERY_SECRET",
            "HEADER_SECRET",
            "ARG_SECRET",
            "ENV_SECRET",
        ):
            self.assertNotIn(secret, serialized)

    def test_plugin_cache_uses_newest_numeric_version_and_config_policy(self):
        old_root = self.plugin(
            "market",
            "widget",
            "1.9.0",
            {"name": "widget", "version": "1.9.0", "description": "old", "skills": "./skills/"},
        )
        self.skill(old_root / "skills", "old", "old-plugin-skill")
        newest_manifest = {
            "name": "widget",
            "version": "1.10.0",
            "description": "newest",
            "skills": "./skills/",
            "mcpServers": "./.mcp.json",
        }
        newest_root = self.plugin("market", "widget", "1.10.0", newest_manifest)
        self.skill(newest_root / "skills", "new", "new-plugin-skill")
        newest_root.joinpath(".mcp.json").write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "plugin-server": {
                            "command": "node",
                            "args": ["--token", "PLUGIN_ARG_SECRET"],
                            "env": {"PLUGIN_TOKEN": "PLUGIN_ENV_SECRET"},
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        latest_root = self.plugin("market", "widget", "latest", newest_manifest)
        self.skill(latest_root / "skills", "alias", "latest-alias-skill")
        self.plugin("market", "broken", "3.0.0")
        cache_only = self.plugin(
            "market",
            "cache-only",
            "2.0.0",
            {
                "name": "cache-only",
                "version": "2.0.0",
                "description": "cached",
                "mcpServers": {"cached-server": {"command": "cached-command", "enabled": True}},
            },
        )
        self.codex_home.joinpath("config.toml").write_text(
            '[plugins."widget@market"]\n'
            "enabled = true\n"
            '[plugins."widget@market".mcp_servers.plugin-server]\n'
            "enabled = false\n"
            '[plugins."config-only@market"]\n'
            "enabled = false\n",
            encoding="utf-8",
        )

        inventory = self.discover()

        plugins = {plugin.id: plugin for plugin in inventory.plugins}
        self.assertEqual(set(plugins), {"broken@market", "cache-only@market", "config-only@market", "widget@market"})
        self.assertEqual(plugins["widget@market"].version, "1.10.0")
        self.assertEqual(plugins["widget@market"].root, str(newest_root.absolute()))
        self.assertTrue(plugins["widget@market"].enabled)
        self.assertIsNone(plugins["cache-only@market"].enabled)
        self.assertEqual(plugins["cache-only@market"].root, str(cache_only.absolute()))
        self.assertIs(plugins["config-only@market"].enabled, False)
        self.assertEqual(plugins["config-only@market"].root, "")
        self.assertTrue(any(issue.code == "plugin_not_cached" for issue in plugins["config-only@market"].issues))
        self.assertTrue(any(issue.code == "missing_plugin_manifest" for issue in plugins["broken@market"].issues))
        skill_names = {skill.name for skill in inventory.catalog.skills}
        self.assertIn("new-plugin-skill", skill_names)
        self.assertNotIn("old-plugin-skill", skill_names)
        self.assertNotIn("latest-alias-skill", skill_names)
        servers = {server.name: server for server in inventory.mcps}
        self.assertIs(servers["plugin-server"].enabled, False)
        self.assertEqual(servers["plugin-server"].details["arg_count"], 2)
        self.assertEqual(servers["plugin-server"].details["env_keys"], ["PLUGIN_TOKEN"])
        self.assertIsNone(servers["cached-server"].enabled)
        serialized = json.dumps(inventory.to_dict(), ensure_ascii=False)
        self.assertNotIn("PLUGIN_ARG_SECRET", serialized)
        self.assertNotIn("PLUGIN_ENV_SECRET", serialized)

    def test_malformed_toml_reports_a_generic_error_without_source_text(self):
        self.codex_home.joinpath("config.toml").write_text(
            'private_value = "TOML_SOURCE_SECRET"\n[mcp_servers.bad\n', encoding="utf-8"
        )

        inventory = self.discover()

        self.assertTrue(any(issue.code == "invalid_config" for issue in inventory.issues))
        serialized = json.dumps(inventory.to_dict(), ensure_ascii=False)
        self.assertNotIn("TOML_SOURCE_SECRET", serialized)
        self.assertNotIn("private_value", serialized)

    def test_malformed_config_records_are_visible_without_returning_values(self):
        self.plugin(
            "market",
            "cached-invalid",
            "1.0.0",
            {"name": "cached-invalid", "version": "1.0.0"},
        )
        self.codex_home.joinpath("config.toml").write_text(
            '[mcp_servers]\ninvalid = "MCP_RECORD_SECRET"\n'
            '[mcp_servers.invalid-enabled]\ncommand = "safe-command"\nenabled = "MCP_ENABLED_SECRET"\n'
            '[plugins]\n"invalid@market" = "PLUGIN_POLICY_SECRET"\n'
            '"cached-invalid@market" = "CACHED_POLICY_SECRET"\n'
            '[plugins."mcp-policy-invalid@market"]\nenabled = true\nmcp_servers = "MCP_POLICY_SECRET"\n'
            '[skills]\nconfig = [{ enabled = false, path = 42, private = "SKILL_POLICY_SECRET" }]\n',
            encoding="utf-8",
        )

        inventory = self.discover()

        self.assertEqual(inventory.mcps[0].issues[0].code, "invalid_mcp_record")
        invalid_enabled = next(record for record in inventory.mcps if record.name == "invalid-enabled")
        self.assertIsNone(invalid_enabled.enabled)
        self.assertTrue(any(issue.code == "invalid_mcp_enabled" for issue in invalid_enabled.issues))
        plugin = next(record for record in inventory.plugins if record.id == "invalid@market")
        self.assertTrue(any(issue.code == "invalid_plugin_policy" for issue in plugin.issues))
        cached = next(record for record in inventory.plugins if record.id == "cached-invalid@market")
        self.assertTrue(any(issue.code == "invalid_plugin_policy" for issue in cached.issues))
        invalid_mcp_policy = next(record for record in inventory.plugins if record.id == "mcp-policy-invalid@market")
        self.assertTrue(any(issue.code == "invalid_plugin_mcp_policy" for issue in invalid_mcp_policy.issues))
        self.assertTrue(any(issue.code == "invalid_skill_config" for issue in inventory.issues))
        serialized = json.dumps(inventory.to_dict(), ensure_ascii=False)
        for secret in (
            "MCP_RECORD_SECRET",
            "MCP_ENABLED_SECRET",
            "PLUGIN_POLICY_SECRET",
            "CACHED_POLICY_SECRET",
            "MCP_POLICY_SECRET",
            "SKILL_POLICY_SECRET",
        ):
            self.assertNotIn(secret, serialized)

    def test_config_only_plugin_mcp_policy_remains_visible_without_a_definition(self):
        self.codex_home.joinpath("config.toml").write_text(
            '[plugins."policy-only@market"]\nenabled = true\n'
            '[plugins."policy-only@market".mcp_servers.policy-server]\nenabled = false\n',
            encoding="utf-8",
        )

        inventory = self.discover()

        server = next(record for record in inventory.mcps if record.name == "policy-server")
        self.assertIs(server.enabled, False)
        self.assertEqual(server.transport, "unknown")
        self.assertEqual(server.target, "")
        self.assertTrue(any(issue.code == "missing_plugin_mcp_definition" for issue in server.issues))

    def test_malformed_plugin_files_do_not_echo_their_contents(self):
        self.plugin("market", "bad-manifest", "1.0.0", '{"value":"MANIFEST_SOURCE_SECRET"')
        plugin_root = self.plugin(
            "market",
            "bad-mcp",
            "1.0.0",
            {"name": "bad-mcp", "version": "1.0.0", "mcpServers": "./.mcp.json"},
        )
        plugin_root.joinpath(".mcp.json").write_text('{"value":"MCP_FILE_SECRET"', encoding="utf-8")

        inventory = self.discover()

        plugins = {record.id: record for record in inventory.plugins}
        self.assertTrue(any(issue.code == "invalid_plugin_manifest" for issue in plugins["bad-manifest@market"].issues))
        self.assertTrue(any(issue.code == "invalid_plugin_mcp" for issue in plugins["bad-mcp@market"].issues))
        serialized = json.dumps(inventory.to_dict(), ensure_ascii=False)
        self.assertNotIn("MANIFEST_SOURCE_SECRET", serialized)
        self.assertNotIn("MCP_FILE_SECRET", serialized)

    def test_latest_alias_is_preferred_when_no_numeric_cache_version_exists(self):
        self.plugin(
            "market",
            "alias-only",
            "beta",
            {"name": "alias-only", "version": "0.9.0", "description": "beta"},
        )
        latest = self.plugin(
            "market",
            "alias-only",
            "latest",
            {"name": "alias-only", "version": "1.0.0", "description": "latest"},
        )

        inventory = self.discover()

        plugin = next(record for record in inventory.plugins if record.id == "alias-only@market")
        self.assertEqual(plugin.version, "1.0.0")
        self.assertEqual(plugin.root, str(latest.absolute()))

    def test_portable_root_manifest_is_preferred_and_root_mcp_json_is_discovered(self):
        root = self.plugin(
            "market",
            "portable",
            "1.0.0",
            {"name": "portable", "version": "1.0.0", "description": "legacy"},
        )
        root.joinpath("plugin.json").write_text(
            json.dumps(
                {
                    "name": "portable",
                    "version": "1.0.0",
                    "description": "portable-root",
                    "skills": "./skills/",
                }
            ),
            encoding="utf-8",
        )
        self.skill(root / "skills", "portable-skill", "portable-skill")
        root.joinpath("mcp.json").write_text(
            json.dumps({"mcpServers": {"portable-server": {"command": "portable-command"}}}),
            encoding="utf-8",
        )

        inventory = self.discover()

        plugin = next(record for record in inventory.plugins if record.id == "portable@market")
        server = next(record for record in inventory.mcps if record.name == "portable-server")
        self.assertEqual(plugin.description, "portable-root")
        self.assertEqual(plugin.source, str((root / "plugin.json").absolute()))
        self.assertEqual(server.source, str((root / "mcp.json").absolute()))
        self.assertIn("portable-skill", {skill.name for skill in inventory.catalog.skills})

    def test_explicit_plugin_server_disable_is_known_when_plugin_status_is_unknown(self):
        self.plugin(
            "market",
            "partial-policy",
            "1.0.0",
            {
                "name": "partial-policy",
                "version": "1.0.0",
                "mcpServers": {"server": {"command": "server-command"}},
            },
        )
        self.codex_home.joinpath("config.toml").write_text(
            '[plugins."partial-policy@market".mcp_servers.server]\nenabled = false\n', encoding="utf-8"
        )

        inventory = self.discover()

        plugin = next(record for record in inventory.plugins if record.id == "partial-policy@market")
        server = next(record for record in inventory.mcps if record.name == "server")
        self.assertIsNone(plugin.enabled)
        self.assertIs(server.enabled, False)

    def test_non_version_cache_directories_without_manifests_are_ignored(self):
        self.plugin("market", "plugin-backup-temp", "browser")

        inventory = self.discover()

        self.assertNotIn("plugin-backup-temp@market", {record.id for record in inventory.plugins})

    def test_qualified_skill_disable_only_matches_the_named_plugin_source(self):
        user_skill = self.skill(self.codex_home / "skills", "user-task", "task")
        plugin_root = self.plugin(
            "market",
            "widget",
            "1.0.0",
            {"name": "widget", "version": "1.0.0", "skills": "./skills/"},
        )
        plugin_skill = self.skill(plugin_root / "skills", "plugin-task", "task")
        self.codex_home.joinpath("config.toml").write_text(
            '[skills]\nconfig = [{ name = "widget:task", enabled = false }]\n', encoding="utf-8"
        )

        inventory = self.discover()

        by_path = {Path(record.path).resolve(): record for record in inventory.catalog.skills}
        self.assertIs(by_path[plugin_skill.resolve()].enabled, False)
        self.assertIsNone(by_path[user_skill.resolve()].enabled)

    def test_disabled_plugin_forces_its_skills_off_after_skill_enable_rules(self):
        disabled_root = self.plugin(
            "market",
            "disabled-plugin",
            "1.0.0",
            {"name": "disabled-plugin", "version": "1.0.0", "skills": "./skills/"},
        )
        disabled_skill = self.skill(disabled_root / "skills", "task", "plugin-task")
        unknown_root = self.plugin(
            "market",
            "cache-only",
            "1.0.0",
            {"name": "cache-only", "version": "1.0.0", "skills": "./skills/"},
        )
        unknown_skill = self.skill(unknown_root / "skills", "task", "cache-task")
        self.codex_home.joinpath("config.toml").write_text(
            '[plugins."disabled-plugin@market"]\nenabled = false\n'
            '[skills]\nconfig = [{ name = "plugin-task", enabled = true }]\n',
            encoding="utf-8",
        )

        inventory = self.discover()

        by_path = {Path(record.path).resolve(): record for record in inventory.catalog.skills}
        self.assertIs(by_path[disabled_skill.resolve()].enabled, False)
        self.assertIsNone(by_path[unknown_skill.resolve()].enabled)

    def test_equivalent_config_path_keeps_skill_disabled(self):
        skill = self.skill(self.codex_home / "skills", "task-skill", "task-skill")
        alias_parent = self.codex_home / "skills" / "alias"
        alias_parent.mkdir()
        alternate = alias_parent / ".." / "task-skill" / "SKILL.md"
        self.assertEqual(alternate.resolve(), skill.resolve())
        self.codex_home.joinpath("config.toml").write_text(
            f'[skills]\nconfig = [{{path = "{alternate.as_posix()}", enabled = false}}]\n', encoding="utf-8"
        )
        inventory = self.discover()
        self.assertIs(inventory.catalog.skills[0].enabled, False)

    def test_command_target_rejects_inline_arguments_shells_and_urls_without_echoing_them(self):
        safe_path = "C:/Program Files/MCP Tools/My MCP Server.exe"
        self.codex_home.joinpath("config.toml").write_text(
            '[mcp_servers.inline]\ncommand = "node --header Bearer_HEADER_SECRET"\n'
            '[mcp_servers.shell]\ncommand = "node && echo SHELL_COMMAND_SECRET"\n'
            '[mcp_servers.url-command]\n'
            'command = "https://url-user:URL_COMMAND_PASSWORD@example.test/private?token=URL_COMMAND_QUERY"\n'
            '[mcp_servers.schemeless-url]\n'
            'command = "url-user:SCHEMELESS_PASSWORD@example.test/private?token=SCHEMELESS_QUERY"\n'
            '[mcp_servers.path]\n'
            f'command = "{safe_path}"\n'
            '[mcp_servers.name]\ncommand = "node"\n',
            encoding="utf-8",
        )

        inventory = self.discover()

        servers = {record.name: record for record in inventory.mcps}
        for name in ("inline", "shell", "url-command", "schemeless-url"):
            self.assertEqual(servers[name].target, "[unsafe command]")
            self.assertTrue(any(issue.code == "unsafe_mcp_command" for issue in servers[name].issues))
        self.assertEqual(servers["path"].target, safe_path)
        self.assertFalse(any(issue.code == "unsafe_mcp_command" for issue in servers["path"].issues))
        self.assertEqual(servers["name"].target, "node")
        serialized = json.dumps(inventory.to_dict(), ensure_ascii=False)
        for secret in (
            "Bearer_HEADER_SECRET",
            "SHELL_COMMAND_SECRET",
            "URL_COMMAND_PASSWORD",
            "URL_COMMAND_QUERY",
            "SCHEMELESS_PASSWORD",
            "SCHEMELESS_QUERY",
            "/private",
        ):
            self.assertNotIn(secret, serialized)

    def test_explicit_skill_roots_replace_default_skill_sources_but_keep_other_inventories(self):
        self.skill(self.codex_home / "skills", "default", "default-skill")
        custom_root = self.root / "custom-skills"
        custom_skill = self.skill(custom_root, "custom", "custom-skill")
        self.plugin(
            "market",
            "visible-plugin",
            "1.0.0",
            {"name": "visible-plugin", "version": "1.0.0"},
        )
        self.codex_home.joinpath("config.toml").write_text(
            '[skills]\nconfig = [{ name = "custom-skill", enabled = false }]\n'
            '[mcp_servers.visible-mcp]\ncommand = "visible-command"\n',
            encoding="utf-8",
        )

        inventory = self.discover(skill_roots=(custom_root,))

        self.assertEqual([record.path for record in inventory.catalog.skills], [str(custom_skill.absolute())])
        self.assertIs(inventory.catalog.skills[0].enabled, False)
        self.assertEqual(inventory.roots, [str(custom_root.absolute())])
        self.assertIn("visible-mcp", {record.name for record in inventory.mcps})
        self.assertIn("visible-plugin@market", {record.id for record in inventory.plugins})

    def test_atlas_uses_current_config_and_disabled_plugin_policy(self):
        plugin_root = self.plugin(
            "market",
            "disabled-plugin",
            "1.0.0",
            {"name": "disabled-plugin", "version": "1.0.0", "skills": "./skills/"},
        )
        plugin_skill = self.skill(plugin_root / "skills", "task", "atlas-task")
        atlas = self.root / "atlas.json"
        atlas.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "skills": [
                        {
                            "path": str(plugin_skill.absolute()),
                            "sha256": hashlib.sha256(plugin_skill.read_bytes()).hexdigest(),
                            "enabled": True,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        self.codex_home.joinpath("config.toml").write_text(
            '[plugins."disabled-plugin@market"]\nenabled = false\n'
            '[skills]\nconfig = [{ name = "atlas-task", enabled = true }]\n'
            '[mcp_servers.visible-mcp]\ncommand = "visible-command"\n',
            encoding="utf-8",
        )

        inventory = self.discover(atlas_path=atlas)

        self.assertEqual([record.path for record in inventory.catalog.skills], [str(plugin_skill.absolute())])
        self.assertIs(inventory.catalog.skills[0].evidence_matches, True)
        self.assertIs(inventory.catalog.skills[0].enabled, False)
        self.assertEqual(inventory.roots, [])
        self.assertIn("visible-mcp", {record.name for record in inventory.mcps})
        self.assertIn("disabled-plugin@market", {record.id for record in inventory.plugins})

    def test_explicit_roots_and_atlas_are_mutually_exclusive(self):
        with self.assertRaisesRegex(ValueError, "skill_roots.*atlas_path"):
            self.discover(skill_roots=(), atlas_path=self.root / "atlas.json")


if __name__ == "__main__":
    unittest.main()
