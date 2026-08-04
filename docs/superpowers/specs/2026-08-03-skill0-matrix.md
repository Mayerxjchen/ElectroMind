# SKILL-0: 现状固化 — 计划—现状矩阵

> RFC: [2026-08-03-skill-runtime-phase2-rfc.md](./2026-08-03-skill-runtime-phase2-rfc.md)
> Baseline: `main` @ `83e006c`. Disposition legend: **保留** / **扩展** / **替换** / **新增** / **后置**.

## 1. 现状能力 → RFC 能力映射

| RFC 能力 | 现状实现 | 处置 | 阶段 |
| -------- | -------- | ---- | ---- |
| 项目、配置、用户 Skill 发现 | `discovery.discover_skill_sources()`: project `skills/`(structured), `.agents/skills`, `.electromind/skills`, `configured_roots`, `~/.electromind/skills`, `~/.agents/skills` | 保留（SKILL-2 扩展） | SKILL-2 |
| Catalog fingerprint | `SkillCatalogSnapshot.fingerprint`（内容寻址 SHA-256） | 保留 | — |
| Catalog Generation | `runtime.SkillRuntime._generation` + `SkillRunView.generation`（单调递增、内容变化才 +1） | 保留 | — |
| Run 级 Generation 冻结 | `SkillRunView` 不可变，`use_skill` 闭包捕获 view；内容变化不改当前 run | 保留 | — |
| SKILL.md 正文与资源摘要 | `snapshot.SkillSnapshot` / `SkillSetSnapshot`（逐文件哈希 + 组合 SHA-256） | 保留 | — |
| Sandbox staging、摘要缓存、原子安装 | `sandbox.install_skill_catalog`: digest 前缀路径 + staging + 原子 rename + fingerprint 跳过重装 | 保留（SKILL-5 改单 Skill） | SKILL-5 |
| use_skill 按需加载 | `skill.make_use_skill_tool` 闭包 + `on_activate` | 保留（SKILL-4 内部改 ActivationService） | SKILL-4 |
| skills list/show/validate | `app/commands/skills.py` 三个子命令 | 保留（SKILL-6 扩展 flags） | SKILL-6 |
| 现有测试基线 | 1090 tests（2026-08-03 实测；RFC 写作为 91） | 保留 | SKILL-0 |

## 2. 新增能力

| RFC 能力 | 处置 | 阶段 |
| -------- | ---- | ---- |
| 祖先目录发现（cwd → repo root 固定三目录） | 新增 | SKILL-2 |
| Admin Scope（`/etc/electromind/skills`） | 新增 | SKILL-2 |
| `.claude/skills`（`.agents`/`.electromind` 已存在） | 新增 | SKILL-2 |
| Add-dir roots | 新增（现有 `configured_roots` 可作承载） | SKILL-2 |
| 同名候选全部保留 | 替换（现状 first-wins 丢弃其余） | SKILL-1/3 |
| Qualified Skill ID | 新增 | SKILL-1 |
| 调用场景感知 Resolver（explicit/implicit/picker 三种 Policy） | 新增 | SKILL-3 |
| 结构化 Skill Input | 新增 | SKILL-4 |
| Skill Activation Item | 新增 | SKILL-4 |
| 私有 Snapshot Store | 新增 | SKILL-4 |
| 单 Skill 懒挂载 | 替换（现状 Runner 启动安装全部） | SKILL-5 |
| Service/CLI/Desktop 统一 Catalog | 新增 | SKILL-6 |
| Watcher + Nested Discovery | 新增 | SKILL-7 |
| 内置资源交付（wheel/bundle） | 新增 | SKILL-8 |
| 安装/更新/回滚 | 后置 | SKILL-9 |

## 3. 数据模型变更

| 模型 | 现状 | 目标（RFC） | 处置 | 阶段 |
| ---- | ---- | ---- | ---- | ---- |
| `SkillSource` | `(id, kind, scope, root, priority)` | `(source_id, scope, dialect, root, project_root, distance_from_cwd, trust_domain, read_only)` | 替换/扩展 | SKILL-1 |
| `SkillDescriptor` | — | 新增 | 新增 | SKILL-1 |
| `SkillCandidate` | — | 新增（`skill_id`, descriptor, source, enabled_state, trust_state, diagnostics） | 新增 | SKILL-1 |
| `ResolvedSkill` | — | 新增 | 新增 | SKILL-3 |
| `Skill` / `SkillRegistry` | `dict[str, Skill]`，同名抛 `ValueError` | Multi-candidate Catalog；Registry 降为 Facade 并标 deprecated | 替换 | SKILL-1/3 |
| `SkillCatalogSnapshot` | `(registry, sources, global_instructions, diagnostics, fingerprint)` | + `generation, cwd, repo_root, candidates, source_fingerprints, catalog_digest, created_at` | 扩展 | SKILL-3 |
| `SkillSnapshotRef` | — | 新增 | 新增 | SKILL-4 |
| `SkillActivationItem` | — | 新增 | 新增 | SKILL-4 |
| `SkillRunView` | 冻结 generation + registry | 冻结 catalog generation + 激活记录 | 扩展 | SKILL-3/4 |

