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
    return {"schemaVersion": 1, "id": uuid.uuid4().hex, "created_at": now(),
            "workflow": copy.deepcopy(workflow), "workflow_sha256": digest_bytes(json_bytes(workflow)),
            "status": "active", "states": {s["id"]: {"status": "pending", "note": "", "artifacts": []} for s in workflow["steps"]},
            "events": []}


def _satisfied(state):
    return state["status"] in ("completed", "approved")


def validate_run(run):
    if not isinstance(run, dict) or type(run.get("schemaVersion")) is not int or run["schemaVersion"] != 1:
        raise ValueError("不支持的运行记录格式")
    workflow = run.get("workflow")
    require_valid(workflow, check_sources=False)
    if run.get("workflow_sha256") != digest_bytes(json_bytes(workflow)):
        raise ValueError("运行中工作流快照已变化；请新建运行")
    states = run.get("states")
    if not isinstance(states, dict) or set(states) != {s["id"] for s in workflow["steps"]}:
        raise ValueError("运行步骤状态不完整")
    events = run.get("events")
    if not isinstance(events, list) or any(not isinstance(e, dict) for e in events):
        raise ValueError("运行事件记录无效")
    for step in workflow["steps"]:
        state = states[step["id"]]
        allowed = ("pending", "completed") if step["kind"] == "skill" else ("pending", "approved", "rejected")
        if not isinstance(state, dict) or state.get("status") not in allowed:
            raise ValueError(f"步骤状态非法：{step['id']}")
        if state["status"] != "pending":
            if not all(_satisfied(states[d]) for d in step["depends_on"]):
                raise ValueError(f"依赖未通过却已推进步骤：{step['id']}")
            if not isinstance(state.get("note"), str) or not state["note"].strip():
                raise ValueError("完成/审核记录缺少说明")
            if step["kind"] == "skill":
                artifacts = state.get("artifacts")
                if not isinstance(artifacts, list) or not all(isinstance(a, str) and a.strip() for a in artifacts) or (step.get("outputs") and not artifacts):
                    raise ValueError("完成步骤缺少有效产物引用")
    expected_status = "completed" if all(_satisfied(s) for s in states.values()) else "active"
    if run.get("status") != expected_status:
        raise ValueError("运行总状态与步骤状态不一致")


def ready_steps(run) -> list[str]:
    validate_run(run)
    return [s["id"] for s in run["workflow"]["steps"]
            if not _satisfied(run["states"][s["id"]]) and all(_satisfied(run["states"][d]) for d in s["depends_on"])]


def _prepare(run, sid, kind, note):
    validate_run(run)
    step = next((s for s in run["workflow"]["steps"] if s["id"] == sid), None)
    if step is None or step["kind"] != kind:
        raise ValueError("步骤类型错误；人工审核必须使用 review 操作")
    if not isinstance(note, str) or not note.strip():
        raise ValueError("必须填写完成或审核说明")
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
    step = _prepare(run, sid, "skill", note)
    if not isinstance(artifacts, list) or not all(isinstance(a, str) and a.strip() for a in artifacts) or (step.get("outputs") and not artifacts):
        raise ValueError("请登记至少一个产物引用；记录不代表已验证文件内容")
    _record(run, sid, "completed", note, artifacts)


def review_step(run, sid, decision, note):
    _prepare(run, sid, "review", note)
    if decision not in ("approved", "rejected"):
        raise ValueError("审核决定只能是 approved 或 rejected")
    _record(run, sid, decision, note, [])
