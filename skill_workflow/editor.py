"""Small UI-independent workflow editing model."""

import uuid

from .catalog import inspect_skill


class Workbench:
    def __init__(self):
        self.workflow = {"schemaVersion": 1, "name": "my-workflow", "description": "描述何时使用这个组合技能及其交付物", "steps": []}

    def _linear(self):
        previous = []
        for step in self.workflow["steps"]:
            if step["depends_on"] != previous:
                raise ValueError("该文件是分支依赖图；桌面顺序编辑不能重写依赖，请在 JSON 中编辑后重新载入")
            previous = [step["id"]]

    def _rechain(self):
        previous = []
        for step in self.workflow["steps"]:
            step["depends_on"] = previous
            previous = [step["id"]]

    def _append(self, step):
        self._linear()
        step["id"] = "s-" + uuid.uuid4().hex[:10]
        step["depends_on"] = []
        self.workflow["steps"].append(step)
        self._rechain()

    def add_skill(self, skill):
        current = inspect_skill(skill.path)
        if skill.enabled is False or any(i.severity == "error" for i in current.issues):
            raise ValueError("该技能被记录为禁用或存在读取错误，请先核实源文件")
        if current.sha256 != skill.sha256:
            raise ValueError("选中的源文件已变化，请刷新技能目录后重新选择")
        self._append({"kind": "skill", "title": skill.name, "instruction": skill.description,
                      "outputs": ["本步骤产物及验证说明"], "skill_path": skill.path,
                      "skill_sha256": skill.sha256, "source_enabled": skill.enabled})

    def add_review(self):
        self._append({"kind": "review", "title": "人工审核", "instruction": "展示上游产物和验证证据，等待本次明确审核决定。",
                      "criteria": "输入与目标一致；证据支持结论；产物完整且可读。", "outputs": []})

    def move_step(self, index, delta):
        self._linear()
        target = index + delta
        if not (0 <= index < len(self.workflow["steps"]) and 0 <= target < len(self.workflow["steps"])):
            return
        steps = self.workflow["steps"]
        steps[index], steps[target] = steps[target], steps[index]
        self._rechain()

    def remove_step(self, index):
        self._linear()
        del self.workflow["steps"][index]
        self._rechain()