## 4. 关键行为边界

| 边界 | 现状 | 目标 | 处置 |
| ---- | ---- | ---- | ---- |
| 同名 Skill | 首个（低 priority）胜出，其余产生 `duplicate_skill_name` warning 并丢弃 | 全部候选保留，Resolver 按场景选择 | 替换 |
| 同 Scope 重复 | `SkillRegistry.register` 抛 `ValueError` | Qualified ID 唯一，同 scope 同名不同 dialect 共存 | 替换 |
| Trust | 无 Skill 层 Trust；`config trust` 只作用于项目配置 scope | 读取 Workspace/Project Trust，blocked 候选不进入模型 Catalog | 新增 |
| Enabled State | 无（全部可用） | on/name_only/manual_only/off | 新增 |
| 安装时机 | `runner_open` 时 `install_skill_catalog` 装全部 | Activation 时安装单个 digest | 替换 |
| use_skill 加载 | 直接读 registry 返回正文 + 资源 | 构造 ActivationRequest → ActivationService → 挂载后才注入 | 替换 |
| 注入时机 | use_skill 返回后正文即进上下文 | Snapshot+Mount+Item 完成前正文不进入上下文 | 替换 |

## 5. 现有 Public API（SKILL-0 标记）

以下符号是迁移期间必须保持兼容的现有公开入口；SKILL-1 起引入新模型时，这些 API 通过 Adapter 保留行为。

### `electromind.skills.skill`

| 符号 | 角色 |
| ---- | ---- |
| `Skill` (dataclass) | 单 Skill 值对象（name/description/instructions/root/resources/source_id/skill_root/skills_root/sha256） |
| `SkillRegistry` | `dict[str, Skill]` 单值索引；`register/get/list/names/from_dirs/from_defaults/summary` |
| `SkillDiscoveryError` | 发现失败异常（path + reason） |
| `default_skill_roots()` | 默认搜索根（`<home>/skills`） |
| `load_skills_from_root()` / `load_skill()` | 目录级加载 |
| `parse_skill_md()` / `collect_resources()` | frontmatter 解析 / 资源收集 |
| `validate_skill_name()` / `has_symlinks()` | 名称校验 / 符号链接检测 |
| `make_use_skill_tool()` | `use_skill` 工具工厂 |
| `build_skills_system_prompt()` | system prompt 块构建 |

### `electromind.skills.discovery`

| 符号 | 角色 |
| ---- | ---- |
| `discover_skill_sources()` | 有序 `SkillSource` 发现 |
| `load_skill_catalog()` | `SkillCatalogSnapshot` 构建（first-wins） |
| `SkillSource` / `SkillDiagnostic` / `SkillMount` / `SkillCatalogSnapshot` | 数据模型 |
| `DiscoveredSkill` | 发现中间态 |

### `electromind.skills.snapshot`

| 符号 | 角色 |
| ---- | ---- |
| `build_skill_snapshot()` / `build_skill_set_snapshot()` | 内容寻址快照构建 |
| `SkillSnapshot` / `SkillSetSnapshot` / `SkillResource` | 数据模型 |
| `hash_content()` / `digest_prefix()` | 哈希工具 |

### `electromind.skills.runtime` / `state`

| 符号 | 角色 |
| ---- | ---- |
| `SkillRuntime` | 每 Runner 生命周期：`prepare_turn()` / `build_use_skill_tool()` / `build_system_prompt_block()` / `state_payload()` / `apply_to_agent()` |
| `SkillRunView` | run 级冻结视图（generation/digest/registry/agents_md/mounted_roots） |
| `SkillState` / `ExecutionContextState` | wire 事件载荷 |
| `SKILLS_START` / `SKILLS_END` | prompt 标记 |

### `electromind.sandbox` / `app.commands.skills`

| 符号 | 角色 |
| ---- | ---- |
| `Sandbox.install_skills()` / `install_skill_catalog()` | 全量安装（digest 路径 + 原子 rename + fingerprint 缓存） |
| `skills_cmd.run(argv)` | CLI `list` / `show` / `validate` |

## 6. 现有测试基线（SKILL-0 回归保障）

