"""Validate and upgrade skill-only workflow graphs without executing them."""

import copy
from functools import lru_cache
import re
from pathlib import Path

from .catalog import Issue, inspect_skill

_ID = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")
_NAME = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def _structural_graph(workflow, allowed_kinds):
    """Return steps/by-id after validating the graph shape independently of its payload."""
    if not isinstance(workflow, dict):
        raise ValueError("工作流必须是 JSON 对象")
    steps = workflow.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= 500:
        raise ValueError("需要 1–500 个工作流步骤")
    by_id = {}
    graph = {}
    for step in steps:
        if not isinstance(step, dict):
            raise ValueError("每个步骤必须是对象")
        sid = step.get("id")
        if not isinstance(sid, str) or not _ID.fullmatch(sid):
            raise ValueError("步骤 ID 必须以字母开头，只含字母、数字、下划线和连字符")
        if sid in by_id:
            raise ValueError(f"重复步骤 ID：{sid}")
        kind = step.get("kind")
        if not isinstance(kind, str) or kind not in allowed_kinds:
            raise ValueError(f"{sid}：不支持的步骤类型 {kind!r}")
        deps = step.get("depends_on")
        if not isinstance(deps, list) or not all(isinstance(dep, str) and _ID.fullmatch(dep) for dep in deps):
            raise ValueError(f"{sid}：depends_on 必须是步骤 ID 数组")
        if len(set(deps)) != len(deps):
            raise ValueError(f"{sid}：依赖重复")
        by_id[sid] = step
        graph[sid] = deps
    for sid, deps in graph.items():
        for dep in deps:
            if dep not in by_id:
                raise ValueError(f"{sid}：未找到依赖 {dep}")
    pending, completed = dict(graph), set()
    while pending:
        ready = [sid for sid, deps in pending.items() if set(deps) <= completed]
        if not ready:
            raise ValueError("工作流存在依赖环路")
        for sid in ready:
            completed.add(sid)
            del pending[sid]
    return steps, by_id


def upgrade_workflow(data) -> dict:
    """Copy a workflow and upgrade a legacy v1 review graph to skill-only v2."""
    if not isinstance(data, dict):
        raise ValueError("工作流必须是 JSON 对象")
    version = data.get("schemaVersion")
    if type(version) is not int or version not in (1, 2):
        raise ValueError("不支持的工作流版本；仅支持 schemaVersion 1 或 2")
    workflow = copy.deepcopy(data)
    if version == 2:
        return workflow
    steps, by_id = _structural_graph(workflow, {"skill", "review"})
    if not any(step["kind"] == "skill" for step in steps):
        raise ValueError("旧工作流仅包含人工审核步骤，无法升级；请创建包含技能的新工作流")

    @lru_cache(maxsize=None)
    def nearest_skills(sid):
        step = by_id[sid]
        if step["kind"] == "skill":
            return (sid,)
        result = []
        for dep in step["depends_on"]:
            for ancestor in nearest_skills(dep):
                if ancestor not in result:
                    result.append(ancestor)
        return tuple(result)

    upgraded_steps = []
    for step in steps:
        if step["kind"] != "skill":
            continue
        dependencies = []
        for dep in step["depends_on"]:
            for ancestor in nearest_skills(dep):
                if ancestor not in dependencies:
                    dependencies.append(ancestor)
        step["depends_on"] = dependencies
        upgraded_steps.append(step)
    workflow["schemaVersion"] = 2
    workflow["steps"] = upgraded_steps
    return workflow


