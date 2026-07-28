# ElectroMind README 重写设计

## 目标

将仓库根目录 `README.md` 重写为中文主文、英文技术名词保留的产品入口文档。README 以 CLI 用户为第一目标读者，让新用户可以从安装开始，在五分钟内完成配置并启动首次对话；随后再向需要深入使用的读者介绍项目结构、会话、Sandbox、桌面端、协议接口和 Python API。

## 内容原则

- 产品名称统一为 `ElectroMind`，命令统一为 `electromind`。
- 只记录当前仓库实际存在且可由代码或命令验证的功能。
- 不沿用旧 `pagent` README 中已经失效的包名、路径、示例或文档链接。
- API Key 示例只使用占位符，不出现真实凭据。
- 命令以 `uv` 为推荐安装和开发工具，同时区分普通安装与本地源码可编辑安装。
- 项目目录树反映当前文件系统；不把规划中的 `kernel/`、`providers/`、`execution/` 等目录写成已实现。
- 根 README 保持“快速入门足够完整、内部参考适度精简”，避免替代全部开发文档。

## 信息架构

README 按以下顺序组织：

1. 产品简介、适用场景和核心能力
2. 环境要求与 CLI 安装
3. 五分钟快速开始
4. 带职责注释的项目目录树
5. 配置文件位置、优先级和最小配置
6. 常用 CLI 命令、会话查看与恢复
7. 配置、Threads、Skills 等数据保存位置
8. local、container、docker、podman、ssh Sandbox
9. Electron Desktop 与 VS Code 编辑器入口
10. HTTP 与 Wire 集成方式
11. Python API 最小示例
12. 本地开发、检查、常见问题和 MIT License

## 项目目录

目录章节展示当前主要边界：

- `src/app/`：CLI、REPL、配置、会话、HTTP/Wire 与 Dockerfile。
- `src/electromind/`：核心、运行时、Thread、对话持久化、Sandbox、Skills、工具、适配器与 Trace。
- `src/electromind_legacy/`：旧版 API 兼容层。
- `editors/desktop/` 与 `editors/vscode/`：桌面端和 VS Code 扩展。
- `skills/`：仓库内化学计算领域 Skills。
- `tests/`：应用、核心、Sandbox 和协议测试。
- `scripts/`：质量检查、发布与开发命令。

生成的树只列出有助于理解项目的目录和文件，不列出 `.venv`、`node_modules`、构建产物、缓存或每个测试文件。

## 准确性验证

完成 README 后执行：

1. `electromind --help`，核对 CLI 参数与会话命令。
2. 检查 README 中引用的仓库相对路径是否存在。
3. 搜索残留的 `pagent` 产品名和失效路径；仅在解释兼容层或现存模板文件名时允许出现。
4. 检查所有 TOML、Shell 和 Python 代码块的语法与命令名称。

## 非目标

- 本次不重构项目目录。
- 不新增 CLI、桌面端或 Python API 功能。
- 不恢复已删除的旧文档站、示例和 CI 文件。
- 不修改 `README.md` 之外的产品文档；本设计说明仅记录重写决策。