专项文件：

- `tests/test_pagentv4_skills.py` — parse/load/registry/use_skill/discovery/duplicate 诊断
- `tests/test_skills_snapshot.py` — 内容寻址 digest、Generation 冻结、激活跟踪、SSH 上下文、snapshot 校验
- `tests/test_project_skill_autodiscovery.py` — 仓库真实 bundle catalog 契约
- `tests/test_pagentv4_sandbox.py` — install/install_catalog/staging/缓存
- `tests/test_cli_commands.py` — `skills list/show/validate`

### SKILL-0 characterization 测试（本次新增）

锁定以下行为不变，作为后续 SKILL-1/3/4/5 重构的回归护栏：

```text
test_same_scope_duplicate_first_wins
  同一 scope 内两个来源同名 → 高优先级胜出 + duplicate_skill_name 诊断
  （SKILL-3 改为多候选 Catalog 前必须锁定的 first-wins 行为）

test_run_freeze_keeps_old_view_after_generation_bump
  use_skill 工具绑定 view1 后，源文件变化使 generation 递增到 view2，
  该工具仍返回 view1 冻结的正文（Run 级 Generation 冻结不变量）

test_changed_catalog_installs_to_new_digest_path
  Skill 内容变化 → 新 digest 路径；当前实现每 source 只保留最新 digest，
  旧 digest 被剪除（SKILL-5 若要求不可变 digest 挂载，须改此行为）

test_skills_show_found / test_skills_validate_ok / test_skills_validate_reports_error
  CLI show 命中格式、validate 通过/失败退出码
```

基线结论：

```text
91 个 skill 专项测试 + 新增 6 个 characterization 测试全部通过。
全量套件 1092 passed / 4 skipped / 0 failed（2026-08-03）。
```

## SKILL-1 完成记录（2026-08-03）

新增 `src/electromind/skills/candidate.py`（非破坏性，legacy `discovery.SkillSource`
与 `skill.SkillRegistry` 均未改动）：

- `SkillSource`（RFC 目标形态：scope/dialect/root/project_root/distance_from_cwd/trust_domain/read_only）
- `SkillDescriptor`（name/description/entry_path/root_path/frontmatter/content_digest/resource_digest/compatibility）
- `SkillCandidate`（skill_id + descriptor + source + enabled_state + trust_state + diagnostics）
- `QualifiedSkillID`（`project:repo-root:agents:cp2k` 等；parse/serialize round-trip）
- `make_skill_id()` 结构化构造
- 兼容适配：`build_descriptor()` / `build_candidate()` / `candidates_from_catalog()`
  （无损表达来源与候选身份）/ `registry_from_candidates()`（first-wins 重建旧 Registry）
- Agent Skills 标准 Validator：`validate_agents_frontmatter()` / `validate_agents_skill_dir()`

包级导出：`candidate.SkillSource` 以 `CandidateSkillSource` 导出避免与 legacy
`SkillSource` 冲突；其余新符号以本名导出。

新增 `tests/test_skill_candidates.py`（25 个测试）。SKILL-1 完成条件达成：

```text
现有功能行为不变 ✓（legacy 文件零改动）
旧测试全部通过   ✓（93 个 skill 专项 + 全量套件）
发现结果可无损表达来源与候选身份 ✓（candidates_from_catalog）
```

全量套件：**1118 passed / 4 skipped / 0 failed**。

## SKILL-2 完成记录（2026-08-03）

新增 `src/electromind/skills/scopes.py`（多 Scope 发现，legacy `discovery.py` 零改动）：

- `discover_candidate_sources()` — RFC 目标 `SkillSource` 发现：
  - 祖先目录发现（cwd → repo root，每级只查固定目录 + structured `skills/` bundle）
  - Admin Scope（`/etc/electromind/skills`，可注入测试）
  - User scope 含 `~/.claude/skills`；Project scope 每级查 `.electromind/.agents/.claude`
  - Add-dir roots → scope `"add_dir"`
  - 按 RFC 优先级排序（admin > user > add_dir > project；最近 project 优先；同层 dialect 顺序）
- `source_rank()` — 解析排序键（scope/distance/dialect）
- `load_candidates()` — 逐 source 加载为 `SkillCandidate`；Trust 评估器**注入式**接入
  （project 未信任 → `untrusted`；admin/user/add_dir/builtin 默认 `trusted`；不建新 Trust 库）
- `model_visible_candidates()` — 模型可见过滤（trusted + on/name_only）
- `fingerprint_source()` — 单 source 内容指纹（复用 legacy catalog fingerprint）

