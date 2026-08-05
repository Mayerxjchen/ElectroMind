# Desktop D0 打包烟雾测试 — 验收记录

- 日期：2026-08-05
- 验收范围（用户限定）：**验证 Desktop 壳能够被正确打包、启动，并连接已安装的 ElectroMind CLI**。不把本次结果算作"独立 Desktop 应用已完成"。
- 结论：**CONDITIONAL PASS**——壳可打包、可启动、wire 按需连接架构正确；但打包配置有缺陷（包体含开发残留、codesign 失败、图标失效），需修复后重打。

## 1. 产物（✅ 生成成功）

- `editors/desktop/release/electromind-Desktop-0.7.20-mac-arm64.zip`（143M）
- SHA-256：`34f16df3aa656109f9f6b57f636ed060379f54e133f68d9eb41f02bf4d30c215`
- `.app` 完整：`Contents/MacOS/`、`Frameworks/`（Electron 37.10.3）、`Resources/app/`（main.js / renderer.js / preload.js / index.html 齐全，**不依赖 src/ 与开发服务器**）
- 独立解压到 `/tmp/electromind-desktop-test/` 可启动 ✅

## 2. 启动场景

### 场景 1：未安装 CLI（`~/.local/bin/electromind` 临时改名，12s 观察）

- ✅ 主进程无崩溃；渲染进程正常加载（React shell 控制台输出正常，无白屏迹象）
- ✅ 不 spawn 任何 wire 子进程（找不到 CLI 时不启动，无无限重启循环）
- ✅ kill app 后无子进程泄漏
- ⚠️ 环境健康面板的"CLI 缺失 + 安装提示"为渲染进程 UI，终端日志不可见——**留手动验收**

### 场景 2：已安装 CLI（`~/.local/bin/electromind` 0.7.20）

- ✅ app 正常启动；**wire 子进程按需 spawn**（`ensureBridge()` 由 UI 触发，非启动即拉起）
- ✅ kill app 后 wire 子进程随 app 退出，无泄漏
- ⚠️ 完整会话交互（新建/发消息/流式/审批 Permit-Deny/Cancel/恢复/不重复执行）为 GUI 操作——**留手动验收**

### 场景 3：PATH 差异 / 生产路径（设计层确认）

- `enrichedPath()` 兜底：`~/.local/bin` + `/opt/homebrew/bin` + `/usr/local/bin` 恒入 PATH——Finder 启动缺 PATH 场景已设计处理 ✅（Finder 双击仍留手动验收）
- `uv run --project` 回退：生产形态下 `electromindProjectRoot()` = `Resources/app`，其内**无 pyproject.toml** → 回退不触发，走 global 检查 ✅（但依赖目录巧合，见 P2-2）
- `ELECTROMIND_HOME` 由 env 显式注入 `~/.electromind`，不依赖 cwd ✅

## 3. 发现的问题（修复阶段，D0 验收的价值所在）

| # | 严重度 | 问题 | 证据 |
| --- | --- | --- | --- |
| P1-1 | 高 | **打包无 ignore 规则**：`Resources/app/` 含 `.venv`（26M）+ `assets/.venv`（30M）+ `src/` `scripts/` `tests/` `README.md` `tsconfig.json` 全部进包；且未启用 asar（目录形态） | `du -sh app/.venv app/assets` |
| P1-2 | 高 | **codesign --deep --strict 失败**：`.venv` 内符号链接（python3 → python3.13）+ `file modified` | codesign 输出 |
| P2-1 | 中 | **图标失效**：packager WARNING "Could not find icon ... with extension .icon" → 采用默认 `electron.icns`；且 renderer 引 `assets/icon.icns` 加载失败 | 打包日志 + 启动日志 |
| P2-2 | 中 | **uv run 回退未显式区分生产**：`resolveElectromindWireInvocation` 无条件走 pyproject 分支；生产形态碰巧不触发，应显式 `app.isPackaged` 判断（验收标准 5） | `agent.ts:348-370` |
| P3 | 低 | 查找顺序无 `~/.cargo/bin`（ElectroMind 为 Python 栈，uv 入口已在 `~/.local/bin` 覆盖——可不改） | `agent.ts:321` |

## 4. 修复（已完成 2026-08-05，重打验证通过）

```text
F1  package.js 补 ignore 规则（.venv / assets/.venv / icon.iconset /
    src / scripts / tests / release / .git / esbuild.js / tsconfig /
    README / package-lock）+ 显式 asar: true
F2  main/index.ts appIconPath 一律走 PNG（mac 窗口 icon 由 bundle 决定，
    .icns 传 BrowserWindow 触发 nativeImage 加载失败日志）
F3  agent.ts resolveElectromindWireInvocation / resolveBackendAvailability
    加 isPackaged 参数：生产态跳过 uv run --project 回退；
    main/index.ts 传 app.isPackaged，setup.ts 用 process.defaultApp === false
```

