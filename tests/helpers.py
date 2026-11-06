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
    return {"schemaVersion": 2, "name": "example-flow", "description": "用于依次准备、转换并发布结果的示例任务",
            "steps": [task("prepare", []), task("transform", ["prepare"]), task("publish", ["transform"])]}
