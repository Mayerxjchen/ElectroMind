# pagent v0.6.1

统一 pagent home、会话列表与 SSH 工作目录；修复 VS Code「恢复会话」找错路径。

---

## Highlights

- **统一 home**：配置 / threads / skills 共用同一根  
  - A `./.pagent`（工作区已有 `.pagent/` 或遗留 `./pagent.toml`）  
  - B `~/.pagent`（否则）
- **恢复会话**：插件发 `list_threads`，由后端按 cwd 解析 home 回 `ThreadList`，与落盘一致
- **SSH 默认 workdir**：`~/pagent`（远端自动 mkdir，agent 只操作该目录）
- **VS Code**：重打包扩展；setup 写入当前 home 的 `pagent.toml`

## Install

```bash
uv tool install --force pagent
# 或开发本仓库：
# uv tool install --editable --force .
```

扩展：`editors/vscode/pagent-vscode-0.1.1.vsix`

## Notes

- 旧 thread 若冻结了 `ssh.workdir = "~/"`，需**新会话**才会用 `~/pagent`
- 会话曾落在错误目录时，可手动挪到当前 home 的 `threads/`

## Links

- Docs: https://synclionpaw.github.io/pagent/
- Repo: https://github.com/SyncLionPaw/pagent
- Compare: https://github.com/SyncLionPaw/pagent/compare/v0.6.0...v0.6.1
