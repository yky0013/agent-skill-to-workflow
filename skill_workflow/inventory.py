"""Read-only discovery of local Codex skills, MCP servers, and plugins."""

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import re
import tomllib
from urllib.parse import urlsplit

from .catalog import Catalog, Issue, import_atlas, scan_roots


@dataclass
class McpServer:
    id: str
    name: str
    source: str
    transport: str
    enabled: bool | None
    target: str
    details: dict = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)


@dataclass
class PluginRecord:
    id: str
    name: str
    version: str
    root: str
    enabled: bool | None
    description: str
    source: str
    issues: list[Issue] = field(default_factory=list)


@dataclass
class LocalInventory:
    catalog: Catalog
    mcps: list[McpServer]
    plugins: list[PluginRecord]
    roots: list[str]
    config_path: str
    issues: list[Issue] = field(default_factory=list)

    def to_dict(self) -> dict:
        result = asdict(self)
        result["catalog"] = self.catalog.to_dict()
        return result


def _absolute(path: str | Path, base: Path | None = None) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute() and base is not None:
        candidate = base / candidate
    return candidate.absolute()


def _existing_roots(codex_home: Path, projects) -> list[Path]:
    candidates = [codex_home / "skills", Path.home() / ".agents" / "skills"]
    for project in projects:
        root = _absolute(project)
        candidates.extend((root / ".agents" / "skills", root / ".codex" / "skills"))
    roots: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        candidate = candidate.absolute()
        key = os.path.normcase(str(candidate))
        if candidate.is_dir() and key not in seen:
            seen.add(key)
            roots.append(candidate)
    return roots


def _append_root(roots: list[Path], candidate: Path) -> None:
    candidate = candidate.absolute()
    key = os.path.normcase(str(candidate))
    if candidate.is_dir() and all(os.path.normcase(str(root)) != key for root in roots):
        roots.append(candidate)


def _explicit_roots(values) -> list[Path]:
    if isinstance(values, (str, Path)):
        values = (values,)
    roots: list[Path] = []
    seen: set[str] = set()
    for value in values:
        candidate = _absolute(value)
        key = os.path.normcase(str(candidate))
        if key not in seen:
            seen.add(key)
            roots.append(candidate)
    return roots


def _load_config(config_path: Path, issues: list[Issue]) -> dict:
    if not config_path.is_file():
        issues.append(Issue("warning", "missing_config", "未找到 Codex 配置文件", str(config_path)))
        return {}
    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8-sig"))
    except tomllib.TOMLDecodeError:
        issues.append(Issue("error", "invalid_config", "无法解析 config.toml（TOML 格式错误）", str(config_path)))
        return {}
    except (OSError, UnicodeError):
        issues.append(Issue("error", "unreadable_config", "无法读取 config.toml", str(config_path)))
        return {}
    if not isinstance(data, dict):
        issues.append(Issue("error", "invalid_config", "config.toml 顶层必须是表", str(config_path)))
        return {}
    return data


def _apply_skill_policies(catalog: Catalog, config: dict, config_path: Path, issues: list[Issue]) -> None:
    skills = config.get("skills", {})
    if skills is None:
        return
    if not isinstance(skills, dict):
        issues.append(Issue("warning", "invalid_skill_config", "skills 配置必须是表", str(config_path)))
        return
    records = skills.get("config", [])
    if records is None:
        return
    if not isinstance(records, list):
        issues.append(Issue("warning", "invalid_skill_config", "skills.config 必须是数组", str(config_path)))
        return
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("enabled"), bool):
            issues.append(Issue("warning", "invalid_skill_config", "忽略无效的 skills.config 记录", str(config_path)))
            continue
        name = record.get("name")
        raw_path = record.get("path")
        if not isinstance(name, str) and not isinstance(raw_path, str):
            issues.append(Issue("warning", "invalid_skill_config", "技能策略需要 name 或 path", str(config_path)))
            continue
        configured_path = _absolute(raw_path, config_path.parent) if isinstance(raw_path, str) else None
        configured_key = os.path.normcase(str(configured_path)) if configured_path else ""
        for skill in catalog.skills:
            matches_name = isinstance(name, str) and skill.name.casefold() == name.casefold()
            matches_qualified_name = False
            if isinstance(name, str) and ":" in name:
                namespace, bare_name = name.rsplit(":", 1)
                if skill.name.casefold() == bare_name.casefold():
                    try:
                        relative = Path(skill.path).resolve().relative_to(
                            (config_path.parent / "plugins" / "cache").resolve()
                        )
                    except (OSError, ValueError):
                        relative = None
                    if relative is not None and len(relative.parts) >= 3:
                        marketplace, plugin_name = relative.parts[:2]
                        matches_qualified_name = namespace.casefold() in {
                            plugin_name.casefold(),
                            f"{plugin_name}@{marketplace}".casefold(),
                        }
            skill_path = Path(skill.path).absolute()
            matches_path = bool(
                configured_path
                and configured_key
                in {
                    os.path.normcase(str(skill_path)),
                    os.path.normcase(str(skill_path.parent)),
                }
            )
            if matches_name or matches_qualified_name or matches_path:
                skill.enabled = record["enabled"]