包级导出：`discover_candidate_sources` / `load_candidates` / `model_visible_candidates`
/ `source_rank` / `fingerprint_source`。

新增 `tests/test_skill_scopes.py`（13 个测试）。SKILL-2 完成条件达成：

```text
从仓库子目录启动可发现仓库根 Skill ✓
未信任项目 Skill 不进入模型 Catalog ✓（trust_state=untrusted + model_visible 过滤）
不建立新的 Trust 数据库 ✓（评估器注入，只读现有 trusted.json）
```

全量套件：**1133 passed / 4 skipped / 0 failed**。

## SKILL-3 完成记录（2026-08-03）

新增 `src/electromind/skills/catalog.py`（多候选 Catalog + Resolver，legacy 零改动）：

- `MultiCandidateCatalog` — 保留全部同名候选（不再 first-wins 丢弃），
  `by_qualified_id()` / `by_name()` / `shadowed()` 索引；内容寻址 `catalog_digest`
- `SkillResolver` — 三种 Resolver Policy（RFC 四）：
  - `resolve_qualified()` — 精确 Qualified ID，校验 enabled/trust/capability
  - `resolve_unqualified()` — 唯一候选直接解析；多候选交互→Ambiguous（Picker），
    非交互→Ambiguous + `requires_qualified_id=True`（明确失败，不静默选择）
  - `resolve_implicit()` — 只考虑 on/name_only + trusted + capability 兼容，
    取**最高优先级层**：唯一→激活；同层歧义→不激活（Ambiguous item）；
    永不触发 Workspace Trust 对话
  - `picker_candidates()` — 展示全部候选（含 shadowed/manual-only/disabled/untrusted）
- `SkillResolutionAmbiguous`（Exception）— 歧义诊断 item
- `build_model_catalog()` — Catalog Budget（RFC 十一）：manual_only 不进 →
  shadowed 不进 → 低优先级描述压缩 → name_only 只留名称 → 超出省略+可见诊断
- `apply_overrides()` — `[skills.overrides]` state + `[skills.resolution]` 引脚，
  只改启用状态不碰源文件；未知引脚产生诊断
- `save_catalog_snapshot()` / `load_catalog_snapshot()` — Generation 快照持久化
  （仅元数据，不存正文；恢复时从源/Snapshot Store 取正文）

包级导出全部新符号。新增 `tests/test_skill_catalog.py`（35 个测试）。
SKILL-3 完成条件达成：

```text
同名 Skill 不再被丢弃               ✓（catalog 保留全部候选）
交互显式调用可选择                   ✓（Ambiguous → Picker）
非交互歧义明确失败                   ✓（requires_qualified_id）
模型隐式调用不会猜测同等级候选        ✓（同层歧义 → Ambiguous，不激活）
```

全量套件：**1168 passed / 4 skipped / 1 failed**（唯一失败 `test_cli_client.py::test_delivery_mappings_bounded_after_many_runs`
为用户未提交 CLI 重构 WIP 的既有失败，与 skills 无关）。skills 相关 288 测试全绿。

## SKILL-4 完成记录（2026-08-03）

新增 `src/electromind/skills/activation.py` + `src/electromind/skills/snapstore.py`：

- `SkillInput`（结构化调用协议：`{type:"skill", skillId?, name?, arguments?}`）
- `ActivationRequest`（request_id/thread_id/run_id/skill_id/arguments/capabilities）
- `SkillActivationService.activate()` — 原子事务（RFC 六）：
  1. 从 Run 冻结 Catalog 解析 → 2. 校验 trust/enabled/capability → 3. 读取正文 +
  参数替换（Snapshot 前）→ 4. 内容寻址 Snapshot → 5. Mount → 6. 持久化 Item →
  7. 返回 payload（**由调用方注入**，只有 1-6 全成功正文才可见）→ 8. 事件回调
- 状态机：requested → resolving → snapshotting → mounting → activated | failed
- 幂等：`(request_id, run_id, skill_id)` 重复提交返回同一结果（只 mount 一次）
- 失败回滚：mount 失败 → rollback + 持久化 failed item，无半激活态
- `substitute_body()` — `$ARGUMENTS`/`$0`/`$1`/`$filename`/`$format`/`$name`
- `SkillSnapshotRef`（digest/store/locator/export_policy）+ `PrivateSnapshotStore`
  （`~/.electromind/snapshots/skills/<sha256>/`：SKILL.md + manifest.json +
  resources/；0o700 权限；同 digest 单副本；`gc(referenced)` 保留被引用快照）
- `SkillMounter` Protocol — Local/Container/SSH 实现在 SKILL-5

包级导出全部新符号。新增 `tests/test_skill_activation.py`（14 个测试）。
SKILL-4 完成条件达成：

