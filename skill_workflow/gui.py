"""Chinese Tkinter workbench. All domain behavior is shared with the CLI."""

import copy
import json
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from .catalog import Catalog, MAX_SOURCE_BYTES, import_atlas, load_json, read_limited, scan_roots
from .editor import Workbench
from .exporter import export_workflow, render_skill
from .runner import complete_step, create_run, ready_steps, review_step, validate_run
from .storage import preview_json, read_json_versioned, save_json
from .workflow import require_valid, validate_workflow

HISTORY = {"pass": "历史样例通过", "partial": "历史部分可用", "blocked": "历史受阻", "untested": "未验证", "disabled": "历史禁用"}
STATUS = {"pending": "待推进", "completed": "已登记完成", "approved": "审核通过", "rejected": "已退回，待复审"}


def format_run_details(run, sid):
    steps = {step["id"]: step for step in run["workflow"]["steps"]}
    step, state = steps[sid], run["states"][sid]
    lines = [f"{step['title']} · {STATUS[state['status']]}"]
    if step["kind"] == "review":
        lines.append("审核标准：" + step["criteria"])
    lines.append("任务说明：" + step["instruction"])
    if step["depends_on"]:
        lines.append("前置步骤：" + "；".join(f"{steps[d]['title']}（{STATUS[run['states'][d]['status']]}）" for d in step["depends_on"]))
        for dep in step["depends_on"]:
            artifacts = run["states"][dep]["artifacts"]
            if artifacts:
                lines.append("上游产物 · " + steps[dep]["title"] + "：" + "；".join(artifacts))
    if step.get("outputs"):
        lines.append("预期产物：" + "；".join(step["outputs"]))
    lines.extend(["", "当前记录：" + (state["note"] or "尚未登记")])
    if state["artifacts"]:
        lines.append("已登记产物：" + "；".join(state["artifacts"]))
    if step["kind"] == "skill":
        lines.extend(["", "技能来源：" + step["skill_path"]])
    events = [event for event in run["events"] if event["step_id"] == sid]
    if events:
        lines.extend(["", "处理记录（最近在前）："])
        for event in reversed(events):
            lines.append(f"{event['at']} · {STATUS[event['status']]}\n{event['note']}")
    return "\n".join(lines)


