# Agent Skill to Workflow

查看本机 Skills、MCP 和插件，把独立 skill 串成工作流，再导出为可复用的组合 `SKILL.md`。

工作台使用 **Python + Tkinter**，提供中文桌面界面和 CLI。启动后自动显示真实本机能力清单，也可以导入以前的筛查 atlas。工作流由技能步骤组成，完成上一步后直接按依赖推进。

## Python 工作台快速开始

需要 Python 3.11+（含 Tkinter）。Windows 的官方 Python 安装通常提供 Tkinter；Linux 可能需单独安装 `python3-tk`。

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -e .
.venv/Scripts/python -m skill_workflow gui
```

macOS/Linux 使用 `.venv/bin/python` 替代 `.venv/Scripts/python`。Windows 安装后也可双击 `launch_workbench.pyw`。

- **Skills 列表**：默认打开并自动扫描用户技能、Agents 技能、插件技能和项目入口；支持搜索、原文阅读、来源查看和加入工作流。
- **MCP 列表**：显示本机 `config.toml` 与插件声明中的 MCP 名称、连接类型、配置启用状态及来源。凭据值不会显示。
- **插件列表**：查看本机配置声明及缓存清单、版本、说明和目录。缓存发现与配置启用分开标注。
- **编排与导出**：添加和排序技能步骤，编辑任务与产物，保存/载入 JSON，导出组合 skill。
- **运行记录**：登记实际执行结果与产物，按依赖推进，关闭后可恢复。
- **文件保护**：写入前预览，覆盖前备份，版本冲突检查，原子保存；导出目录存在时拒绝覆盖。

工作台负责编排和跟踪，**不会自动调用模型或执行技能命令**。列表中的配置状态不等于连接测试结果，历史样例通过也不等于当前任务已完成。

直接启动不需要指定目录。使用不同 Codex 配置目录时，可点击「选择 Codex 目录」或传入 `--codex-home`。命令行读取本机清单：

```powershell
python -m skill_workflow inventory
python -m skill_workflow gui --codex-home C:/path/to/.codex --project C:/path/to/project
```

以下命令仅用于加载仓库自带的两份演示技能：

```powershell
python examples/create_demo.py demo-workflow.json --apply
python -m skill_workflow gui --root ./examples/skills --workflow demo-workflow.json
python -m skill_workflow validate demo-workflow.json
python -m skill_workflow export demo-workflow.json ./reading-brief --apply
python -m unittest discover -s tests -v
```

所有 CLI 写入默认预览，显式 `--apply` 才保存。示例脚本和新建运行要求目标尚不存在。

[完整使用说明、数据格式与限制](docs/python-workbench.md) · [当前实现范围](docs/superpowers/plans/2026-11-05-inventory-without-review.md)

## 保留的原 Codex Manager 应用

`src-tauri/` 与 `src/` 继续提供原来的 Tauri/Rust/React 配置管理应用。下文是该应用的原有说明；Python 工作台是本仓库新增的独立入口，尚未替换原应用的配置编辑、聊天和终端功能。

### Codex Manager (Tauri)

Codex Manager is a desktop configuration and asset manager for OpenAI Codex.
It edits and organizes on-disk Codex files with a safety-first flow (diff preview, backups, atomic writes),
surfaces local session history from CODEX_HOME, and includes an in-app Codex chat runner with optional
terminal access for advanced workflows.

![Codex Manager dashboard](screenshots/Dashboard.jpg)

## Features
- Config editor with Simple (root scalars), Advanced (nested values), and raw TOML modes.
- Diff preview before every change (stacked/unified view), plus automatic backups and restore.
- Public Config Library with curated presets and apply previews.
- My Configs: save personal presets and apply them later.
- MCP Servers: toggle enabled state and add/update tables.
- Skills: browse user/repo scopes, edit SKILL.md and text files, create/delete skills.
- Public Skills (Clawdhub): search registry, preview SKILL.md/files, install via overlay/replace/sync.
- Diagnostics panel for parse errors and missing paths.
- Settings for CODEX_HOME, repo roots, Codex usage snapshot (plan + rate limit windows + auth status), and local session analytics + wrapped summary from CODEX_HOME logs.
- Chats: searchable session history (pin/archive), transcript paging, copy full ID + resume command, and a new chat workflow that can write workspace-scoped overrides to `.codex/config.toml` on copy.

## Supported platforms
- Windows 10/11 (x64): NSIS + MSI installers.
- macOS 14+ (arm64 + x64): DMG + app bundle (unsigned; Gatekeeper will warn on first open).
- Linux (x64): AppImage + .deb + .rpm.

Release builds are produced via GitHub Actions; download installers from Releases.

## Installation (local development)

### Prerequisites
- Node.js 18+ (20+ recommended)
- Rust toolchain (stable) via rustup
- Tauri system dependencies (platform specific)
  - Windows: Visual Studio Build Tools (Desktop development with C++), WebView2
  - macOS: Xcode Command Line Tools
  - Linux: GTK/WebKit packages (see Tauri prerequisites)

Tauri prerequisites: https://v2.tauri.app/start/prerequisites/

### Install dependencies
```bash
npm install
```

For installing and using the app, download the installer from the GitHub Releases page.

## Local development

### Run the desktop app (Tauri)
```bash
npm run tauri dev
```

### Optional: run the frontend only
This is useful for UI iteration, but backend commands will not work.
```bash
npm run dev
```

### Build a release bundle
Use the bundle formats that match your OS:

Windows:
```bash
npm run tauri build -- --bundles nsis,msi
```

macOS:
```bash
npm run tauri build -- --bundles dmg,app
```

Linux:
```bash
npm run tauri build -- --bundles appimage,deb,rpm
```

Windows installers require NSIS + WiX.

### Tests
```bash
cargo test --manifest-path src-tauri/Cargo.toml
```
Includes:
- TOML patching (scalar edits + MCP toggle)
- Backup/restore round trip (text + binary)
- Path traversal protection
- Skills scan + folder categorization
- Public skill zip planning (overlay/replace/sync)

## Usage

### First run setup
1) Open Settings and set CODEX_HOME (or ensure the `CODEX_HOME` env var is set).
2) Add any repo roots that contain `.codex/skills` for repo-scoped skills (also enables workspace defaults in Chats).
3) Return to Dashboard and click "Refresh scan" if needed.

### What the app manages
Canonical sources of truth are on disk:
- `CODEX_HOME/config.toml`
- `CODEX_HOME/skills/**`
- `REPO_ROOT/.codex/skills/**`
- `CODEX_HOME/prompts/**`
- `CODEX_HOME/rules/*.rules`
- `CODEX_HOME/sessions/**` (read-only history)
- `WORKSPACE/.codex/config.toml` (workspace-scoped overrides from Chats)

### Editing flow
All writes follow the same safety rails:
1) Preview a diff.
2) Create a backup.
3) Atomic write.
4) Re-validate and show status.

### Common actions
- Dashboard: view health and diagnostics, load config quickly.
- Config: edit root scalar keys, advanced nested values, or raw TOML with diff preview.
- Public Config Library: apply curated public configs (diff + backup).
- My Configs: save your own presets (stored in app data) and apply them to config.
- MCP Servers: toggle enabled, add/update server tables.
- Skills: view user and repo skills, edit SKILL.md, create or delete skills.
- Public Skills (Clawdhub): browse/search the Clawdhub registry, preview SKILL.md and files, then install via overlay/replace/sync.
- Backups: review, restore, or delete snapshots.
- Chats: review local sessions, pin/archive, copy resume command, and start new chats with workspace defaults.

### Managing public presets
Public presets live in `src/features/config/data/publicConfigs.ts`. Add new entries there to
ship more curated configs in the Public Config Library.

### My Configs storage
User-created presets are stored in the app data directory under `user-configs/`.

## Project structure
- `src-tauri/` Rust backend (file ops, diffing, backups, TOML patching)
- `src/` React frontend
  - `features/` feature-first UI modules
  - `components/` shared UI primitives
  - `layouts/` app shell + chrome
  - `store/` shared state + backend actions

## Notes
- Raw config editors and previews show full values; handle secrets with care.