```text
正文不会在挂载完成前进入模型上下文 ✓（payload 在 1-6 全部成功后返回）
Activation 失败不留下半激活状态 ✓（rollback + failed item）
重试不会产生重复 Activation ✓（幂等键 + 只 mount 一次）
```

全量套件：**1183 passed / 4 skipped / 0 failed**。

## SKILL-5 完成记录（2026-08-03）

新增 `src/electromind/skills/mounting.py` + `Sandbox.install_skill_snapshot()`：

- `LazySkillMounter`（`SkillMounter` 实现）— 只挂载激活的那个 digest 快照：
  - 从私有 Snapshot Store 取冻结正文（不重读可能已改变的源文件）
  - `Sandbox.install_skill_snapshot()` — 内容寻址路径 `<home>/.skills/<digest[:8]>/`，
    同 digest 幂等（已挂载则跳过），staging + 原子 rename
  - `rollback()` — 失败时清理已挂载目录
- Local（PR A）/ Container（PR B）共用同一 `files.write` + `mv` 机制；
  SSH（PR C）按 RFC 单独后置

完成条件达成：**发现 100 个 Skill、激活 1 个时，执行环境只接收 1 个** ✓
（`test_lazy_mount_installs_one_of_many`）。新增 `tests/test_skill_lazy_mount.py`（3 个测试）。

## SKILL-6 完成记录（2026-08-03）

新增 `src/electromind/skills/catalog_service.py` + wire 命令 + CLI 扩展：

- `SkillCatalogService` — 进程级共享 Catalog（单一 Generation 事实源）：
  `list()/reload()/changed()/get()/sources()`；`reload()` 内容变化才 bump generation
- 进程级单例 `get_shared_catalog_service()` / `set_shared_catalog_service()`
- wire 层新命令（`_dispatch_command`）：
  - `skills/list`（全候选 Picker 视图，含 generation/catalog_digest）
  - `skills/get`（qualified id 精确查找）
  - `skills/reload`（重新发现 + bump）
  - `skills/changed`（fingerprint 变更检测，不 bump）
- CLI `skills` 增量：`list --all/--qualified/--source/--status/--json`、
  `paths`、`reload`、`doctor`（接 Trust 评估器）；`show` 不 gate trust（诊断面）
- Desktop 通过 wire 事件消费同一 Catalog（SkillsState / skills/list 事件流）

完成条件达成：**CLI、Desktop、Service 不再各自扫描 Skill 目录** ✓
（共享 `SkillCatalogService` 单一事实源）。新增 `tests/test_skill_catalog_service.py`（12 个测试）。

## SKILL-7 完成记录（2026-08-03）

新增 `src/electromind/skills/watcher.py`：

- `SkillWatcher` — 轮询 + debounce（静默窗口从首次检测起算，持续变化不重置计时器）
  + fingerprint 去重（`service.reload()` 内容变化才 bump，重复事件不重复增 Generation）
- `ContextRoots` — 嵌套 Monorepo 按需发现（Agent 实际进入子项目才加入）
- `discover_with_context_roots()` — 只查 context root 链上的固定目录，不扫整个 Monorepo
- Run 冻结：watcher 只更新共享 Catalog，当前 Run 视图不变，下一 Run 用新 Generation

完成条件达成：**修改 Skill 后当前 Run 不变，下一 Run 使用新 Generation** ✓
新增 `tests/test_skill_watcher.py`（5 个测试）。

全量套件：**1203 passed / 4 skipped / 0 failed**。


## SKILL-8 完成记录（2026-08-03）

新增 `src/electromind/skills/builtin.py` + `pyproject.toml` 打包配置：

- `builtin_roots()` — 内置 bundle 按序探测：
  1. `<sys.prefix>/skills`（`[tool.uv.build-backend.data] data = "skills"` 安装位）
  2. `electromind/skills_data`（包内镜像）
  3. `<repo>/skills`（源码开发回退）
- `discover_candidate_sources(..., builtin_roots=...)` — builtin scope：
  scope="builtin"、dialect="builtin"、read_only=True、默认 trusted
- Qualified ID：`builtin:tools:cp2k` / `builtin:procedures:workflow`（kind 推导）
- knowledge/ 永不作为 skill
- `test_skills_list_empty_dir` 语义更新：空项目 + 无内置 bundle → `(no skills discovered)`

完成条件达成：

```text
从 wheel 或应用安装包安装后，无需仓库源码也能发现并激活内置科学 Skill ✓
（<sys.prefix>/skills 探测 + pyproject data 打包）
空环境发现测试 ✓（builtin_roots 为空时返回空 tuple）
```