def _apply_disabled_plugin_policies(catalog: Catalog, plugins: list[PluginRecord]) -> None:
    disabled_roots: list[Path] = []
    for plugin in plugins:
        if plugin.enabled is False and plugin.root:
            try:
                disabled_roots.append(Path(plugin.root).resolve())
            except OSError:
                continue
    for skill in catalog.skills:
        try:
            skill_path = Path(skill.path).resolve()
        except OSError:
            continue
        for root in disabled_roots:
            try:
                skill_path.relative_to(root)
            except ValueError:
                continue
            skill.enabled = False
            break


def _mcp_details(record: dict, source: str, record_issues: list[Issue]) -> dict:
    details: dict = {}
    if "args" in record:
        args = record.get("args")
        if isinstance(args, list):
            details["arg_count"] = len(args)
        else:
            record_issues.append(Issue("warning", "invalid_mcp_args", "MCP args 必须是数组", source))
    env_keys: set[str] = set()
    if "env" in record:
        env = record.get("env")
        if isinstance(env, dict):
            env_keys.update(str(key) for key in env)
        else:
            record_issues.append(Issue("warning", "invalid_mcp_env", "MCP env 必须是表", source))
    if "env_vars" in record:
        env_vars = record.get("env_vars")
        if isinstance(env_vars, list) and all(isinstance(key, str) for key in env_vars):
            env_keys.update(env_vars)
        else:
            record_issues.append(Issue("warning", "invalid_mcp_env_vars", "MCP env_vars 必须是字符串数组", source))
    if env_keys:
        details["env_keys"] = sorted(env_keys, key=str.casefold)
    return details


def _safe_url(url: str, source: str, record_issues: list[Issue]) -> tuple[str, dict]:
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        port = parsed.port
    except (TypeError, ValueError):
        hostname = None
        port = None
    scheme = parsed.scheme.casefold() if "parsed" in locals() else ""
    if not scheme or not hostname:
        record_issues.append(Issue("error", "invalid_mcp_url", "MCP URL 缺少有效协议或主机名", source))
        return "[invalid URL]", {}
    display_host = f"[{hostname}]" if ":" in hostname else hostname
    target = f"{scheme}://{display_host}"
    details: dict = {"hostname": hostname}
    if port is not None:
        target += f":{port}"
        details["port"] = port
    return target, details


def _safe_command_target(command: str, source: str, record_issues: list[Issue]) -> str:
    value = command.strip()
    windows_path = re.match(r"^[A-Za-z]:[\\/]", value) is not None
    has_url = not windows_path and re.search(r"[A-Za-z][A-Za-z0-9+.-]*://", value) is not None
    has_url_credentials = not windows_path and (
        "?" in value
        or "#" in value
        or re.search(r"[^/\\\s:]+:[^/\\\s@]+@", value) is not None
    )
    has_shell_syntax = bool(
        re.search(r"[\r\n\x00]|&&|\|\||[|;<>`]|\$\(", value)
    )
    has_inline_option = re.search(r"\s--?[A-Za-z0-9]", value) is not None
    has_separator = "/" in value or "\\" in value
    has_inline_argument = False
    if any(character.isspace() for character in value):
        if not has_separator:
            has_inline_argument = True
        else:
            last_separator = max(value.rfind("/"), value.rfind("\\"))
            tail = value[last_separator + 1 :]
            if any(character.isspace() for character in tail):
                executable_path = re.search(
                    r"(?i)\.(?:exe|com|cmd|bat|ps1|py|js|sh)$", tail
                )
                try:
                    existing_file = Path(value).is_file()
                except OSError:
                    existing_file = False
                has_inline_argument = not (executable_path or existing_file)
    if (
        not value
        or value.startswith("-")
        or has_url
        or has_url_credentials
        or has_shell_syntax
        or has_inline_option
        or has_inline_argument
    ):
        record_issues.append(
            Issue("error", "unsafe_mcp_command", "MCP command 必须是单个可执行文件名或路径", source)
        )
        return "[unsafe command]"
    return value


