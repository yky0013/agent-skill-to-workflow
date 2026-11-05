"""Render a reusable instruction skill and export it without copying source skills."""

from pathlib import Path
import tempfile

import yaml

from .storage import ensure_plain_path, exclusive_destination, json_bytes
from .workflow import ordered_steps, require_valid


def render_skill(workflow) -> str:
    warnings = require_valid(workflow)
    front = yaml.safe_dump({"name": workflow["name"], "description": workflow["description"]}, allow_unicode=True, sort_keys=False).strip()
    lines = ["---", front, "---", "", f"# {workflow['name']}", "", workflow["description"], "",
             "## 执行约定", "",
             "1. 先读取 workflow.json 和 sources.lock.json，核对每个来源的绝对路径及 SHA-256。来源缺失或变化时停止，要求重新核对并导出。",
             "2. 按依赖顺序读取并遵循对应 SKILL.md，结合本步骤任务和上游产物执行。这里列出的是指令，不是可直接执行的脚本。",
             "3. 每个技能步骤先检查输入，完成后报告实际产物及验证证据；缺失输入或失败时停止下游，不得虚构完成。",
             "4. 到达人工审核步骤时，展示待审产物、证据和审核标准，等待用户明确回复本次运行通过。沉默、历史授权和历史通过均不构成本次通过。",
             "5. 审核退回时，记录原因并补充或修订产物，重新请求审核；只有本次明确通过才可推进依赖该节点的步骤。",
             "6. 每次运行分别记录步骤状态、产物引用、用户审核决定及说明。状态记录不等同于模型执行日志或实验验证。", "",
             "本技能依赖本机原技能路径；跨设备必须重新选择来源并导出。仅锁定主 SKILL.md，不锁定全部配套资源。", ""]
    if warnings:
        lines.extend(["## 来源静态检查提示", ""])
        lines.extend(f"- {i.message}" for i in warnings)
        lines.append("")
    for index, step in enumerate(ordered_steps(workflow), 1):
        lines.extend([f"## {index}. {step['title']} ({step['id']})", "",
                      f"类型：{'人工审核' if step['kind'] == 'review' else '技能步骤'}",
                      f"前置步骤：{', '.join(step['depends_on']) or '无；由用户提供初始输入'}", "",
                      step["instruction"], ""])
        if step["kind"] == "skill":
            lines.extend([f"来源路径：{step['skill_path']}", f"SHA-256：{step['skill_sha256']}", ""])
        else:
            lines.extend(["审核标准：", step["criteria"], "", "**停止并等待本次人工明确通过。退回或未答复时不得执行下游。**", ""])
        lines.append("预期产物：" + ("；".join(step.get("outputs", [])) or "步骤结果与验证说明"))
        lines.append("")
    return "\n".join(lines)


def export_workflow(workflow, destination):
    rendered = render_skill(workflow)
    destination = Path(destination).expanduser().absolute()
    ensure_plain_path(destination)
    if not destination.parent.is_dir():
        raise ValueError(f"导出父目录不存在：{destination.parent}")
    sources = {}
    for step in ordered_steps(workflow):
        if step["kind"] == "skill":
            sources[step["skill_path"]] = {"path": step["skill_path"], "sha256": step["skill_sha256"]}
    contents = {"SKILL.md": rendered.encode("utf-8"), "workflow.json": json_bytes(workflow),
                "sources.lock.json": json_bytes({"schemaVersion": 1, "sources": list(sources.values())})}
    with exclusive_destination(destination):
        if destination.exists():
            raise ValueError("导出目录已存在；请选择新的目录，原内容不会被覆盖")
        staging = Path(tempfile.mkdtemp(prefix=".workflow-export-", dir=destination.parent))
        try:
            for name, payload in contents.items():
                (staging / name).write_bytes(payload)
            require_valid(workflow)
            # rename does not merge directories; the application lock serializes writers.
            staging.rename(destination)
        finally:
            if staging.exists():
                for name in contents:
                    (staging / name).unlink(missing_ok=True)
                staging.rmdir()
    return destination