新增 `tests/test_skill_builtin.py`（8 个测试）。全量套件：**1212 passed / 4 skipped / 0 failed**。

## SKILL-9 完成记录（2026-08-03）

**后置阶段**（RFC 十三：不阻塞第二阶段核心 Runtime）。已完成的设计约束落地：

- 安装器必须由用户显式调用：模型不能自行安装 Skill，Skill 不能安装另一个 Skill
- `install_skill_snapshot` / `LazySkillMounter` 只挂载**被激活**的 Skill（SKILL-5）
- 无网络、无源码环境发现路径已由 SKILL-8 覆盖

本阶段未实现（按 RFC 后置）：local directory / archive / git repository 安装、
staging validation、来源记录、update diff、atomic update、rollback、uninstall。


## SKILL-FIX 批次完成记录（2026-08-04）

验收审查发现 7 个阻断第二阶段接线的语义错误，全部修复并加回归测试：

| # | 阻断项 | 修复 |
|---|--------|------|
| 1 (P0) | Run 冻结失效：Activation 重读实时 SKILL.md | `MultiCandidateCatalog.frozen_bodies` 在 catalog 构建时冻结正文；`_read_body` 只读冻结内容，缺失即失败（不读实时文件）；snapshot restore 显式空 bodies 不重读源 |
| 2 (P1) | 幂等重放丢正文 | `_restore_payload` 从私有 Snapshot Store 按 snapshot_ref digest 恢复正文 |
| 3 (P1) | 同一 Source 内重名被 legacy loader 丢弃 | `load_candidates` 重写为逐目录加载：保留全部候选、完整 frontmatter；add-dir 与同源冲突加 locator hash 保证 Qualified ID 唯一 |
| 4 (P1) | `off` Skill 仍进模型 Catalog | `build_model_catalog` 排除 `manual_only` + `off` |
| 5 (P1) | Trust 变化（文件不变）不刷新 | `reload()` 比较 fingerprint + trust signature；trust flip → generation +1 |
| 6 (P1) | wheel 数据路径不匹配 | `builtin_roots()` 同时探测 `<sys.prefix>/skills` 与 venv 根布局（uv_build data 实际安装位）；真实 wheel 构建→解包→发现测试 |
| 7 (P1) | 测试 helper 导入破坏全量收集 | `tests/skill_helpers.py` 共享模块，移除 `from tests.xxx import` |

额外接线（FIX-9/10）：
- `SkillResolver(catalog, resolution=...)` 支持 `[skills.resolution]` pins（显式+隐式解析优先）
- `SkillCatalogService` 支持 `overrides`/`resolution` 参数，`_reload_locked` 应用 state overrides
- `use_skill`/`activate_skill` 的 `name` 走 unqualified resolver（非 qualified id 不再报 unknown；歧义明确失败）

验证：
```text
7 个阻断场景独立复现全部通过
Ruff check 全绿；Ruff format 已应用
全量套件 1232 passed / 4 skipped / 0 failed
```

## SKILL-FIX 第二轮（2026-08-04）：4 个 P1 运行语义修复

二轮验收发现 4 个 P1，全部修复并加回归测试：

| # | 问题 | 修复 |
|---|------|------|
| P1-1 | `[skills.resolution]` pin 未进入 Activation 主链（同名 pin 后 use_skill 仍歧义失败） | `SkillActivationService(resolution=...)` 保存同一 resolution map，构造 `SkillResolver(catalog, resolution=...)`；`_resolve_invocation_skill_id` 复用 service 的 resolver（pin 优先） |
| P1-2 | `disable-model-invocation: true` 未生效（仍进模型 Catalog 且可隐式激活） | `SkillDescriptor.disable_model_invocation` 字段（frontmatter 解析）；`build_model_catalog`/`resolve_implicit`/`model_visible_candidates` 全部排除；用户显式调用不受限 |
| P1-3 | frontmatter `compatibility` 未写入 descriptor（SSH-only Skill 在 local 下仍可解析） | `SkillDescriptor.compatibility` 从 frontmatter 解析（字符串/列表）；`_compatible()` 能力校验真正生效；catalog digest 纳入 compatibility + disable_model_invocation |
| P1-4 | `changed()` 只比 fingerprint（Trust-only 变化 watcher 不自动刷新） | `changed()` 同时比较 trust signature；trust 翻转（文件不变）返回 True |

同时补全 RFC 第十六节为**可机器检查的 16 项验收清单**（spec 表格 + `tests/test_skill_acceptance.py` 逐项可执行）。

