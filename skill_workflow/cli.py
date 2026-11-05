"""CLI mutations are preview-only unless --apply is supplied explicitly."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

from .catalog import import_atlas, inspect_skill, load_json, scan_roots
from .editor import Workbench
from .exporter import export_workflow, render_skill
from .runner import complete_step, create_run, ready_steps, review_step, validate_run
from .storage import preview_json, read_json_versioned, save_json
from .workflow import require_valid, validate_workflow


def _print(data):
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _write(path, data, apply, expected=None):
    print(preview_json(path, data))
    if apply:
        save_json(path, data, expected_digest=expected)
        print(f"已写入：{Path(path).absolute()}")
    else:
        print("仅预览；确认后添加 --apply 写入。")


def build_parser():
    parser = argparse.ArgumentParser(prog="skill-workflow", description="Python 技能编排、人工审核与组合 skill 导出；不会执行技能指令。")
    sub = parser.add_subparsers(dest="command", required=True)
    gui = sub.add_parser("gui", help="打开中文桌面工作台")
    gui.add_argument("--atlas")
    gui.add_argument("--root", action="append", default=[])
    gui.add_argument("--workflow")
    scan = sub.add_parser("scan", help="只读扫描或导入历史筛查")
    scan.add_argument("roots", nargs="*")
    scan.add_argument("--atlas")
    scan.add_argument("--output")
    scan.add_argument("--apply", action="store_true")
    compose = sub.add_parser("compose", help="按顺序选择技能，生成可编辑工作流 JSON")
    compose.add_argument("name")
    compose.add_argument("--description", required=True)
    compose.add_argument("--skill", action="append", required=True)
    compose.add_argument("--review-after", type=int, action="append", default=[], help="在第 N 个技能后插入审核，可重复")
    compose.add_argument("--output", required=True)
    compose.add_argument("--apply", action="store_true")
    validate = sub.add_parser("validate", help="校验 schema、来源和依赖图")
    validate.add_argument("workflow")
    export = sub.add_parser("export", help="预览/导出组合技能到新的目录")
    export.add_argument("workflow")
    export.add_argument("destination")
    export.add_argument("--apply", action="store_true")
    run = sub.add_parser("run", help="创建人工跟踪记录，不执行技能")
    run.add_argument("workflow")
    run.add_argument("output")
    run.add_argument("--apply", action="store_true")
    status = sub.add_parser("status", help="查看运行状态与可推进步骤")
    status.add_argument("run")
    for command in ("complete", "review"):
        item = sub.add_parser(command, help="登记技能完成" if command == "complete" else "登记人工审核决定")
        item.add_argument("run")
        item.add_argument("step_id")
        if command == "review":
            item.add_argument("decision", choices=("approved", "rejected"))
        else:
            item.add_argument("--artifact", action="append", default=[])
        item.add_argument("--note", required=True)
        item.add_argument("--apply", action="store_true")
    restore = sub.add_parser("restore", help="预览/恢复工作流或运行 JSON 备份")
    restore.add_argument("backup")
    restore.add_argument("destination")
    restore.add_argument("--apply", action="store_true")
    return parser


def main(argv=None):
    # UTF-8 JSON is stable when redirected on Windows and when consumed by other tools.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    try:
        if args.command == "gui":
            from .gui import launch
            launch(roots=args.root, atlas=args.atlas, workflow_path=args.workflow)
        elif args.command == "scan":
            if args.atlas and args.roots:
                raise ValueError("请选择扫描目录或 --atlas，不要混用")
            if not args.atlas and not args.roots:
                raise ValueError("请提供至少一个技能根目录或 --atlas")
            catalog = import_atlas(args.atlas) if args.atlas else scan_roots(args.roots)
            data = catalog.to_dict()
            if args.output:
                _write(args.output, data, args.apply)
            else:
                _print(data)
            all_issues = catalog.issues + [i for skill in catalog.skills for i in skill.issues]
            return 2 if any(i.severity == "error" for i in all_issues) else 0
        elif args.command == "compose":
            if any(n < 1 or n > len(args.skill) for n in args.review_after):
                raise ValueError("--review-after 必须指向已有技能序号（从 1 开始）")
            model = Workbench()
            model.workflow.update(name=args.name, description=args.description)
            for index, source in enumerate(args.skill, 1):
                model.add_skill(inspect_skill(source))
                if index in args.review_after:
                    model.add_review()
            require_valid(model.workflow)
            _write(args.output, model.workflow, args.apply)
        elif args.command == "validate":
            issues = validate_workflow(load_json(args.workflow))
            _print({"valid": not any(i.severity == "error" for i in issues), "issues": [asdict(i) for i in issues]})
            return 2 if any(i.severity == "error" for i in issues) else 0
        elif args.command == "export":
            workflow = load_json(args.workflow)
            print(render_skill(workflow))
            print(f"目标：{Path(args.destination).absolute()}\n文件：SKILL.md, workflow.json, sources.lock.json")
            if args.apply:
                export_workflow(workflow, args.destination)
                print("组合技能已导出。未自动安装。")
            else:
                print("仅预览；确认后添加 --apply 导出。")
        elif args.command == "run":
            _write(args.output, create_run(load_json(args.workflow)), args.apply)
        elif args.command == "status":
            run = load_json(args.run)
            validate_run(run)
            _print({"id": run["id"], "status": run["status"], "ready_steps": ready_steps(run), "states": run["states"]})
        elif args.command in ("complete", "review"):
            run, version = read_json_versioned(args.run)
            if args.command == "complete":
                complete_step(run, args.step_id, args.note, args.artifact)
            else:
                review_step(run, args.step_id, args.decision, args.note)
            _write(args.run, run, args.apply, version)
        elif args.command == "restore":
            data = load_json(args.backup)
            if isinstance(data, dict) and "workflow" in data:
                validate_run(data)
            else:
                require_valid(data, check_sources=False)
            version = read_json_versioned(args.destination)[1] if Path(args.destination).exists() else None
            _write(args.destination, data, args.apply, version)
        return 0
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
