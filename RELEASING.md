# ElectroMind 发布流程（CLI-6）

## 产物

| 形态 | 命令 | 说明 |
|---|---|---|
| wheel / sdist | `uv build` | 标准 Python 包（`electromind = "app.cli:main"`） |
| standalone binary | `scripts/build-standalone.sh` | PyInstaller 单文件，含 tiktoken 数据 |
| GitHub Release | `scripts/release.sh --publish` | 产物 + SHA256SUMS + release notes |

## 安装方式

```bash
# uv tool（推荐，隔离环境）
uv tool install electromind

# pipx
pipx install electromind

# pip（venv 内）
pip install electromind

# standalone（免 Python）
./electromind-<version>-<platform>
```

升级：`uv tool upgrade electromind` / `pipx upgrade electromind`。
ElectroMind 不做静默自动升级：`electromind` 启动时检查新版本并提示，
`ELECTROMIND_DISABLE_UPDATE_CHECK=1` 完全禁用，`electromind update` 显式升级。

## 发版步骤

```bash
# 1. 版本号（pyproject.toml [project].version）
# 2. 构建 + 校验和
scripts/release.sh
# 3. 手动冒烟（安装后）
uv tool install dist/electromind-*.whl --force
electromind --version
electromind doctor
electromind session list
# 4. 发布
scripts/release.sh --publish --tag=v0.8.0
```

## 校验与签名

- `SHA256SUMS.txt`：所有发布产物的 sha256（发布在 Release 资产中）
- 消费者校验：`shasum -a 256 -c SHA256SUMS.txt`
- 签名（可选）：`gpg --detach-sign --armor dist/electromind-*.whl`，
  公钥发布在 GitHub 账号；脚本未内置签名步骤，发布前手动执行。

## 版本兼容承诺

- CLI 契约（flag/exit code/输出格式）见 `docs/superpowers/specs/2026-08-01-cli-professional-refactor.md`
- Harness 协议 v2 事件形状与 wire/http/CLI 客户端共用（`protocol_v2.EventEnvelope`）
- 弃用周期：`--auto/--yolo/--execution-mode/--max-turns/permission.mode=auto`
  保持可用并打印警告，删除前一个版本预告

## 安装类型可追溯

每次 Run 的 RunSnapshot 冻结 CLI 版本与工具/技能摘要；
`electromind doctor` 报告安装类型（wheel/pipx/standalone 由 importlib.metadata 与
`sys.frozen` 区分——standalone 下 `PyInstaller` 冻结标记可判）。