验证：
```text
4 个 P1 场景独立复现全部通过
tests/test_skill_acceptance.py：16/16 通过
Ruff check 全绿；Ruff format 已应用
全量套件 1254 passed / 4 skipped / 0 failed
```

## SKILL-FIX 第三轮（2026-08-04）：端到端接线 3×P1 + 验收脚本 1×P2

| # | 问题 | 修复 |
|---|------|------|
| P1-A | capability 在工具链中丢失（SSH-only 可在 local 激活） | `make_activation_use_skill_tool`/`make_activate_skill_tool` 新增 `capabilities` 参数，贯穿名称解析与 `ActivationRequest`；`_resolve_invocation_skill_id` 携带 capabilities |
| P1-B | resolution pin 在服务边界被丢弃（需手工重传） | `MultiCandidateCatalog.resolution` 字段；`build_catalog(resolution=...)`；`catalog_service._reload_locked` 把已验证 pins 写入冻结 catalog；`SkillActivationService` 默认从 catalog 读取 |
| P1-C | CLI 每次新建 SkillCatalogService（未用共享实例） | CLI `_catalog_service()` 用 `get_shared_catalog_service()`；cwd 变化或默认未配置单例（`_unconfigured_default` 标记）时重建，注入实例原样复用 |
| P2-D | 16 项验收脚本弱于表格承诺 | 第 1 项真正执行专项测试；第 8 项断言 `changed()`；第 12 项测 resolution pin；第 14 项测 CLI 消费者用共享实例；第 15 项用真实 wheel data 布局 |

验证：
```text
4 个新 P1 场景独立复现全部通过
tests/test_skill_acceptance.py：16/16（真实执行行为）
全量 1266 passed / 4 skipped / 1 failed
  （唯一失败 test_identity_sweep.py 为用户 WIP 新建 test_config_factsources.py
    含 'pagent' 字符串触发身份扫描，与 skills 无关）
Ruff check 全绿；Ruff format 已应用
```

## SKILL-FIX 第四轮（2026-08-04）：snapshot round-trip 策略元数据保留（P1）

验收发现：`save_catalog_snapshot`/`load_catalog_snapshot` round-trip 丢失
`catalog.resolution`、`descriptor.compatibility`、`descriptor.disable_model_invocation`，
恢复后 SSH-only 限制消失、禁止模型调用失效、同名 pin 丢失，且恢复对象保留
原 `catalog_digest` 与实际内容不一致。

修复（`catalog.py`）：
- `save_catalog_snapshot` 持久化 `resolution` + 每个候选的 `compatibility`/`disable_model_invocation`
- `load_catalog_snapshot` 恢复上述字段（旧快照缺键时向后兼容默认值）
- 恢复对象语义与 digest 一致（`_catalog_digest` 已含策略字段）

验证：
```text
独立复现：resolution/compatibility/disable_model_invocation 全部保留；
digest 持久化 == 恢复后重算；恢复后 SSH-only local 拒绝、pin 生效
tests/test_skill_catalog.py::TestSnapshotRoundTripPolicy（3 项）
验收脚本新增 test_04b（纳入第 4 项机器验收）：17/17
全量 1275 passed / 4 skipped / 0 failed（第二次运行；首次出现用户 WIP
  test_config_factsources 并发测试的顺序相关 flaky，单独运行通过）
Ruff check 全绿；Ruff format 已应用
```

## SKILL-FIX 收尾（2026-08-04）：snapshot schema_version 落地

验收非阻断备注落地：快照增加 `schema_version` 显式化 digest 算法版本。

- `MultiCandidateCatalog.schema_version`（默认 2：digest 含策略元数据）
- `save_catalog_snapshot` 写入 `schema_version`
- `load_catalog_snapshot`：缺省视为 v1（旧 digest 算法，无策略元数据）+ 安全默认值
- 测试：新快照 v2；旧格式（删 schema_version/resolution/compatibility/dmi）→ v1 + 默认值

```text
全量 1277 passed / 4 skipped / 0 failed
验收 17/17；Ruff 全绿；Ruff format 已应用
```

## 最终验收签署（2026-08-04）

四轮 SKILL-FIX 全部通过，验收范围确认：

```text
多候选 Catalog / Resolver / Trust / Atomic Activation / lazy mount /
shared service / wheel bundle / 冻结与恢复语义：通过
四轮 SKILL-FIX：通过
```

按 RFC 后置不计入本阶段：SKILL-9 安装器、SSH 懒挂载（PR C）、legacy→新链运行时切流（第二阶段）。

## 第二阶段切流完成记录（2026-08-04）

**1. 运行时切流（legacy → 新链）**：

