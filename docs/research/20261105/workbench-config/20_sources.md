# 本机配置读取依据

2026-11-05，为实现只读 MCP/插件清单核对以下官方资料，并与本机文件结构对照。

- [MCP 配置](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)：用户 MCP 位于 config.toml 的 mcp_servers；插件 MCP 策略位于 plugins.<plugin>.mcp_servers。命令、URL、环境变量和请求头属于不同配置字段。清单读取不意味着建立连接。
- [插件包与配置](https://developers.openai.com/plugins/build/plugins)：缓存采用 marketplace/plugin/version 目录；支持 root plugin.json/mcp.json 与 .codex-plugin/plugin.json 兼容格式。项目配置在真实宿主中受信任状态和配置优先级影响。
- 本机只读结构检查：存在用户 skills.config 路径/名称禁用项、用户 mcp_servers，以及插件 .codex-plugin/plugin.json 的 skills/mcpServers 声明。未复制配置原文、密钥、个人技能正文到仓库。

实现因此分别显示文件来源、配置启用和未知状态，不将本地缓存或历史运行记录解释为当前可调用工具清单。