class App:
    def __init__(self, root):
        self.root = root
        self.model = Workbench()
        self.catalog = Catalog()
        self.roots = []
        self.atlas_path = None
        self.workflow_path = None
        self.workflow_version = None
        self.saved_workflow = copy.deepcopy(self.model.workflow)
        self.run = None
        self.run_path = None
        self.run_version = None
        self.run_drafts = {}
        self.selected_run_step = None
        self.selected_step = None
        self._scanning = False
        self._pending_scan = None
        self._scan_queue = queue.Queue()
        self.status = tk.StringVar(value="从技能目录开始：只读扫描 → 编排步骤 → 人工审核 → 导出组合技能")
        self.query = tk.StringVar()
        self.name_var = tk.StringVar()
        self.description_var = tk.StringVar()
        self.title_var = tk.StringVar()
        root.title("Skill Workflow · 技能工作流工作台")
        root.geometry("1280x850")
        root.minsize(1020, 700)
        root.configure(background="#eef2f7")
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure(".", font=("Microsoft YaHei UI", 10), background="#eef2f7", foreground="#172c43")
        style.configure("TButton", padding=(12, 7))
        style.configure("Accent.TButton", background="#2463b4", foreground="white")
        style.map("Accent.TButton", background=[("active", "#184b8b")])
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 22, "bold"))
        style.configure("Muted.TLabel", foreground="#5c6c80")
        style.configure("Treeview", rowheight=31, background="white", fieldbackground="white")
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 10, "bold"))
        style.map("Treeview", background=[("selected", "#d8e9ff")], foreground=[("selected", "#153d70")])
        header = ttk.Frame(root, padding=(22, 17, 22, 12))
        header.pack(fill="x")
        ttk.Label(header, text="技能工作流工作台", style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, text="把独立技能组织成可审阅、可复用的工作流", style="Muted.TLabel").pack(anchor="w", pady=(5, 0))
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=18, pady=(0, 8))
        self.catalog_tab = ttk.Frame(self.notebook, padding=14)
        self.flow_tab = ttk.Frame(self.notebook, padding=14)
        self.run_tab = ttk.Frame(self.notebook, padding=14)
        for tab, text in ((self.catalog_tab, "  1  技能目录  "), (self.flow_tab, "  2  编排与导出  "), (self.run_tab, "  3  人工审核与运行  ")):
            self.notebook.add(tab, text=text)
        self._build_catalog()
        self._build_workflow()
        self._build_run()
        ttk.Label(root, textvariable=self.status, style="Muted.TLabel", wraplength=1200, padding=(22, 7, 22, 12)).pack(fill="x")
        self.show_workflow()
        root.protocol("WM_DELETE_WINDOW", self.close)

    def action(self, operation):
        def perform():
            try:
                operation()
            except (OSError, ValueError, TypeError, RecursionError) as exc:
                self.status.set(str(exc))
                messagebox.showerror("操作未完成", str(exc), parent=self.root)
        return perform

    def button(self, parent, text, operation, accent=False):
        button = ttk.Button(parent, text=text, command=self.action(operation), style="Accent.TButton" if accent else "TButton")
        button.pack(side="left", padx=(0, 7), pady=3)
        return button

    def text_box(self, parent, height=8):
        return ScrolledText(parent, wrap="word", height=height, font=("Microsoft YaHei UI", 10),
                            background="white", foreground="#20364d", relief="flat", borderwidth=1, padx=12, pady=9)

    def put_text(self, widget, text, readonly=False):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        if readonly:
            widget.configure(state="disabled")

    def _build_catalog(self):
        bar = ttk.Frame(self.catalog_tab)
        bar.pack(fill="x")
        self.button(bar, "添加技能目录", self.choose_root)
        self.button(bar, "扫描常用目录", self.scan_defaults)
        self.button(bar, "导入筛查 atlas.json", self.choose_atlas)
        self.button(bar, "刷新", self.refresh_scan)
        self.button(bar, "加入工作流 →", self.add_selected_skill, True)
        search = ttk.Frame(self.catalog_tab)
        search.pack(fill="x", pady=(10, 10))
        ttk.Label(search, text="搜索名称、描述或路径").pack(side="left", padx=(0, 10))
        ttk.Entry(search, textvariable=self.query).pack(side="left", fill="x", expand=True)
        self.query.trace_add("write", lambda *_: self.refresh_catalog())
        split = ttk.Panedwindow(self.catalog_tab, orient="horizontal")
        split.pack(fill="both", expand=True)
        left, right = ttk.Frame(split), ttk.Frame(split)
        split.add(left, weight=4)
        split.add(right, weight=5)
        self.catalog_tree = ttk.Treeview(left, columns=("name", "current", "history"), show="headings", selectmode="browse")
        for column, title, width in (("name", "技能", 190), ("current", "当前读取", 100), ("history", "历史运行证据", 125)):
            self.catalog_tree.heading(column, text=title)
            self.catalog_tree.column(column, width=width, minwidth=80)
        scroll = ttk.Scrollbar(left, orient="vertical", command=self.catalog_tree.yview)
        self.catalog_tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.catalog_tree.pack(fill="both", expand=True)
        self.catalog_tree.bind("<<TreeviewSelect>>", lambda _: self.show_skill())
        self.skill_details = self.text_box(right)
        self.skill_details.pack(fill="both", expand=True, padx=(12, 0))
        self.put_text(self.skill_details, "选择目录扫描，或导入之前保存的 atlas.json。\n\n同名技能按来源路径区分。目录扫描只证明文件可读取，不证明宿主已启用或完整工作流已运行。\n\n原始 SKILL.md 保持只读。", True)

    def _build_workflow(self):
        bar = ttk.Frame(self.flow_tab)
        bar.pack(fill="x")
        for text, op in (("新建", self.new_workflow), ("打开", self.choose_workflow), ("保存", self.save_workflow), ("另存为", lambda: self.save_workflow(save_as=True)), ("恢复 JSON 备份", self.restore_backup)):
            self.button(bar, text, op)
        self.button(bar, "校验", self.check_workflow)
        self.button(bar, "预览与导出", self.export_dialog, True)
        identity = ttk.Frame(self.flow_tab)
        identity.pack(fill="x", pady=(9, 9))
        ttk.Label(identity, text="技能名称").grid(row=0, column=0, padx=(0, 8))
        ttk.Entry(identity, textvariable=self.name_var, width=24).grid(row=0, column=1, padx=(0, 18))
        ttk.Label(identity, text="何时使用 / 交付目标").grid(row=0, column=2, padx=(0, 8))
        ttk.Entry(identity, textvariable=self.description_var).grid(row=0, column=3, sticky="ew")
        identity.columnconfigure(3, weight=1)
        split = ttk.Panedwindow(self.flow_tab, orient="horizontal")
        split.pack(fill="both", expand=True)
        left, right = ttk.Frame(split), ttk.Frame(split, padding=(15, 0, 0, 0))
        split.add(left, weight=3)
        split.add(right, weight=5)
        controls = ttk.Frame(left)
        controls.pack(fill="x")
        self.button(controls, "+ 人工审核", self.add_review)
        self.button(controls, "↑", lambda: self.move_step(-1))
        self.button(controls, "↓", lambda: self.move_step(1))
        self.button(controls, "移除", self.remove_step)
        self.step_tree = ttk.Treeview(left, columns=("order", "kind", "title"), show="headings", selectmode="browse")
        for column, title, width in (("order", "顺序", 45), ("kind", "类型", 70), ("title", "步骤", 220)):
            self.step_tree.heading(column, text=title)
            self.step_tree.column(column, width=width, minwidth=40)
        self.step_tree.pack(fill="both", expand=True, pady=8)
        self.step_tree.bind("<<TreeviewSelect>>", lambda _: self.select_step())
        ttk.Label(left, text="在技能目录中选择技能并加入。\n调整顺序会同步前后依赖；分支图需在 JSON 中编辑。", style="Muted.TLabel", wraplength=370).pack(anchor="w")
        ttk.Label(right, text="步骤名称").pack(anchor="w")
        ttk.Entry(right, textvariable=self.title_var).pack(fill="x", pady=(4, 8))
        self.source_label = ttk.Label(right, text="选择一个步骤进行编辑", style="Muted.TLabel", wraplength=620)
        self.source_label.pack(fill="x", pady=(0, 7))
        ttk.Label(right, text="任务说明 · 输入如何处理").pack(anchor="w")
        self.instruction_text = self.text_box(right, 4)
        self.instruction_text.pack(fill="both", expand=True, pady=(3, 7))
        ttk.Label(right, text="预期产物 · 每行一项").pack(anchor="w")
        self.outputs_text = self.text_box(right, 2)
        self.outputs_text.pack(fill="x", pady=(3, 7))
        ttk.Label(right, text="人工审核标准 · 仅审核步骤使用").pack(anchor="w")
        self.criteria_text = self.text_box(right, 3)
        self.criteria_text.pack(fill="both", expand=True, pady=(3, 5))
        footer = ttk.Frame(right)
        footer.pack(fill="x")
        self.button(footer, "应用步骤修改", self.apply_editor)
        self.button(footer, "创建跟踪运行 →", self.start_run, True)

    def _build_run(self):
        bar = ttk.Frame(self.run_tab)
        bar.pack(fill="x")
        self.button(bar, "打开运行记录", self.choose_run)
        self.button(bar, "从当前工作流创建", self.start_run)
        self.run_summary = ttk.Label(self.run_tab, text="尚未打开运行记录", style="Muted.TLabel", wraplength=1150)
        self.run_summary.pack(fill="x", pady=10)
        self.run_tree = ttk.Treeview(self.run_tab, columns=("title", "kind", "status", "ready"), show="headings", height=7, selectmode="browse")
        for column, title, width in (("title", "步骤", 320), ("kind", "类型", 110), ("status", "状态", 180), ("ready", "推进条件", 200)):
            self.run_tree.heading(column, text=title)
            self.run_tree.column(column, width=width)
        self.run_tree.pack(fill="x")
        self.run_tree.bind("<<TreeviewSelect>>", lambda _: self.show_run_step())
        self.run_details = self.text_box(self.run_tab, 6)
        self.run_details.pack(fill="both", expand=True, pady=(10, 8))
        bottom = ttk.Frame(self.run_tab)
        bottom.pack(fill="x")
        notes = ttk.Frame(bottom)
        notes.pack(side="left", fill="both", expand=True, padx=(0, 10))
        ttk.Label(notes, text="完成 / 审核说明（必填）").pack(anchor="w")
        self.note_text = self.text_box(notes, 3)
        self.note_text.pack(fill="both", expand=True)
        artifacts = ttk.Frame(bottom)
        artifacts.pack(side="left", fill="both", expand=True)
        ttk.Label(artifacts, text="实际产物引用（每行一个路径或说明，仅登记）").pack(anchor="w")
        self.artifacts_text = self.text_box(artifacts, 3)
        self.artifacts_text.pack(fill="both", expand=True)
        controls = ttk.Frame(self.run_tab)
        controls.pack(fill="x", pady=(8, 0))
        self.complete_button = self.button(controls, "登记技能完成", lambda: self.transition(), True)
        self.approve_button = self.button(controls, "人工审核通过", lambda: self.transition("approved"), True)
        self.reject_button = self.button(controls, "退回修改", lambda: self.transition("rejected"))
        ttk.Label(controls, text="实际执行由你或宿主 agent 完成，工作台负责跟踪与审核。", style="Muted.TLabel").pack(side="right")
        self.show_run_step()

    def background_scan(self, operation):
        if self._scanning:
            self._pending_scan = operation
            self.status.set("已更新扫描来源，当前读取结束后会扫描最后选择的来源。")
            return
        self._scanning = True
        self.status.set("正在只读扫描技能文件…")
        def worker():
            try:
                self._scan_queue.put((operation(), None))
            except Exception as exc:
                self._scan_queue.put((None, exc))
        threading.Thread(target=worker, daemon=True).start()
        self.root.after(80, self.poll_scan)

    def poll_scan(self):
        try:
            catalog, error = self._scan_queue.get_nowait()
        except queue.Empty:
            self.root.after(80, self.poll_scan)
            return
        self._scanning = False
        if self._pending_scan is not None:
            operation, self._pending_scan = self._pending_scan, None
            self.background_scan(operation)
            return
        if error:
            self.status.set(f"读取失败：{error}")
            messagebox.showerror("扫描未完成", str(error), parent=self.root)
            return
        self.catalog = catalog
        self.refresh_catalog()
        errors = sum(any(i.severity == "error" for i in s.issues) for s in catalog.skills)
        self.status.set(f"读取 {len(catalog.skills)} 个技能入口 · {errors} 个入口需修复 · {len(catalog.issues)} 项目录提示。历史证据不等于本次运行通过。")
        if catalog.issues:
            self.put_text(self.skill_details, "目录检查提示\n\n" + "\n".join(i.message for i in catalog.issues), True)

    def choose_root(self):
        path = filedialog.askdirectory(title="选择包含技能目录的根目录", parent=self.root)
        if path:
            self.atlas_path = None
            if path not in self.roots:
                self.roots.append(path)
            self.refresh_scan()

    def scan_defaults(self):
        home = Path.home()
        codex = Path(os.environ.get("CODEX_HOME", home / ".codex"))
        self.roots = [str(p) for p in (codex / "skills", home / ".agents/skills", codex / "plugins/cache") if p.is_dir()]
        if not self.roots:
            raise ValueError("未找到常用技能目录，请手动选择根目录")
        self.atlas_path = None
        self.refresh_scan()

    def choose_atlas(self):
        path = filedialog.askopenfilename(title="选择历史筛查 atlas.json", filetypes=[("JSON", "*.json")], parent=self.root)
        if path:
            self.atlas_path = path
            self.refresh_scan()

    def refresh_scan(self):
        if self.atlas_path:
            path = self.atlas_path
            self.background_scan(lambda: import_atlas(path))
        elif self.roots:
            roots = self.roots.copy()
            self.background_scan(lambda: scan_roots(roots))
        else:
            self.status.set("请先选择技能根目录或 atlas.json。")

    def refresh_catalog(self):
        self.catalog_tree.delete(*self.catalog_tree.get_children())
        query = self.query.get().casefold().strip()
        for skill in self.catalog.skills:
            if query and query not in f"{skill.name} {skill.description} {skill.path}".casefold():
                continue
            current = "读取错误" if any(i.severity == "error" for i in skill.issues) else ("有提示" if skill.issues else "可读取")
            if skill.enabled is False:
                current = "快照禁用"
            history = HISTORY.get(skill.historical.get("status"), skill.historical.get("status", "未验证"))
            self.catalog_tree.insert("", "end", iid=skill.id, values=(skill.name, current, history))

    def selected_skill(self):
        selected = self.catalog_tree.selection()
        return next((s for s in self.catalog.skills if selected and s.id == selected[0]), None)

    def show_skill(self):
        skill = self.selected_skill()
        if not skill:
            return
        info = [skill.name, skill.description, "", "路径：" + skill.path, "SHA-256：" + skill.sha256,
                "", "当前证据：主文件读取与静态链接检查；未运行技能。",
                "宿主启用状态：" + ("历史快照禁用" if skill.enabled is False else "未进行当前宿主核验"),
                "历史入口类别：" + skill.visibility,
                "历史运行证据：" + json.dumps(skill.historical or {"status": "未验证"}, ensure_ascii=False, indent=2),
                "快照时间：" + (skill.captured_at or "无"),
                "源文件与快照：" + ({True: "一致", False: "不一致或缺失", None: "无历史快照"}[skill.evidence_matches]), ""]
        info += [f"[{i.severity}] {i.message}" + (f"（行 {i.line}）" if i.line else "") for i in skill.issues]
        if skill.references:
            info += ["", "哈希匹配的显式关系证据：", json.dumps(skill.references, ensure_ascii=False, indent=2)]
        try:
            source = read_limited(Path(skill.path), MAX_SOURCE_BYTES).decode("utf-8-sig")
            info += ["", "──── SKILL.md 原文（只读）────", source]
        except (OSError, ValueError, UnicodeError) as exc:
            info += [str(exc)]
        self.put_text(self.skill_details, "\n".join(info), True)

    def add_selected_skill(self):
        skill = self.selected_skill()
        if not skill:
            raise ValueError("请先选择一个技能")
        self.commit_editor()
        self.model.add_skill(skill)
        self.refresh_steps(self.model.workflow["steps"][-1]["id"])
        self.notebook.select(self.flow_tab)
        self.status.set(f"已加入 {skill.name}；可编辑任务说明和产物要求。")

    def commit_editor(self):
        self.model.workflow["name"] = self.name_var.get().strip()
        self.model.workflow["description"] = self.description_var.get().strip()
        step = next((s for s in self.model.workflow["steps"] if s["id"] == self.selected_step), None)
        if step:
            step.update(title=self.title_var.get().strip(), instruction=self.instruction_text.get("1.0", "end-1c").strip(),
                        outputs=[s.strip() for s in self.outputs_text.get("1.0", "end-1c").splitlines() if s.strip()])
            if step["kind"] == "review":
                step["criteria"] = self.criteria_text.get("1.0", "end-1c").strip()

    def apply_editor(self):
        self.commit_editor()
        self.refresh_steps(self.selected_step)
        self.status.set("步骤修改已应用到当前草稿；保存后才写入文件。")

    def select_step(self):
        selected = self.step_tree.selection()
        sid = selected[0] if selected else None
        if sid == self.selected_step:
            return
        self.commit_editor()
        self.selected_step = sid
        step = next((s for s in self.model.workflow["steps"] if s["id"] == sid), None)
        self.title_var.set(step["title"] if step else "")
        self.put_text(self.instruction_text, step["instruction"] if step else "")
        self.put_text(self.outputs_text, "\n".join(step.get("outputs", [])) if step else "")
        self.put_text(self.criteria_text, step.get("criteria", "") if step else "")
        self.source_label.configure(text=(f"ID：{sid}\n来源：{step.get('skill_path', '人工审核节点')}" if step else "选择一个步骤进行编辑"))

    def refresh_steps(self, select=None):
        self.selected_step = None
        self.step_tree.delete(*self.step_tree.get_children())
        for index, step in enumerate(self.model.workflow["steps"], 1):
            self.step_tree.insert("", "end", iid=step["id"], values=(index, "人工审核" if step["kind"] == "review" else "技能", step["title"]))
        if select and self.step_tree.exists(select):
            self.step_tree.selection_set(select)
            self.step_tree.see(select)
        else:
            self.title_var.set("")
            for widget in (self.instruction_text, self.outputs_text, self.criteria_text):
                self.put_text(widget, "")
        self.select_step()

    def show_workflow(self):
        self.selected_step = None
        self.name_var.set(self.model.workflow["name"])
        self.description_var.set(self.model.workflow["description"])
        self.refresh_steps()

    def add_review(self):
        self.commit_editor()
        self.model.add_review()
        self.refresh_steps(self.model.workflow["steps"][-1]["id"])

    def _selected_index(self):
        selected = self.step_tree.selection()
        if not selected:
            raise ValueError("请先选择一个步骤")
        return next(i for i, s in enumerate(self.model.workflow["steps"]) if s["id"] == selected[0])

    def move_step(self, delta):
        self.commit_editor()
        index = self._selected_index()
        sid = self.model.workflow["steps"][index]["id"]
        self.model.move_step(index, delta)
        self.refresh_steps(sid)

    def remove_step(self):
        self.commit_editor()
        self.model.remove_step(self._selected_index())
        self.refresh_steps()

    def can_discard(self):
        self.commit_editor()
        return self.model.workflow == self.saved_workflow or messagebox.askyesno("尚有未保存修改", "放弃当前工作流草稿的未保存修改？", parent=self.root)

    def new_workflow(self):
        if self.can_discard():
            self.model = Workbench()
            self.workflow_path = self.workflow_version = None
            self.saved_workflow = copy.deepcopy(self.model.workflow)
            self.show_workflow()

    def choose_workflow(self):
        if not self.can_discard():
            return
        path = filedialog.askopenfilename(title="打开工作流 JSON", filetypes=[("JSON", "*.json")], parent=self.root)
        if path:
            self.load_workflow(path)

    def load_workflow(self, path):
        workflow, version = read_json_versioned(path)
        require_valid(workflow, check_sources=False)
        self.model.workflow = workflow
        self.workflow_path, self.workflow_version = Path(path), version
        self.saved_workflow = copy.deepcopy(workflow)
        self.show_workflow()
        self.notebook.select(self.flow_tab)
        self.status.set(f"已载入 {path}；导出或启动前会重新校验源文件。")

    def confirm_preview(self, title, text):
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.geometry("1040x700")
        dialog.transient(self.root)
        dialog.grab_set()
        result = [False]
        preview = self.text_box(dialog)
        preview.pack(fill="both", expand=True, padx=14, pady=14)
        self.put_text(preview, text, True)
        bar = ttk.Frame(dialog, padding=12)
        bar.pack(fill="x")
        def accept():
            result[0] = True
            dialog.destroy()
        ttk.Button(bar, text="确认写入", command=accept, style="Accent.TButton").pack(side="right")
        ttk.Button(bar, text="取消", command=dialog.destroy).pack(side="right", padx=10)
        dialog.wait_window()
        return result[0]

    def save_workflow(self, path=None, save_as=False):
        self.commit_editor()
        require_valid(self.model.workflow, check_sources=False)
        if path is None:
            path = self.workflow_path if not save_as else None
        if path is None:
            path = filedialog.asksaveasfilename(title="保存工作流", defaultextension=".json", initialfile=self.model.workflow["name"] + ".json", parent=self.root)
        if not path:
            return
        path = Path(path)
        version = self.workflow_version if self.workflow_path and path.absolute() == self.workflow_path.absolute() else (read_json_versioned(path)[1] if path.exists() else None)
        if self.confirm_preview("保存工作流 · 差异预览", preview_json(path, self.model.workflow)):
            self.workflow_version = save_json(path, self.model.workflow, expected_digest=version)
            self.workflow_path = path
            self.saved_workflow = copy.deepcopy(self.model.workflow)
            self.status.set(f"已保存：{path}。覆盖前的原文件保存在同目录 .workflow-backups。")

    def check_workflow(self):
        self.commit_editor()
        issues = validate_workflow(self.model.workflow)
        text = "\n".join(f"[{i.severity}] {i.message}" for i in issues) or "工作流结构、来源摘要及依赖检查通过。尚未执行技能。"
        messagebox.showinfo("工作流校验", text, parent=self.root)

    def export_dialog(self):
        self.commit_editor()
        content = render_skill(self.model.workflow)
        parent = filedialog.askdirectory(title="选择导出父目录（将创建以技能名称命名的新目录）", parent=self.root)
        if not parent:
            return
        destination = Path(parent) / self.model.workflow["name"]
        if destination.exists():
            raise ValueError("此目录已存在，请改用新的工作流名称或其他父目录")
        preview = f"目标：{destination}\n文件：SKILL.md、workflow.json、sources.lock.json\n\n{content}\n\n──── workflow.json ────\n" + json.dumps(self.model.workflow, ensure_ascii=False, indent=2)
        if self.confirm_preview("导出组合技能 · 完整预览", preview):
            export_workflow(self.model.workflow, destination)
            self.status.set(f"组合技能已导出：{destination}。未自动安装，原技能保持只读。")

    def restore_backup(self):
        source = filedialog.askopenfilename(title="选择 .workflow-backups 中的 JSON 备份", filetypes=[("JSON", "*.json")], parent=self.root)
        if not source:
            return
        data = load_json(source)
        if isinstance(data, dict) and "workflow" in data:
            validate_run(data)
        else:
            require_valid(data, check_sources=False)
        target = filedialog.asksaveasfilename(title="选择要恢复到的文件", defaultextension=".json", parent=self.root)
        if not target:
            return
        version = read_json_versioned(target)[1] if Path(target).exists() else None
        if self.confirm_preview("恢复备份 · 差异预览", preview_json(target, data)):
            save_json(target, data, expected_digest=version)
            self.status.set(f"已恢复：{target}。请重新打开该文件以载入恢复后的内容。")

    def start_run(self):
        self.commit_editor()
        proposed = create_run(self.model.workflow)
        if not self.can_discard_run():
            return
        path = filedialog.asksaveasfilename(title="创建新的运行记录", initialfile=self.model.workflow["name"] + ".run.json", defaultextension=".json", parent=self.root)
        if not path:
            return
        if Path(path).exists():
            raise ValueError("运行记录已存在；请打开旧记录或选择新文件名")
        if self.confirm_preview("创建运行记录 · 预览", preview_json(path, proposed)):
            self.run_version = save_json(path, proposed, expected_digest=None)
            self.run, self.run_path = proposed, Path(path)
            self.run_drafts = {}
            self.selected_run_step = None
            self.refresh_run()
            self.notebook.select(self.run_tab)

    def choose_run(self):
        path = filedialog.askopenfilename(title="打开运行记录", filetypes=[("JSON", "*.json")], parent=self.root)
        if path:
            proposed, version = read_json_versioned(path)
            validate_run(proposed)
            if not self.can_discard_run():
                return
            self.run, self.run_version, self.run_path = proposed, version, Path(path)
            self.run_drafts = {}
            self.selected_run_step = None
            self.refresh_run()

    def refresh_run(self):
        self.run_tree.delete(*self.run_tree.get_children())
        if not self.run:
            return
        ready = ready_steps(self.run)
        for step in self.run["workflow"]["steps"]:
            state = self.run["states"][step["id"]]["status"]
            condition = "可以推进" if step["id"] in ready else ("已结束" if state in ("approved", "completed") else "等待上游通过")
            self.run_tree.insert("", "end", iid=step["id"], values=(step["title"], "人工审核" if step["kind"] == "review" else "技能", STATUS[state], condition))
        self.run_summary.configure(text=f"{self.run['workflow']['name']} · {'全部完成' if self.run['status'] == 'completed' else '跟踪中'} · {self.run_path}")
        if ready:
            self.run_tree.selection_set(ready[0])
        self.show_run_step()

    def show_run_step(self):
        selected = self.run_tree.selection()
        for button in (self.complete_button, self.approve_button, self.reject_button):
            button.configure(state="disabled")
        if not self.run or not selected:
            self.commit_run_draft()
            self.selected_run_step = None
            self.put_text(self.run_details, "选择运行步骤查看任务、产物要求和审核记录。", True)
            return
        sid = selected[0]
        if sid != self.selected_run_step:
            self.commit_run_draft()
            self.selected_run_step = sid
            draft = self.run_drafts.get(sid, {})
            self.put_text(self.note_text, draft.get("note", ""))
            self.put_text(self.artifacts_text, draft.get("artifacts", ""))
        step = next(s for s in self.run["workflow"]["steps"] if s["id"] == sid)
        self.put_text(self.run_details, format_run_details(self.run, sid), True)
        if sid in ready_steps(self.run):
            buttons = (self.complete_button,) if step["kind"] == "skill" else (self.approve_button, self.reject_button)
            for button in buttons:
                button.configure(state="normal")

    def transition(self, decision=None):
        if not self.run or not self.run_tree.selection():
            raise ValueError("请选择运行步骤")
        proposed = copy.deepcopy(self.run)
        sid = self.run_tree.selection()[0]
        note = self.note_text.get("1.0", "end-1c").strip()
        if decision:
            review_step(proposed, sid, decision, note)
        else:
            artifacts = [s.strip() for s in self.artifacts_text.get("1.0", "end-1c").splitlines() if s.strip()]
            complete_step(proposed, sid, note, artifacts)
        if self.confirm_preview("登记进度 · 差异预览", preview_json(self.run_path, proposed)):
            self.run_version = save_json(self.run_path, proposed, expected_digest=self.run_version)
            self.run = proposed
            self.run_drafts.pop(sid, None)
            self.selected_run_step = None
            self.refresh_run()
            self.status.set("进度已保存；审核未通过的下游仍保持阻塞。")

    def commit_run_draft(self):
        if self.selected_run_step is not None:
            note = self.note_text.get("1.0", "end-1c")
            artifacts = self.artifacts_text.get("1.0", "end-1c")
            if note.strip() or artifacts.strip():
                self.run_drafts[self.selected_run_step] = {"note": note, "artifacts": artifacts}
            else:
                self.run_drafts.pop(self.selected_run_step, None)

    def can_discard_run(self):
        self.commit_run_draft()
        return not self.run_drafts or messagebox.askyesno("尚有未登记内容", "放弃当前运行中尚未登记的说明和产物引用？", parent=self.root)

    def close(self):
        if self.can_discard() and self.can_discard_run():
            self.root.destroy()


def launch(*, roots=None, atlas=None, workflow_path=None):
    root = tk.Tk()
    app = App(root)
    app.roots = roots or []
    app.atlas_path = atlas
    if workflow_path:
        app.action(lambda: app.load_workflow(workflow_path))()
    if roots or atlas:
        root.after(100, app.refresh_scan)
    root.mainloop()