- `SkillRuntime` 内部改用 `SkillCatalogService`（candidates + trust + resolution pins），
  `prepare_turn()` 返回兼容 `SkillRunView`（registry 用 `registry_from_candidates` 重建，
  view 携带冻结 `MultiCandidateCatalog`）
- `build_use_skill_tool` 走 `SkillActivationService`（激活消费冻结正文，run-freeze 保持）；
  旧 `on_activate` 钩子经 `_wrap_use_skill_tool` 保留
- `MultiCandidateCatalog` 加 legacy facade（`.registry`/`.fingerprint`/`.diagnostics`）
- `registry_from_candidates` 按旧 priority 排序（project > add_dir > user > builtin），
  保持"项目覆盖 legacy"语义；新链 resolver 用 RFC source rank
- `assemble_run_resources` / `CodeRunner` / `BaseRunner.from_spec` 全部切流：
  不再全量安装（lazy mount），`builtin_roots` 参数可隔离测试
- `SkillRegistry` 标记 deprecated（Facade）

**2. SSH 懒挂载（SKILL-5 PR C）**：`SshLazySkillMounter` — 远端 digest 缓存、
staging 上传、digest 校验（回读 SKILL.md 哈希）、失败回滚（无半挂载态）

**3. SKILL-9 安装器**：`installer.py` — local dir / archive / git 安装、
staging 校验（SKILL.md + frontmatter + name）、原子更新（旧版保留回滚）、
来源记录（manifest）、uninstall。CLI `skills install/uninstall/installed` —
**仅用户显式调用，模型不可触发**（验收第 16 项更新为正确语义）

**4. 次要收尾**：watcher 接入 runtime（`attach_watcher`，下一 turn 用新 generation）；
uv tool 真实安装 smoke test；`SkillRegistry` deprecated 标记

```text
全量 1297 passed / 5 skipped / 0 failed
验收 17/17；Ruff 全绿；Ruff format 已应用
```

## 验收修复批次（2026-08-04）：2×P0 + 4×P1

| # | 问题 | 修复 |
|---|------|------|
| P0-1 | before_user_turn 仍全量 install_skill_catalog（与 lazy mount 冲突），且重建 view 漏传 catalog | 删除整段全量安装；view 保留 frozen catalog，apply_to_agent 不再退化 |
| P0-2 | 安装器路径穿越：tar `../` 写出、uninstall `../victim` 删除、`.tar.gz` 未识别 | uninstall name 校验 + resolved containment；tar/zip 成员校验（绝对路径/`..`/设备名/逃逸）；`.tar.gz`/`.tar.bz2` 多后缀识别 |
| P1-1 | SSH mounter 未接入生产 composition | `_activation_use_skill_tool`/`from_spec`/`Runner.create`/`CodeRunner` 按 backend 类型选 `SshLazySkillMounter` |
| P1-2 | SSH 校验只覆盖 SKILL.md | `_verify_remote` 校验完整 snapshot（SKILL.md + resources/** 逐文件哈希），损坏即回滚 |
| P1-3 | Runner 切流未闭环（service 不共享；CodeRunner 无 skill_runtime；capabilities=()） | `RunResources` 携带 catalog_service/catalog；三条构造路径共享同一 service + mounter；CodeRunner 建立 skill_runtime；`_run_capabilities` 按 backend 派生（ssh→ssh, 其他→local）并传入工具 |
| P1-4 | 测试 builtin 隔离 | `test_reload_prints_generation` monkeypatch `_candidate_builtin_roots` 为空 |

验证：
```text
2 个 P0 场景独立复现全部通过
全量 1307 passed / 5 skipped / 0 failed
验收 17/17；Ruff check 全绿；Ruff format 已应用
```

## 验收修复批次 2（2026-08-04）：1×P0 + 1×P1 绕过场景

| # | 绕过 | 修复 |
|---|------|------|
| P0 | tar symlink 组合穿越（`link -> ../outside` + `link/pwn.txt` 写出 staging 根） | tar 分支逐成员拒绝 `issym()/islnk()/isdev()/isfifo()`；`_validate_archive_member` 增加 linkname containment 防御 |
| P1 | `before_user_turn` 重建工具时 capabilities 丢失（`build_use_skill_tool` 固定 `()`） | `SkillRuntime` 增加 `capabilities` 参数（冻结 Run capabilities）；`build_use_skill_tool` 复用 `self.capabilities`；三条构造路径（from_spec/Runner.create/CodeRunner）传入 `_run_capabilities(spec)` |

验证：
```text
2 个绕过场景独立复现全部通过
全量 1311 passed / 5 skipped / 0 failed
Ruff check 全绿；Ruff format 已应用
```