def _make_mcp(identifier: str, name: str, record, source: str, enabled: bool | None) -> McpServer:
    record_issues: list[Issue] = []
    if not isinstance(record, dict):
        record_issues.append(Issue("error", "invalid_mcp_record", "MCP 定义必须是表", source))
        return McpServer(identifier, name, source, "unknown", enabled, "", {}, record_issues)

    details = _mcp_details(record, source, record_issues)
    command = record.get("command")
    url = record.get("url")
    if isinstance(command, str) and command.strip():
        transport = "stdio"
        target = _safe_command_target(command, source, record_issues)
    elif isinstance(url, str):
        transport = "http"
        target, url_details = _safe_url(url, source, record_issues)
        details.update(url_details)
    else:
        transport = "unknown"
        target = ""
        record_issues.append(Issue("error", "missing_mcp_target", "MCP 定义缺少 command 或 url", source))
    return McpServer(identifier, name, source, transport, enabled, target, details, record_issues)


def _config_mcps(config: dict, config_path: Path, issues: list[Issue]) -> list[McpServer]:
    section = config.get("mcp_servers", {})
    if section is None:
        return []
    if not isinstance(section, dict):
        issues.append(Issue("error", "invalid_mcp_config", "mcp_servers 必须是表", str(config_path)))
        return []
    records: list[McpServer] = []
    for name, definition in sorted(section.items(), key=lambda item: str(item[0]).casefold()):
        enabled: bool | None = True if isinstance(definition, dict) else None
        invalid_enabled = False
        if isinstance(definition, dict) and "enabled" in definition:
            configured = definition.get("enabled")
            enabled = configured if isinstance(configured, bool) else None
            invalid_enabled = not isinstance(configured, bool)
        record = _make_mcp(f"config:{name}", str(name), definition, str(config_path), enabled)
        if invalid_enabled:
            record.issues.append(Issue("warning", "invalid_mcp_enabled", "MCP enabled 必须是布尔值", str(config_path)))
        records.append(record)
    return records


def _version_key(version: str):
    match = re.fullmatch(r"(\d+(?:\.\d+)*)(.*)", version)
    if not match:
        return None
    base = tuple(int(part) for part in match.group(1).split("."))
    suffix = match.group(2)
    suffix_numbers = tuple(int(part) for part in re.findall(r"\d+", suffix))
    return base, int(not suffix), suffix_numbers, version.casefold()


def _safe_plugin_path(root: Path, value: str) -> Path | None:
    declared = Path(value)
    if declared.is_absolute():
        return None
    try:
        resolved_root = root.resolve()
        resolved = (root / declared).resolve()
        resolved.relative_to(resolved_root)
    except (OSError, ValueError):
        return None
    return resolved


def _read_json_object(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError):
        return None
    return data if isinstance(data, dict) else None


def _plugin_policies(config: dict, config_path: Path, issues: list[Issue]) -> dict:
    section = config.get("plugins", {})
    if section is None:
        return {}
    if not isinstance(section, dict):
        issues.append(Issue("error", "invalid_plugin_config", "plugins 必须是表", str(config_path)))
        return {}
    return section


