# Python 工作台使用与架构

## 适用范围

本工作台将原有 skill 组合为包含人工审核的流程。它保存的是编排、来源锁定和人工登记记录，不会启动模型、执行 skill 中的命令、安装技能或修改 Codex 配置。原 Tauri 应用仍在原目录，作为独立入口保留。

## 桌面操作

1. 在「技能目录」选择一个或多个根目录，或导入历史 `atlas.json`。可搜索名称、描述、路径并读取原文。扫描常用目录会读取当前用户的 Codex/Agents skill 与插件缓存目录，但不确认当前宿主是否已启用这些入口。
2. 选择 skill，点击「加入工作流」。在「编排与导出」修改名称、任务说明和产物要求。用「人工审核」添加审核点，然后用上下移动放到合适的位置。
3. 填写技能名称（小写英文字母、数字、连字符）和用途说明；保存 JSON。每次覆盖展示差异，并保留 `.workflow-backups` 备份。
4. 点击「预览与导出」，选择父目录并审阅全部编排。工作台创建以名称命名的新目录；已有目录不会被合并或覆盖。
5. 点击「创建跟踪运行」创建单独的运行 JSON。在宿主 agent 或其他工具中实际执行技能后，登记完成说明及产物引用。产物引用只记录文字，不代表程序已核验文件内容。
6. 人工审核通过后才放行下游；退回时下游继续阻塞。修改外部产物后可补充说明并重新审核。已经通过的节点不支持撤销；要重新执行上游任务，请创建新运行。
7. 可随时重新打开运行记录。若保存时检测到另一进程已修改文件，重新载入再操作；不会自动覆盖外部修改。

## 命令行

所有写入命令默认预览；显式加入 `--apply` 才落盘。新建命令拒绝覆盖已有目标。输出 JSON 使用 UTF-8。

退出码：`0` 表示检查/操作成功，`2` 表示输入、来源或写入错误。`scan` 仍会返回完整目录结果，但发现任一技能读取/元数据错误时退出码为 `2`；静态警告不影响退出码。

```powershell
python -m skill_workflow scan ./examples/skills
python -m skill_workflow compose my-flow --description "提取证据并审核" --skill ./examples/skills/extract-evidence/SKILL.md --review-after 1 --output my-flow.json --apply
python -m skill_workflow validate my-flow.json
python -m skill_workflow export my-flow.json ./my-flow --apply
python -m skill_workflow run my-flow.json my-flow.run.json --apply
python -m skill_workflow status my-flow.run.json
```

`compose` 自动生成步骤 ID；通过 `status` 或工作流 JSON 查看 ID。`complete` 仅用于技能步骤，`review` 仅用于审核步骤：

```powershell
python -m skill_workflow complete my-flow.run.json STEP_ID --note "已检查输入和结果" --artifact evidence.md --apply
python -m skill_workflow review my-flow.run.json REVIEW_ID approved --note "来源与产物已核实" --apply
python -m skill_workflow review my-flow.run.json REVIEW_ID rejected --note "请补充原始证据" --apply
python -m skill_workflow restore path/to/backup.json restored.run.json --apply
```

最后两条审核命令是两种选择，不应对已通过的同一节点依次执行。

## 可运行示例

在仓库根目录运行：

```powershell
python examples/create_demo.py demo-workflow.json --apply
python -m skill_workflow gui --root ./examples/skills --workflow demo-workflow.json
```

示例流程是「提取证据 → 人工核查 → 编写简报」，由两份本仓库自带示例技能组成。脚本根据当前安装路径计算来源摘要，因此没有预置个人路径。用户自行提供文章，示例不进行网络检索。

## 数据与证据规则

- 工作流 `schemaVersion=1`，顶层为 `name`、`description`、`steps`。每步必须有 `id`、`kind`、`title`、`instruction`、`depends_on`。技能步骤增加 `skill_path`、`skill_sha256`，审核步骤增加 `criteria`。`outputs` 为字符串数组。
- CLI 与核心支持有向无环图；桌面提供顺序编辑。分支图载入后可编辑文字、校验、导出与跟踪，但拒绝通过顺序按钮隐式重写依赖。
- 身份按来源路径生成，同名技能不会自动合并。主文件变化后，启动、登记进度或导出都会要求重新核对。已经运行的快照不可直接修改；选择新来源后创建新运行。
- `atlas.json` 兼容早期本机能力图谱 schemaVersion=1。主要字段是 `skills[].path/sha256/enabled/historical/references`。导入会复读原文件，只有哈希一致才保留显式引用证据；不会从正文普通提及猜测调用关系。
- `enabled=false` 或 `visibility=disabled` 代表导入快照记录为禁用；该条目不可直接加入工作流。确认实际状态后可重新扫描并选择。目录扫描不能证明宿主启用状态。
- 历史运行状态和时间始终独立展示。主文件读取、静态链接检查、历史样例运行和实际工作流完成是不同证据。
- 主文件哈希不覆盖整个配套资源目录。Markdown 缺失链接只是静态提示，可能涉及可选分支；未知、无法读取和未运行均不会显示成成功运行。
- 载入时按事件顺序重建状态，拒绝没有对应审核事件的“已通过”状态及不合法的依赖顺序。运行记录仍是本地人工登记，不是具备身份认证或防篡改能力的审计系统。导出技能依赖宿主遵循审核指令；应用内的状态机限制不等于对外部 agent 的强制控制。

## 导出与文件保护

导出目录包含 `SKILL.md`、`workflow.json` 和 `sources.lock.json`。不复制原技能源码、不安装或启用技能。包含原技能绝对路径，分享前请检查路径和任务说明；跨设备须在目标机器重新选择源文件并导出。

JSON 保存使用预期内容 SHA-256、排他锁、覆盖前备份和临时文件原子替换。写入路径拒绝符号链接及目录联接。可从界面「恢复 JSON 备份」或 CLI `restore` 恢复。备份不会自动清理。

锁文件名为 `.<目标名称>.workflow-lock`。若进程异常终止，锁可能残留。确认没有其他工作台进程写入该目标后，可手动移除对应锁文件，再重试；应用不会擅自删除其他进程的锁。

## 模块

| 模块 | 职责 |
|---|---|
| `catalog.py` | 只读发现、YAML 安全读取、静态资源检查、历史 atlas 对照 |
| `workflow.py` | schema、依赖、来源和哈希验证 |
| `editor.py` | 顺序编辑和来源选择，拒绝隐式改写分支图 |
| `runner.py` | 人工完成与审核状态机、运行快照 |
| `storage.py` | 差异、备份、并发版本检查、原子保存 |
| `exporter.py` | 组合技能文档和来源锁定文件 |
| `cli.py` / `gui.py` | 同一核心的命令行和中文 Tkinter 界面 |

## 验证

```powershell
python -m unittest discover -s tests -v
python -m pip wheel . --no-deps --wheel-dir dist
```

Tkinter 测试需要显示环境；无显示的 Linux 使用 `xvfb-run -a python -m unittest discover -s tests -v`。新增 CI 包含 Windows/Linux 与 Python 3.11/3.14。配置了 CI 不代表远端 CI 已通过，需查看对应运行结果。旧应用测试仍是 `cargo test --manifest-path src-tauri/Cargo.toml`。
