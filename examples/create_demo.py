"""Create a local, source-locked example: python examples/create_demo.py OUTPUT --apply."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from skill_workflow.catalog import inspect_skill
from skill_workflow.storage import preview_json, save_json
from skill_workflow.workflow import require_valid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent / "skills"
    steps = []
    for sid, folder, deps, output in (("extract", "extract-evidence", [], "evidence.md"), ("summarize", "write-summary", ["review"], "brief.md")):
        skill = inspect_skill(root / folder / "SKILL.md")
        steps.append({"id": sid, "kind": "skill", "title": skill.name,
                      "instruction": skill.description, "outputs": [output], "depends_on": deps,
                      "skill_path": skill.path, "skill_sha256": skill.sha256})
    steps.insert(1, {"id": "review", "kind": "review", "title": "人工核查证据", "depends_on": ["extract"],
                     "instruction": "向用户展示 evidence.md；核实后记录本次审核决定。",
                     "criteria": "每条主张有来源定位；方法条件无遗漏；未知内容已标明。", "outputs": []})
    workflow = {"schemaVersion": 1, "name": "reviewed-reading-brief", "description": "用于将用户提供的文章整理为经过人工证据审核的中文阅读简报。", "steps": steps}
    require_valid(workflow)
    print(preview_json(args.output, workflow))
    if args.apply:
        save_json(args.output, workflow, expected_digest=None)
        print(f"Saved: {args.output.absolute()}")
    else:
        print("Preview only. Add --apply to create the file; its parent directory must exist.")


if __name__ == "__main__":
    main()