def validate_workflow(workflow, *, check_sources=True) -> list[Issue]:
    issues = []
    def error(code, message, path=""):
        issues.append(Issue("error", code, message, path))
    if not isinstance(workflow, dict):
        return [Issue("error", "schema", "工作流必须是 JSON 对象")]
    if type(workflow.get("schemaVersion")) is not int or workflow["schemaVersion"] != 2:
        error("schema", "工作流 schemaVersion 必须为 2")
    name = workflow.get("name")
    if not isinstance(name, str) or not _NAME.fullmatch(name) or len(name) > 64 or name.casefold() in _RESERVED:
        error("name", "名称应为不超过 64 字符的小写字母/数字/连字符，不能使用系统保留名称")
    if not isinstance(workflow.get("description"), str) or not workflow["description"].strip():
        error("field", "需要工作流用途说明 description")
    steps = workflow.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= 500:
        error("steps", "需要 1–500 个工作流步骤")
        return issues
    ids = set()
    graph = {}
    inspected = {}
    for step in steps:
        if not isinstance(step, dict):
            error("step", "每个步骤必须是对象")
            continue
        sid = step.get("id")
        if not isinstance(sid, str) or not _ID.fullmatch(sid):
            error("id", "步骤 ID 必须以字母开头，只含字母、数字、下划线和连字符")
            continue
        if sid in ids:
            error("duplicate_id", f"重复步骤 ID：{sid}")
        ids.add(sid)
        kind = step.get("kind")
        if kind != "skill":
            error("kind", f"{sid}：kind 只能是 skill")
        for field in ("title", "instruction"):
            if not isinstance(step.get(field), str) or not step[field].strip():
                error("field", f"{sid}：需要非空 {field}")
        deps = step.get("depends_on")
        if not isinstance(deps, list) or not all(isinstance(d, str) and _ID.fullmatch(d) for d in deps):
            error("dependency", f"{sid}：depends_on 必须是步骤 ID 数组")
        else:
            if len(set(deps)) != len(deps):
                error("dependency", f"{sid}：依赖重复")
            graph[sid] = deps
        outputs = step.get("outputs", [])
        if not isinstance(outputs, list) or not all(isinstance(o, str) and o.strip() for o in outputs):
            error("field", f"{sid}：outputs 必须为非空字符串数组")
        if kind == "skill":
            path, sha = step.get("skill_path"), step.get("skill_sha256")
            if not isinstance(path, str) or not path.strip() or not Path(path).is_absolute():
                error("source", f"{sid}：skill_path 必须是本机绝对路径")
                continue
            if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
                error("source", f"{sid}：需要有效的 skill_sha256")
            if step.get("source_enabled") is False:
                error("disabled", f"{sid}：源入口在导入快照中为禁用，请核实后重新选择", path)
            if check_sources:
                if path not in inspected:
                    inspected[path] = inspect_skill(path)
                skill = inspected[path]
                issues.extend(Issue(i.severity, i.code, f"{sid}：{i.message}", i.path, i.line) for i in skill.issues)
                if skill.sha256 and skill.sha256 != sha:
                    error("source_changed", f"{sid}：源文件已变化，请核对后重新选择该技能", path)
    for sid, deps in graph.items():
        for dep in deps:
            if dep not in ids:
                error("dependency", f"{sid}：未找到依赖 {dep}")
    if len(graph) == len(steps) and not any(i.code in {"dependency", "duplicate_id"} for i in issues):
        pending, completed = dict(graph), set()
        while pending:
            ready = [sid for sid, deps in pending.items() if set(deps) <= completed]
            if not ready:
                error("cycle", "工作流存在依赖环路")
                break
            for sid in ready:
                completed.add(sid)
                del pending[sid]
    return issues


def require_valid(workflow, *, check_sources=True):
    issues = validate_workflow(workflow, check_sources=check_sources)
    errors = [i.message for i in issues if i.severity == "error"]
    if errors:
        raise ValueError("\n".join(errors))
    return issues


def ordered_steps(workflow) -> list[dict]:
    require_valid(workflow, check_sources=False)
    pending = list(workflow["steps"])
    result, done = [], set()
    while pending:
        for step in list(pending):
            if set(step["depends_on"]) <= done:
                result.append(step)
                done.add(step["id"])
                pending.remove(step)
    return result