def _selected_plugin_roots(cache: Path, issues: list[Issue]) -> dict[str, tuple[Path, Path]]:
    selected: dict[str, tuple[Path, Path]] = {}
    if not cache.is_dir():
        return selected
    try:
        marketplaces = sorted((path for path in cache.iterdir() if path.is_dir()), key=lambda path: path.name.casefold())
        for marketplace in marketplaces:
            plugin_dirs = sorted((path for path in marketplace.iterdir() if path.is_dir()), key=lambda path: path.name.casefold())
            for plugin_dir in plugin_dirs:
                version_dirs = sorted((path for path in plugin_dir.iterdir() if path.is_dir()), key=lambda path: path.name.casefold())
                manifest_candidates = [
                    (
                        path,
                        path / "plugin.json"
                        if (path / "plugin.json").is_file()
                        else path / ".codex-plugin" / "plugin.json",
                    )
                    for path in version_dirs
                ]
                with_manifest = [(path, manifest) for path, manifest in manifest_candidates if manifest.is_file()]
                numeric_manifests = [
                    (key, path, manifest)
                    for path, manifest in with_manifest
                    if (key := _version_key(path.name)) is not None
                ]
                if numeric_manifests:
                    _, chosen, chosen_manifest = max(numeric_manifests, key=lambda item: item[0])
                elif with_manifest:
                    chosen, chosen_manifest = next(
                        ((path, manifest) for path, manifest in with_manifest if path.name.casefold() == "latest"),
                        min(with_manifest, key=lambda item: item[0].name.casefold()),
                    )
                else:
                    numeric_dirs = [(key, path) for path in version_dirs if (key := _version_key(path.name)) is not None]
                    if numeric_dirs:
                        chosen = max(numeric_dirs, key=lambda item: item[0])[1]
                    elif version_dirs:
                        chosen = next((path for path in version_dirs if path.name.casefold() == "latest"), None)
                        if chosen is None:
                            continue
                    else:
                        continue
                    chosen_manifest = chosen / "plugin.json"
                identity = f"{plugin_dir.name}@{marketplace.name}"
                selected[identity] = (chosen, chosen_manifest)
    except OSError:
        issues.append(Issue("warning", "plugin_cache_scan_error", "无法完整扫描插件缓存", str(cache)))
    return selected


def _policy_enabled(policy) -> bool | None:
    if isinstance(policy, dict) and isinstance(policy.get("enabled"), bool):
        return policy["enabled"]
    return None


def _plugin_policy_issues(policy, config_path: Path) -> list[Issue]:
    if policy is None:
        return []
    if not isinstance(policy, dict):
        return [Issue("warning", "invalid_plugin_policy", "插件策略必须是表", str(config_path))]
    policy_issues: list[Issue] = []
    if "enabled" in policy and not isinstance(policy.get("enabled"), bool):
        policy_issues.append(Issue("warning", "invalid_plugin_enabled", "插件 enabled 必须是布尔值", str(config_path)))
    if "mcp_servers" in policy and not isinstance(policy.get("mcp_servers"), dict):
        policy_issues.append(Issue("warning", "invalid_plugin_mcp_policy", "插件 mcp_servers 策略必须是表", str(config_path)))
    return policy_issues


def _server_policy(policy, name: str):
    if not isinstance(policy, dict):
        return None
    servers = policy.get("mcp_servers", {})
    return servers.get(name) if isinstance(servers, dict) else None


def _plugin_server_enabled(plugin_enabled: bool | None, policy, definition: dict) -> bool | None:
    if plugin_enabled is False:
        return False
    server_policy = policy
    if isinstance(server_policy, bool):
        policy_enabled = server_policy
    elif isinstance(server_policy, dict) and isinstance(server_policy.get("enabled"), bool):
        policy_enabled = server_policy["enabled"]
    else:
        policy_enabled = None
    if policy_enabled is False:
        return False
    if plugin_enabled is None:
        return None
    if policy_enabled is True:
        return True
    if isinstance(definition.get("enabled"), bool):
        return definition["enabled"]
    return True


def _policy_only_mcps(
    identity: str,
    policy,
    plugin_enabled: bool | None,
    config_path: Path,
    declared_names=(),
) -> list[McpServer]:
    if not isinstance(policy, dict) or not isinstance(policy.get("mcp_servers"), dict):
        return []
    declared = set(declared_names)
    records: list[McpServer] = []
    for raw_name, server_policy in sorted(policy["mcp_servers"].items(), key=lambda item: str(item[0]).casefold()):
        name = str(raw_name)
        if name in declared:
            continue
        enabled = _plugin_server_enabled(plugin_enabled, server_policy, {})
        records.append(
            McpServer(
                f"plugin:{identity}:{name}",
                name,
                str(config_path),
                "unknown",
                enabled,
                "",
                {},
                [Issue("warning", "missing_plugin_mcp_definition", "插件策略对应的 MCP 定义未在缓存清单中找到", str(config_path))],
            )
        )
    return records


