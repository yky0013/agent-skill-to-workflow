from pathlib import Path

from skill_workflow.catalog import inspect_skill


def example_workflow(root):
    path = Path(root) / "source" / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("---\nname: source\ndescription: Process an input\n---\n# Read the input\n", encoding="utf-8")
    skill = inspect_skill(path)
    def task(identifier, deps):
        return {"id": identifier, "kind": "skill", "title": identifier, "depends_on": deps,
                "instruction": "处理输入并核查结果", "outputs": ["report.md"],
                "skill_path": skill.path, "skill_sha256": skill.sha256}
    return {"schemaVersion": 1, "name": "example-flow", "description": "用于有人工审核的示例任务",
            "steps": [task("prepare", []),
                      {"id": "approve", "kind": "review", "title": "人工审核", "depends_on": ["prepare"],
                       "instruction": "检查报告", "outputs": [], "criteria": "证据充分，产物可读"},
                      task("publish", ["approve"])]}
