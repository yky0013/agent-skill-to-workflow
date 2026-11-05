# 本机能力清单与技能工作流

## 启动与清单

运行 `python -m skill_workflow gui`，或在 Windows 双击 `launch_workbench.pyw`。启动后自动打开 Skills 列表，后台读取本机 Skills、MCP 和插件，不需要先选演示目录。

默认从 `CODEX_HOME` 指定的目录读取配置；未设置时使用 `~/.codex`。扫描用户技能、`~/.agents/skills`、插件缓存中声明的技能目录，以及显式项目的 `.agents/skills` 和 `.codex/skills`。需要更换配置来源时，点击「选择 Codex 目录」，或者传入：

```powershell
python -m skill_workflow gui --codex-home C:/my-profile/.codex --project F:/my-project
python -m skill_workflow inventory --codex-home C:/my-profile/.codex --project F:/my-project
```

界面提供五个页面：

| 页面 | 用途 |
|---|---|
| Skills | 搜索名称、描述和路径；查看来源、当前静态问题和只读原文；加入工作流 |
| MCP | 查看本机配置和插件声明中的名称、传输类型、配置状态及来源 |
| 插件 | 查看配置声明、缓存版本、用途和目录；区分配置启用与未知状态 |
| 编排与导出 | 添加、排序、编辑技能步骤，保存或导出组合技能 |
| 运行记录 | 登记实际完成说明和产物，完成后按依赖推进 |

MCP 列表不启动服务或发起连接测试，配置启用不代表当前连接成功。环境变量值、HTTP 认证头、令牌和 URL 凭据不进入显示记录。插件缓存说明文件存在，不能单凭缓存推断插件已启用。

发现逻辑以本机文件为依据。MCP 与插件策略读取所选 Codex 目录的 config.toml，`--project` 扩展项目技能目录，不合并项目级 MCP 策略。当前实现不是 Codex 宿主配置解析器，不保证还原云端或系统托管策略、当前会话工具清单及所有信任层级；实际是否由宿主加载以该宿主为准。

## 编排与运行

1. 在 Skills 列表选择一个技能，点击「加入工作流」。
2. 在「编排与导出」填写名称和用途，编辑每个步骤的任务说明、输入处理方式和预期产物；通过上下移动调整顺序。
3. 保存为工作流 JSON，或预览并导出到新的技能目录。源文件变化或依赖不合法时会给出明确错误。
4. 实际执行由用户或宿主 agent 完成。创建运行记录后，登记某个已完成步骤的说明和产物引用，即可推进依赖该步骤的下游。
5. 运行记录可关闭后重新打开；尚未提交的备注在切换步骤时保留，更换运行或退出前会提醒处理未登记内容。

当前工作流只包含技能步骤，没有独立的人工审核节点、通过/退回按钮或额外审核关卡。工作台不会自行调用模型、执行 skill 中的命令或安装技能。

## 命令行

写入默认只预览；显式 `--apply` 才保存。新建命令拒绝覆盖已有目标。

```powershell
python -m skill_workflow inventory
python -m skill_workflow scan ./examples/skills
python -m skill_workflow compose my-flow --description "提取证据并整理简报" --skill ./examples/skills/extract-evidence/SKILL.md --skill ./examples/skills/write-summary/SKILL.md --output my-flow.json --apply
python -m skill_workflow validate my-flow.json
python -m skill_workflow export my-flow.json ./my-flow --apply
python -m skill_workflow run my-flow.json my-flow.run.json --apply
python -m skill_workflow status my-flow.run.json
python -m skill_workflow complete my-flow.run.json STEP_ID --note "已检查输入和结果" --artifact evidence.md --apply
python -m skill_workflow restore path/to/backup.json restored.run.json --apply
```

`compose` 自动生成步骤 ID，可在工作流 JSON 或 `status` 输出中查看。退出码 `0` 表示检查/操作成功，`2` 表示发现输入、来源或写入错误；扫描仍会输出已发现的清单。静态警告不代表执行失败。

## 示例与旧文件

仓库自带两份演示技能，可生成「提取证据 → 编写简报」流程：

```powershell
python examples/create_demo.py demo-workflow.json --apply
python -m skill_workflow gui --root ./examples/skills --workflow demo-workflow.json
```

只有显式传入 `--root ./examples/skills` 时，Skills 页面才限定为演示目录。通常启动请不加这个参数。

当前工作流与运行记录使用 `schemaVersion=2`。载入 v1 工作流时，会先检查依赖结构，再移除旧审核节点，将下游重新接到其前置技能；分支依赖保留，原文件不会在载入时被覆盖。保存差异会展示转换结果。纯审核流程、循环或缺失依赖不能转换。

旧 v1 运行记录不会被自动改写为完成状态。请载入相应工作流并创建新的 v2 运行；旧文件仍保留在原处，可作为历史记录查看。

## 数据和文件保护

- 步骤包括 `id`、`kind="skill"`、`title`、`instruction`、`depends_on`、`outputs`、`skill_path` 和 `skill_sha256`。
- CLI 和核心支持 DAG；桌面顺序编辑不会隐式重写分支图。复杂依赖可在 JSON 中编辑后重新载入。
- 同名技能按来源路径区分。导出和运行前核对主文件 SHA-256；锁定不覆盖整个配套资源目录。
- 支持导入历史 atlas schemaVersion=1；历史运行证据单独标注，源哈希不匹配时不复用旧显式引用判断。
- 运行事件重放检查状态和依赖一致性，但运行文件属于本地人工登记，不是带身份认证的审计系统；产物引用也不代表文件内容已验证。
- 导出包含 `SKILL.md`、`workflow.json`、`sources.lock.json`，不复制原技能正文、不自动安装。跨设备需要重新选择本机来源后导出。
- 保存提供差异预览、覆盖前 `.workflow-backups` 备份、预期摘要检查、排他锁和原子写入。支持界面和 CLI 恢复备份。备份不会自动清理。
- 异常终止可能留下 `.<目标名称>.workflow-lock`。确认没有其他进程写入该目标后，再手动移除对应锁文件。

## 开发与验证

`inventory.py` 读取本机能力，`catalog.py` 检查技能，`workflow.py` 验证/迁移流程，`editor.py` 处理编排，`runner.py` 跟踪执行，`storage.py` 负责写入，`exporter.py` 生成组合技能，GUI 和 CLI 共享这些模块。

```powershell
python -m unittest discover -s tests -v
python -m pip wheel . --no-deps --wheel-dir dist
```

Tk 测试需要显示环境；无显示的 Linux 使用 `xvfb-run -a`。Python CI 覆盖 Windows/Linux × Python 3.11/3.14。旧 Tauri 应用在 `src/` 与 `src-tauri/`，使用原有构建流程。

配置读取参考：[MCP 配置](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)、[插件包与配置](https://developers.openai.com/plugins/build/plugins)。本机实际文件结构优先，未知状态明确标注。