def _manifest_mcp_mapping(
    manifest: dict, plugin_root: Path, manifest_path: Path, plugin_issues: list[Issue]
) -> tuple[dict, str]:
    declaration = manifest.get("mcpServers")
    source = manifest_path
    fallback_paths = (plugin_root / "mcp.json", plugin_root / ".mcp.json")
    if declaration is None:
        source = next((path for path in fallback_paths if path.is_file()), manifest_path)
        if source == manifest_path:
            return {}, str(manifest_path)
        declaration = _read_json_object(source)
        if declaration is None:
            plugin_issues.append(Issue("error", "invalid_plugin_mcp", "无法解析插件 MCP 文件", str(manifest_path)))
            return {}, str(source)
    if isinstance(declaration, str):
        resolved = _safe_plugin_path(plugin_root, declaration)
        if resolved is None:
            plugin_issues.append(Issue("error", "unsafe_plugin_mcp_path", "插件 MCP 路径越出插件根目录", str(manifest_path)))
            return {}, str(manifest_path)
        source = resolved
        if not source.is_file():
            fallback = next((path for path in fallback_paths if path != source and path.is_file()), None)
            if fallback is None:
                plugin_issues.append(Issue("warning", "missing_plugin_mcp", "插件声明的 MCP 文件不存在", str(manifest_path)))
                return {}, str(source)
            source = fallback
            plugin_issues.append(Issue("warning", "plugin_mcp_fallback", "使用插件根目录的兼容 MCP 文件", str(manifest_path)))
        loaded = _read_json_object(source)
        if loaded is None:
            plugin_issues.append(Issue("error", "invalid_plugin_mcp", "无法解析插件 MCP 文件", str(manifest_path)))
            return {}, str(source)
        declaration = loaded
    if not isinstance(declaration, dict):
        plugin_issues.append(Issue("error", "invalid_plugin_mcp", "插件 mcpServers 必须是表或相对文件路径", str(source)))
        return {}, str(source)
    if "mcpServers" in declaration:
        declaration = declaration.get("mcpServers")
    if not isinstance(declaration, dict):
        plugin_issues.append(Issue("error", "invalid_plugin_mcp", "插件 MCP 文件缺少 mcpServers 表", str(source)))
        return {}, str(source)
    return declaration, str(source)


