# 发布

## 1. Standalone Agent（macOS）

```bash
scripts/build-standalone.sh        # PyInstaller 单文件 → dist/electromind-<ver>-<plat>
```

产物无需 Python 环境；内置冒烟（首次启动物化默认配置）+ SHA-256 校验和
（`dist/SHA256SUMS-standalone.txt`）。

## 2. Desktop 打包（macOS Standalone）

```bash
cd editors/desktop
node scripts/package.js --agent-bin ../../dist/electromind-<ver>-<plat> \
  --agent-sha256 <SHA256>
```

- **必须显式指定 Agent 二进制**；缺失 / 版本 / 架构不匹配 → 构建失败
- 打包时执行 Agent `version` 子命令校验版本一致；嵌入后写出
  `agent.sha256`（可选 `--agent-sha256` 强制核对）
- 找不到 Agent 时**禁止静默降级为 Companion**——除非显式
  `--allow-companion`（开发用）
- 产物：`release/electromind-Desktop-<ver>-arm64/electromind Desktop.app`

## 3. dmg 安装包（macOS）

```bash
scripts/build-dmg.sh               # → release/electromind-Desktop-<ver>-arm64.dmg
```

拖拽安装式：App + Applications 快捷方式 + 卷图标，`hdiutil` 压缩为 UDZO 并校验。

## 4. 安装与验收

```bash
# 安装
cp -R "release/.../electromind Desktop.app" /Applications/
xattr -dr com.apple.quarantine "/Applications/electromind Desktop.app"   # 如需要

# 冒烟
cd editors/desktop
node --test scripts/standalone-smoke.test.mjs        # 干净环境 + wire + 重启恢复
node --test scripts/skills-manager-cdp.test.mjs      # Skills 完整操作链
```

> 未签名（ad-hoc）：本地使用无碍；对外分发需 Apple 开发者账号公证
> （`codesign --options runtime` + notarize + staple），否则对方首次打开需
> 右键 → 打开。

## 5. 发布到 GitHub Release

前置：`gh` CLI 已安装并登录（`gh auth status` 确认），SSH/git 推送正常。

```bash
# 5.1 确认版本号一致（package.json 与 pyproject.toml）
node -p "require('./editors/desktop/package.json').version"

# 5.2 tag 指向当前 main（发布必须关联最新代码，避免关联旧 commit）
git tag -f v<VER> main
git push origin v<VER> --force

# 5.3 创建 Release 并上传 DMG + zip（产物见第 3、4 步）
~/bin/gh release create v<VER> \
  "editors/desktop/release/electromind-Desktop-<VER>-arm64.dmg" \
  "editors/desktop/release/electromind-Desktop-<VER>-mac-arm64.zip" \
  --repo Mayerxjchen/ElectroMind \
  --title "ElectroMind <VER>" \
  --notes "ElectroMind Desktop <VER> — macOS (Apple Silicon)

包含：
- \`electromind-Desktop-<VER>-arm64.dmg\` — 拖拽安装包
- \`electromind-Desktop-<VER>-mac-arm64.zip\` — zip 版

> 未经 Apple 公证，首次打开需 右键 → 打开。"

# 5.4 验证
~/bin/gh release view v<VER> --repo Mayerxjchen/ElectroMind
```

> 只发布 DMG + zip 两个安装包（裸 agent 二进制属构建中间产物，不对外）。
> 附件删除：`gh release delete-asset v<VER> <文件名> --repo Mayerxjchen/ElectroMind --yes`。
> Python 包（wheel/sdist）走 `scripts/release.sh --publish`，与 Desktop 安装包分开。

## 6. CI

推送 main / PR 自动跑（`.github/workflows/ci.yml`）：

- core：Python 测试 + TS check + Desktop 单测 + CDP 冒烟
- package-smoke：Companion 打包冒烟（macOS）
- standalone-smoke：真实 Agent 构建 + 严格打包 + 双冒烟（macOS，仅 main）

## 暂缓

- Windows / Linux Standalone
- 自动更新与回滚
- 正式多平台安装器
