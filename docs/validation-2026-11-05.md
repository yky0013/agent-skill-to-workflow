# 2026-11-05 Python 工作台验证记录

## 已验证

- Windows，Python 3.14.0，PyYAML 6.0.3；在仓库隔离 `.venv` 中运行 `python -m unittest discover -s tests -v`：46 项通过，无失败或跳过。
- 测试覆盖真实临时文件、源哈希漂移、同名入口、历史 atlas、冲突记录、依赖图、事件重放、人工审核退回/通过、关闭后恢复、JSON 备份、写入冲突、导出碰撞、CLI 子进程和真实 Tk 控件操作。
- 独立审查确认的 5 类问题均已加入先失败后通过的回归测试：运行事件与状态不一致、缺失运行字段、未提交备注丢失、快速切换扫描来源、重复 atlas 身份冲突。
- 构建 `agent_skill_to_workflow-0.1.0-py3-none-any.whl` 成功；已在隔离环境安装，并从仓库根目录以外调用 `skill-workflow --help`、校验和导出示例成功。
- 本机历史 atlas 的 234 个条目导入成功：224 个主文件摘要一致，10 个源文件当前无法读取，16 个记录为历史禁用。结果仅证明导入兼容性和本次文件比对；没有执行这些技能。
- 示例流程「提取证据 → 人工核查 → 编写简报」生成、校验和导出成功。个人 atlas、个人技能原文及本机运行记录未提交。
- Windows 解锁后完成原生窗口验收：技能搜索与原文阅读、步骤编辑区域、完整导出预览与实际导出、运行记录载入、跨步骤备注保留、审核退回阻塞与重新通过放行均已观察确认。退出重启后重新载入的审核状态和产物引用一致。
- 审核详情已改为直接展示任务说明、审核标准、上游产物和处理记录，替代原始 JSON；在当前桌面尺寸与缩放下已复查显示。验收运行使用明确标注的模拟数据，没有执行真实文献任务。
- GitHub Python 检查在提交 `4aa63f2` 上的 Windows/Linux × Python 3.11/3.14 四组均通过：[运行记录](https://github.com/yky0013/agent-skill-to-workflow/actions/runs/42041838001)。原 Tauri 构建的 Windows、Linux、macOS Intel 三组通过；macOS ARM 组取消，原因不确定：[构建记录](https://github.com/yky0013/agent-skill-to-workflow/actions/runs/42041838244)。

## 明确限制

- 原 Tauri 应用的 `cargo test --manifest-path src-tauri/Cargo.toml` 未能运行：本机未找到 Cargo。原 Rust/TypeScript 产品代码没有修改。
- 原生目视验收覆盖本机当前窗口尺寸和显示缩放，未覆盖所有分辨率、缩放比例或其他操作系统桌面。
- 新增 Windows/Linux、Python 3.11/3.14 的 GitHub Actions 配置；远端结果以实际 Actions 运行记录为准，不以本地通过推断。
- 未验证 Python 工作台的 macOS 桌面、外部宿主执行组合技能、真实模型调用或完整科研工作流。工作台本身不会执行技能命令。