重打验证结果：

| 项 | 修复前 | 修复后 |
| --- | --- | --- |
| ZIP | 143M | **113M**（剩余大头为 Electron 运行时本体） |
| SHA-256 | 34f16df3… | 34664373fb0eacfa611259dcb64935303a39e6d8b8f1aba946dab5740b9bd96 |
| codesign --deep --strict | FAIL（.venv 符号链接） | ✅ valid on disk + satisfies Designated Requirement |
| 打包形态 | 目录复制 | ✅ app.asar（main/renderer/preload 齐） |
| 开发残留 | .venv 56M + src/scripts/tests | ✅ 0 残留 |
| 启动日志 | icon 加载失败 | ✅ 0 icon 错误、0 crash、渲染正常、无泄漏 |
| tsc --noEmit | — | ✅ 通过 |

遗留：`.icon` WARNING 来自 electron-packager icon composer（Assets.car）分支，
无害——copyIcon 的 .icns 分支正常（已验证 bundle 内 electron.icns 与源 icon
MD5 一致，即 Dock 图标已生效）。

## 7. D2 Standalone 最小可行性验证（2026-08-05，用户决策：先验证 Standalone）

### 结论：**可行** ✅ —— PyInstaller 单文件 + 嵌入 + 内置优先启动，全链路实测通过。

### 验证证据

| 项 | 结果 |
| --- | --- |
| 单文件构建 | ✅ `dist/electromind-0.7.20-macosx_11.0_arm64`（34M，SHA-256 `08fc7aac…`） |
| 独立运行 | ✅ 干净 PATH（/usr/bin:/bin）下 `--wire` 全链路（doctor 物化配置 / config validate / plan propose→approve 事件回流） |
| 嵌入 | ✅ `Resources/agent/electromind` 进包；ZIP 113M → **147M** |
| 内置优先 | ✅ 隐藏系统 CLI 后启动 app → spawn `Resources/agent/electromind --wire --execution-mode local`（非系统 CLI）；kill 后无泄漏 |
| 启动顺序 | `resolveElectromindWireInvocation`：isPackaged → 内置 → 系统 → （开发）uv run；`resolveBackendAvailability` 同步（mode: "bundled"） |

### 过程中发现并修复的 bug

1. **`src/app/__main__.py` 相对导入**（build-standalone.sh 从未验证）：PyInstaller 顶层脚本模式下 `from .cli import main` → ImportError。改为绝对导入 `from app.cli import main`（`python -m app` 与 PyInstaller 双兼容）。
2. **`package.js` embedAgent 少拼一级 `.app`**：agent 拷进 `packagedDir()/Contents/Resources/agent`（packager 输出根）而非 `.app/Contents/Resources/agent`，ZIP 不含内置 agent。已修 + 清理残留。
3. **脚本注释声称的 `--venv` 分支未实现**（build-standalone.sh 用法注释有、代码无）：本次用手工临时 venv 流程替代（`uv venv` + `uv pip install -e . pyinstaller`）；脚本补丁留待后续。

### 遗留与风险（1.0 前）

- win/linux 嵌入未验证（package.js 已留 `D2-win/linux` TODO 分支；win 需 `.exe` 后缀分支，linux 资源路径不同）
- 单文件启动时间（PyInstaller onefile 解包开销，~秒级）未量化
- 嵌入式 agent 的 ad-hoc 签名随 `codesign --deep` 覆盖（已验证不影响启动）
- 内置 agent 更新策略：随 Desktop 版本绑定（内置 0.7.20 = 当前核心版本）

## 5. 手动验收清单（用户 GUI 侧）

- [ ] Finder 双击 `.app` 能打开（非终端）
- [ ] 未装 CLI 机器上：健康面板明确显示 CLI 缺失 + 正确安装命令
- [ ] 已装 CLI：新建会话 → 发消息 → 流式文本 → ToolCall/ToolResult 显示
- [ ] Approval 可 Permit / Deny
- [ ] Cancel 终止当前 Run
- [ ] 关闭 Desktop 后 wire 子进程退出；重开后恢复会话且不重复执行上次工具调用
- [ ] 当前目录含空格 / home 含非 ASCII 时能启动

## 6. 状态定义（与用户口径一致）

| 能力 | 结论 |
| --- | --- |
| CLI | 正式运行入口 |
| Desktop 源码运行 | 可用 |
| Desktop 打包工具链 | 已实现，D0 已验证可产出（配置待修） |
| Desktop 安装包 | 已产出首个 ZIP（**带缺陷，未发布**） |
| Desktop 独立运行 | 不支持 |
| Desktop + 已安装 CLI | 目标可支持（架构验证通过） |
| GitHub Release | 尚未发布 |
| README 下载说明 | 已修正（声明未发布、从源码运行） |
