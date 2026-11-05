"""Persistent manual run ledger. No skill content or user command is executed."""

import copy
from datetime import datetime, timezone
import uuid

from .catalog import digest_bytes
from .storage import json_bytes
from .workflow import require_valid


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_run(workflow) -> dict:
    require_valid(workflow)
    return {"schemaVersion": 2, "id": uuid.uuid4().hex, "created_at": now(),
            "workflow": copy.deepcopy(workflow), "workflow_sha256": digest_bytes(json_bytes(workflow)),
            "status": "active", "states": {s["id"]: {"status": "pending", "note": "", "artifacts": []} for s in workflow["steps"]},
            "events": []}


def _satisfied(state):
    return state["status"] == "completed"


def _timestamp(value):
    if not isinstance(value, str):
        raise ValueError("运行记录缺少有效时间")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("运行记录时间格式无效") from exc
    if parsed.tzinfo is None:
        raise ValueError("运行记录时间必须包含时区")


def validate_run(run):
    if isinstance(run, dict) and type(run.get("schemaVersion")) is int and run["schemaVersion"] == 1:
        raise ValueError("旧版 schemaVersion=1 运行记录不能升级；请从升级后的工作流新建运行")
    if not isinstance(run, dict) or type(run.get("schemaVersion")) is not int or run["schemaVersion"] != 2:
        raise ValueError("不支持的运行记录格式")
    identifier = run.get("id")
    if not isinstance(identifier, str):
        raise ValueError("运行记录缺少 id")
    try:
        uuid.UUID(identifier)
    except ValueError as exc:
        raise ValueError("运行记录 id 无效") from exc
    _timestamp(run.get("created_at"))
    workflow = run.get("workflow")
    require_valid(workflow, check_sources=False)
    if run.get("workflow_sha256") != digest_bytes(json_bytes(workflow)):
        raise ValueError("运行中工作流快照已变化；请新建运行")
    states = run.get("states")
    if not isinstance(states, dict) or set(states) != {s["id"] for s in workflow["steps"]}:
        raise ValueError("运行步骤状态不完整")
    events = run.get("events")
    if not isinstance(events, list):
        raise ValueError("运行事件记录无效")
    steps = {s["id"]: s for s in workflow["steps"]}
    replay = {sid: {"status": "pending", "note": "", "artifacts": []} for sid in steps}
    for event in events:
        if not isinstance(event, dict) or set(event) != {"step_id", "status", "note", "artifacts", "at"}:
            raise ValueError("运行事件字段不完整或包含不支持的字段")
        sid = event["step_id"]
        if not isinstance(sid, str) or sid not in steps:
            raise ValueError("运行事件引用了未知步骤")
        step = steps[sid]
        if _satisfied(replay[sid]) or not all(_satisfied(replay[d]) for d in step["depends_on"]):
            raise ValueError(f"运行事件顺序非法或依赖尚未通过：{sid}")
        if event["status"] != "completed":
            raise ValueError(f"运行事件状态不符合步骤类型：{sid}")
        if not isinstance(event["note"], str) or not event["note"].strip():
            raise ValueError("完成事件缺少说明")
        _timestamp(event["at"])
        artifacts = event["artifacts"]
        if not isinstance(artifacts, list) or not all(isinstance(a, str) and a.strip() for a in artifacts):
            raise ValueError("事件产物引用格式无效")
        if step.get("outputs") and not artifacts:
            raise ValueError("事件产物不符合步骤要求")
        replay[sid] = {key: value for key, value in event.items() if key != "step_id"}
    if states != replay:
        raise ValueError("运行步骤状态与事件历史不一致，拒绝推进")
    expected_status = "completed" if all(_satisfied(s) for s in replay.values()) else "active"
    if run.get("status") != expected_status:
        raise ValueError("运行总状态与步骤状态不一致")


def ready_steps(run) -> list[str]:
    validate_run(run)
    return [s["id"] for s in run["workflow"]["steps"]
            if not _satisfied(run["states"][s["id"]]) and all(_satisfied(run["states"][d]) for d in s["depends_on"])]


def _prepare(run, sid, note):
    validate_run(run)
    step = next((s for s in run["workflow"]["steps"] if s["id"] == sid), None)
    if step is None:
        raise ValueError("未找到要完成的技能步骤")
    if not isinstance(note, str) or not note.strip():
        raise ValueError("必须填写完成说明")
    if sid not in ready_steps(run):
        raise ValueError("前置步骤尚未通过，或该步骤已结束")
    require_valid(run["workflow"])
    return step


def _record(run, sid, status, note, artifacts):
    record = {"status": status, "note": note.strip(), "artifacts": list(artifacts), "at": now()}
    run["states"][sid] = record
    run["events"].append({"step_id": sid, **copy.deepcopy(record)})
    run["status"] = "completed" if all(_satisfied(s) for s in run["states"].values()) else "active"


def complete_step(run, sid, note, artifacts):
    step = _prepare(run, sid, note)
    if not isinstance(artifacts, list) or not all(isinstance(a, str) and a.strip() for a in artifacts) or (step.get("outputs") and not artifacts):
        raise ValueError("请登记至少一个产物引用；记录不代表已验证文件内容")
    _record(run, sid, "completed", note, artifacts)
