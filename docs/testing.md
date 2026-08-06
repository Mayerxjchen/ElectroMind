# 测试

## Python 测试

```bash
uv run pytest tests/            # 全量
uv run pytest tests/<file>      # 指定文件
```

覆盖领域：

- 核心运行时（Runner / Thread / 会话 / 检查点 / 工具调度 / 审批范围）
- Sandbox（local / container / SSH 挂载 parity，容器需本地预构建镜像，
  `ELECTROMIND_TEST_CONTAINER_IMAGE` 指向后才会跑）
- Skills（发现 / 安装 / 信任 / 目录服务 / 安装器 / Wire 管理操作）
- Artifact（状态机：completed ≠ validated ≠ accepted，SHA 完整性，训练门）
- HPC（提交记录 / reconcile / 防重复 sbatch / 幂等键 / 三入口脚本）
- CP2K Parser（成功 / 未收敛 / TIMEOUT / OOM / 截断 fixture）
- 数据完整性（原子写 / .bak 恢复 / data doctor / 磁盘空间）
- Wire 协议（命令路由 / 事件形状 / 惰性 runner）

## Desktop 测试

```bash
cd editors/desktop
npm run check                    # TypeScript（tsc --noEmit）
node --test scripts/*.test.mjs   # 全部单元测试
```

分层：

| 层 | 内容 |
|---|---|
| 纯逻辑单测 | ThreadStore / timeline-projection / skills-view / ipc-schema / 协议契约 |
| 进程测试 | Agent 进程树终止 / 打包 Agent 校验（合成 Mach-O） |
| CDP 冒烟 | 真实 Electron 渲染加载（Linux 用 xvfb） |
| 打包级测试 | standalone-smoke（干净环境 + wire + 重启恢复）、skills-manager CDP 链 |

## Golden Tasks（evals/）

```bash
python -m evals list          # 列出全部任务
python -m evals run           # 运行全部（JSON 报告）
python -m evals baseline      # 保存/刷新基线
```

66 个确定性 Golden Tasks（Planning / Tool Use / Safety / Context / Scientific /
Recovery 六类 ≥10 个）用脚本化 Provider 驱动；safety 与 recovery 类 100%
通过是发布门槛。

## CI

`.github/workflows/ci.yml` 三个 job：

| Job | 内容 |
|---|---|
| core（ubuntu） | ruff + pytest + coverage + TS check + Desktop 单测 + CDP 冒烟 + smoke 脚本语法门禁 |
| package-smoke（macOS） | Companion 打包冒烟 |
| standalone-smoke（macOS） | 构建真实 Agent（PyInstaller）→ 严格打包（--agent-bin + SHA）→ standalone 冒烟 + Skills Manager CDP 链 |

失败步骤会以 `::error::` 注解发布（checks API 可见），无需 admin 日志即可定位。

## HPC 恢复冒烟（真集群）

`scripts/hpc-recovery-smoke.mjs` 需要真实集群（aTrust + Slurm），CI 不跑
（GitHub runner 无法访问 HPC）。手动执行：

```bash
node scripts/hpc-recovery-smoke.mjs [--host ikkemhpc] [--sleep 45]
```

覆盖：提交后本地进程退出 → 远端 Job 继续运行；重启后经 rsess 恢复原 Job ID
（绝不重提）；重复 prepare 禁止二次 sbatch；rsync 收集 + SHA 核对；
Scheduler 成功但 Parser 失败 → 不标记科学成功；CP2K 成功输出 → VALIDATED。