def _discover_plugins(
    codex_home: Path, config: dict, config_path: Path, issues: list[Issue]
) -> tuple[list[PluginRecord], list[McpServer], list[Path]]:
    policies = _plugin_policies(config, config_path, issues)
    selected = _selected_plugin_roots(codex_home / "plugins" / "cache", issues)
    records: list[PluginRecord] = []
    mcps: list[McpServer] = []
    skill_roots: list[Path] = []
    identities = sorted(set(selected) | {str(name) for name in policies}, key=str.casefold)
    for identity in identities:
        policy = policies.get(identity)
        plugin_enabled = _policy_enabled(policy)
        policy_issues = _plugin_policy_issues(policy, config_path)
        if identity not in selected:
            name = identity.split("@", 1)[0]
            record_issues = [
                Issue("warning", "plugin_not_cached", "配置的插件未在本地缓存中找到", str(config_path)),
                *policy_issues,
            ]
            records.append(PluginRecord(identity, name, "", "", plugin_enabled, "", str(config_path), record_issues))
            mcps.extend(_policy_only_mcps(identity, policy, plugin_enabled, config_path))
            continue

        plugin_root, manifest_path = selected[identity]
        plugin_issues: list[Issue] = list(policy_issues)
        manifest = _read_json_object(manifest_path) if manifest_path.is_file() else None
        if manifest is None:
            code = "invalid_plugin_manifest" if manifest_path.is_file() else "missing_plugin_manifest"
            message = "无法解析插件清单" if manifest_path.is_file() else "插件缓存缺少 plugin.json"
            plugin_issues.append(Issue("error", code, message, str(manifest_path)))
            records.append(
                PluginRecord(identity, identity.split("@", 1)[0], plugin_root.name, str(plugin_root.absolute()), plugin_enabled, "", str(manifest_path), plugin_issues)
            )
            mcps.extend(_policy_only_mcps(identity, policy, plugin_enabled, config_path))
            continue

        raw_name = manifest.get("name")
        name = raw_name.strip() if isinstance(raw_name, str) and raw_name.strip() else identity.split("@", 1)[0]
        raw_version = manifest.get("version")
        version = raw_version.strip() if isinstance(raw_version, str) and raw_version.strip() else plugin_root.name
        description = manifest.get("description") if isinstance(manifest.get("description"), str) else ""
        skill_declaration = manifest.get("skills")
        declarations = [skill_declaration] if isinstance(skill_declaration, str) else skill_declaration
        if declarations is not None:
            if not isinstance(declarations, list) or not all(isinstance(value, str) for value in declarations):
                plugin_issues.append(Issue("warning", "invalid_plugin_skills", "插件 skills 必须是相对路径或路径数组", str(manifest_path)))
            else:
                for value in declarations:
                    root = _safe_plugin_path(plugin_root, value)
                    if root is None:
                        plugin_issues.append(Issue("error", "unsafe_plugin_skill_path", "插件技能路径越出插件根目录", str(manifest_path)))
                    elif root.is_dir():
                        _append_root(skill_roots, root)
                    else:
                        plugin_issues.append(Issue("warning", "missing_plugin_skill_root", "插件声明的技能目录不存在", str(root)))

        mcp_mapping, mcp_source = _manifest_mcp_mapping(manifest, plugin_root, manifest_path, plugin_issues)
        declared_names: set[str] = set()
        for server_name, definition in sorted(mcp_mapping.items(), key=lambda item: str(item[0]).casefold()):
            server_name = str(server_name)
            declared_names.add(server_name)
            enabled = _plugin_server_enabled(plugin_enabled, _server_policy(policy, server_name), definition if isinstance(definition, dict) else {})
            mcps.append(_make_mcp(f"plugin:{identity}:{server_name}", server_name, definition, mcp_source, enabled))
        if isinstance(policy, dict) and "mcp_servers" in policy:
            configured_servers = policy.get("mcp_servers")
            if isinstance(configured_servers, dict):
                mcps.extend(_policy_only_mcps(identity, policy, plugin_enabled, config_path, declared_names))
        records.append(
            PluginRecord(identity, name, version, str(plugin_root.absolute()), plugin_enabled, description, str(manifest_path), plugin_issues)
        )
    records.sort(key=lambda record: record.id.casefold())
    mcps.sort(key=lambda record: (record.name.casefold(), record.id.casefold()))
    return records, mcps, skill_roots


def discover_local(codex_home=None, projects=(), skill_roots=None, atlas_path=None) -> LocalInventory:
    """Discover local inventory without changing configuration or cache state."""

    if skill_roots is not None and atlas_path is not None:
        raise ValueError("skill_roots 与 atlas_path 不能同时使用")
    if codex_home is None:
        codex_home = os.environ.get("CODEX_HOME") or (Path.home() / ".codex")
    home = _absolute(codex_home)
    config_path = home / "config.toml"
    issues: list[Issue] = []
    config = _load_config(config_path, issues)
    plugins, plugin_mcps, plugin_roots = _discover_plugins(home, config, config_path, issues)
    if atlas_path is not None:
        root_paths: list[Path] = []
        catalog = import_atlas(atlas_path)
    elif skill_roots is not None:
        root_paths = _explicit_roots(skill_roots)
        catalog = scan_roots(root_paths)
    else:
        root_paths = _existing_roots(home, projects)
        for root in plugin_roots:
            _append_root(root_paths, root)
        catalog = scan_roots(root_paths)
    _apply_skill_policies(catalog, config, config_path, issues)
    _apply_disabled_plugin_policies(catalog, plugins)
    mcps = _config_mcps(config, config_path, issues) + plugin_mcps
    mcps.sort(key=lambda record: (record.name.casefold(), record.id.casefold()))
    return LocalInventory(
        catalog=catalog,
        mcps=mcps,
        plugins=plugins,
        roots=[str(path) for path in root_paths],
        config_path=str(config_path),
        issues=issues,
    )
