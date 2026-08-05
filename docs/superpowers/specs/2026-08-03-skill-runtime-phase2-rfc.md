# ElectroMind Skill 系统第二阶段重构 RFC

> Status: Approved — implementation baseline for SKILL-0 through SKILL-9.
> Baseline: current repo state, `main` @ `83e006c`, 91 passing tests.

## 一、RFC 目标

将现有流程：

```text
Discovery
→ SkillRegistry[name]
→ use_skill()
→ 安装全部 Skill
→ 注入正文
```

升级为：

```text
Discovery
→ SkillCandidate[]
→ Multi-candidate Catalog
→ Resolver
→ ResolvedSkill
→ Atomic Activation
→ SnapshotRef + Mount
→ Activation Item
→ 注入正文
```

### 必须保留的现有能力

```text
[保留] 项目、配置、用户 Skill 发现
[保留] Catalog fingerprint
[保留] Catalog Generation
[保留] Run 级 Generation 冻结
[保留] SKILL.md 正文与资源摘要
[保留] Sandbox staging、摘要缓存、原子安装
[保留] use_skill 按需加载
[保留] skills list/show/validate
[保留] 现有 91 个测试
```

### 本阶段新增

```text
[新增] 祖先目录发现
[新增] Admin Scope
[新增] .agents/skills 与 .claude/skills
[新增] 同名候选全部保留
[新增] Qualified Skill ID
[新增] 调用场景感知 Resolver
[新增] 结构化 Skill Input
[新增] Skill Activation Item
[新增] 私有 Snapshot Store
[新增] 单 Skill 懒挂载
[新增] Service、CLI、Desktop 统一 Catalog
```

## 二、冻结的核心架构

### 1. 四层模型必须分离

```text
SkillSource
→ 从哪里发现

SkillCandidate
→ 发现了哪个具体版本

SkillCatalog
→ 当前可见的全部候选

SkillResolver
→ 本次调用最终选哪个
```

不能继续使用 `registry: dict[str, Skill]` 作为核心事实源。它会丢失：

- 同名候选
- 来源信息
- 被遮蔽版本
- 兼容方言
- Trust 状态
- 禁用状态
- 解析理由

### 2. 目标数据模型

#### SkillSource

```python
@dataclass(frozen=True, slots=True)
class SkillSource:
    source_id: str
    scope: Literal["builtin", "admin", "user", "project", "add_dir", "plugin"]
    dialect: Literal["electromind", "agents", "claude", "builtin"]
    root: Path
    project_root: Path | None
    distance_from_cwd: int | None
    trust_domain: str
    read_only: bool
```

#### SkillDescriptor

```python
@dataclass(frozen=True, slots=True)
class SkillDescriptor:
    name: str
    description: str
    entry_path: Path
    root_path: Path
    frontmatter: Mapping[str, object]
    content_digest: str
    resource_digest: str
    compatibility: tuple[str, ...]
```

#### SkillCandidate

```python
@dataclass(frozen=True, slots=True)
class SkillCandidate:
    skill_id: str
    descriptor: SkillDescriptor
    source: SkillSource
    enabled_state: Literal["on", "name_only", "manual_only", "off"]
    trust_state: Literal["trusted", "untrusted", "blocked"]
    diagnostics: tuple[SkillDiagnostic, ...]
```

Qualified ID 示例：

```text
builtin:procedure:cp2k
user:agents:cp2k
project:repo-root:agents:cp2k
project:packages-water:claude:cp2k
```

#### ResolvedSkill

```python
@dataclass(frozen=True, slots=True)
class ResolvedSkill:
    candidate: SkillCandidate
    resolution_reason: str
    catalog_generation: int
    catalog_digest: str
```

## 三、Source、Priority、Trust、State 必须独立

不能使用一个整数 `priority` 同时表达全部语义。

### Source Priority

只负责未限定名称的候选排序：

```text
1. 显式 Qualified ID
2. 用户本地 override
3. Admin
4. User
5. 最近的 Project
6. 更高层 Project
7. Built-in
```

同一 Scope 内默认方言顺序：`electromind > agents > claude`。该顺序只影响默认解析，不删除候选。

### Trust

Trust 决定候选是否允许进入模型 Catalog 或被激活。`Source Priority ≠ Trust`。高优先级但未信任的项目 Skill，不能压过低优先级的可信 Skill。

### Enabled State

```text
on          → 模型可发现，用户可调用
name_only   → 模型只看到名字，用户可调用
manual_only → 模型不可发现，用户可调用
off         → 完全不可用
```

### Compatibility Dialect

只描述来源和 Frontmatter 兼容规则：`electromind | agents | claude | builtin`。它不自动授予更高权限或更高 Trust。

## 四、Resolver 按调用场景采用不同规则

### 1. Qualified 显式调用

精确匹配 → 校验 enabled → 校验 trust → 校验 Run 能力 → 激活。不再进行名称优先级选择。

### 2. 非限定显式调用

只有一个可用候选时直接解析；多个可用候选时：

```text
交互式 CLI/Desktop → 打开候选选择器
非交互 -p 模式    → 明确失败，要求使用 Qualified ID
```

不能静默选择一个重名 Skill。

### 3. 模型隐式调用

只考虑 `enabled_state = on 或 name_only`、`trust_state = trusted`、`disable-model-invocation != true`、与当前 Run capability 兼容。

```text
唯一明确最高候选 → 允许激活
同等级歧义       → 不激活，产生 SkillResolutionAmbiguous Item
全部不可信或禁用 → 不激活
```

模型隐式调用不能触发 Workspace Trust 对话。

### 4. `/skills` Picker

展示全部候选（active / shadowed / manual-only / disabled / untrusted / invalid / incompatible）。Picker 是诊断和选择界面，不应用模型 Catalog 的过滤规则。

## 五、Workspace Trust 政策

本 RFC 不建立新的 Skill Trust 数据库。唯一事实源是现有 Workspace / Project Trust，Skill 系统只读取。

未信任项目的行为：

```text
[允许] 在 /skills 中显示名称、路径和诊断
[允许] 查看 SKILL.md
[禁止] 进入模型隐式 Catalog
[禁止] Activation
[禁止] 挂载或执行脚本
```

用户显式选择该 Skill 时调用现有 Workspace Trust 流程；Trust 成功后下一次解析重新评估。Skill 层不弹第二套信任窗口。

默认信任来源：Built-in、Admin、User 默认可信。但可信 Skill 的工具执行仍必须经过 Permission Engine（`Trusted Skill ≠ Tool 自动批准`）。

## 六、Activation 必须是原子事务

正确顺序：

```text
1. 从 Run 冻结的 Catalog Generation 解析候选
2. 校验 Trust、Enabled State 和兼容性
3. 解析并验证调用参数
4. 创建内容寻址 Snapshot
5. 完成目标环境挂载
6. 持久化 SkillActivation Item
7. 将正文注入模型上下文
8. 发布 skill/activated 事件
```

只有第 1～6 步全部成功，模型才能看到 Skill 正文。

Activation 状态：`requested → resolving → snapshotting → mounting → activated | failed | cancelled`。

#### SkillActivationItem

```python
@dataclass(frozen=True, slots=True)
class SkillActivationItem:
    activation_id: str
    request_id: str
    thread_id: str
    run_id: str
    skill_id: str
    catalog_generation: int
    descriptor_digest: str
    snapshot_ref: str
    target_id: str | None
    mounted_root: str | None
    arguments: Mapping[str, str]
    status: str
    created_at: str
```

相同 `request_id + run_id + skill_id` 重复提交必须返回同一 Activation 结果。

## 七、Snapshot 隐私与保留策略

### Run / Project Record

只保存：`skill_id`、`source scope`、`digest`、`catalog generation`、`snapshot_ref`、参数、激活结果。不默认保存私有 Skill 明文。

### Private Snapshot Store

```text
~/.electromind/snapshots/skills/<sha256>/
├── SKILL.md
├── manifest.json
└── resources/
```

权限默认仅当前用户可读。

#### SkillSnapshotRef

```python
@dataclass(frozen=True, slots=True)
class SkillSnapshotRef:
    digest: str
    store: Literal["builtin", "project", "private"]
    locator: str
    export_policy: Literal["reference_only", "exportable", "private"]
```

### 默认策略

| 来源          | 正文默认导出 |
| ----------- | --------: |
| Built-in    | 可通过版本重新解析 |
| 项目提交 Skill  | 可选包含 |
| User Skill  | 不包含 |
| Admin Skill | 不包含 |
| 外部 Add-dir  | 不包含 |

导出完整私有 Snapshot 必须显式请求 `--include-private-skill-snapshots` 并显示内容范围。

### 保留与回收

```text
有 Thread/Run 引用 → 保留
无引用且超过保留期限 → 可由 GC 删除
同 digest → 只保存一份
```

恢复时优先使用 SnapshotRef，不重新读取可能已经改变的源文件。

## 八、Catalog Generation 与 Run 冻结

升级后的 Catalog Snapshot 保存：

```python
@dataclass(frozen=True, slots=True)
class SkillCatalogSnapshot:
    generation: int
    cwd: str
    repo_root: str | None
    candidates: tuple[SkillCandidate, ...]
    source_fingerprints: Mapping[str, str]
    catalog_digest: str
    created_at: str
```

当前 Run 永远使用启动时冻结的 Generation。Watcher 产生新 Generation → 当前 Run 不变 → 下一 Run 使用新 Catalog。Activation 也必须从当前 Run 的冻结 Snapshot 中解析。

## 九、现有代码的演进方式

### `skills/discovery.py`

保留发现逻辑、fingerprint、路径规范化、诊断。替换“首个同名胜出”的聚合边界：

```text
旧: name -> Skill
新: name -> list[SkillCandidate]
    qualified_id -> SkillCandidate
```

### `skills/runtime.py`

保留 Generation、缓存、Run 冻结、fingerprint 变更判断。新增 `CatalogBuilder`、`Resolver`、`ActivationService`。

### `skills/snapshot.py`

保留正文摘要、资源摘要、Catalog Snapshot。新增 `SkillSnapshotRef`、私有 Snapshot Store、导出策略、引用计数/回收索引、Activation Snapshot。

### `sandbox/sandbox.py`

保留 staging、内容摘要缓存、原子安装、目标路径映射。修改为：旧 = Runner 启动时安装全部 Skill；新 = Activation 时安装一个具体 digest 的 Skill。Local/Container 先完成，SSH 单独实施。

### `app/commands/skills.py`

保留 list/show/validate。增量加入 `--all`、`--qualified`、`--source`、`--status`、`--json`、`paths`、`doctor`、`reload`。

### `use_skill`

保留兼容入口，内部改为构造 `ActivationRequest` → `SkillActivationService`。新模型工具使用 `activate_skill`。旧名称保留至少一个正式版本周期。

## 十、发现 Scope

```text
Built-in → 包内 procedures/、tools/
Admin    → /etc/electromind/skills
User     → ~/.electromind/skills、~/.agents/skills、~/.claude/skills
Project  → .electromind/skills、.agents/skills、.claude/skills
Add-dir  → 显式目录下的上述三类路径
```

祖先发现：从 cwd 向上到 repo root，每一级只检查三个固定目录（`.electromind`、`.agents`、`.claude`）。不执行 `find repo -name SKILL.md`、不递归扫描 HOME、不扫描兄弟项目。Nested Monorepo 动态嵌套发现放入 SKILL-7（Context Roots 按需发现）。

### Root 内发现语义（有界递归）

祖先发现定位的是 **Skill root**。每个 root **内部**的发现不是扁平一层，而是**有界递归**。三个概念必须区分：

```text
Skill root     → 作用域配置提供的搜索根（project / user / admin / builtin）
Atomic Skill   → 一个可触发、加载、执行的 Skill：<dir>/SKILL.md（+ references/ scripts/ assets/）
Grouping dir   → 仅用于组织的中层目录（如 procedures/、tools/），本身不是 Skill
```

Collection manifest（显式声明成员 root）在本提案中**预留但不实现**（PR 2）。

root 内发现不变量：

```text
MAX_DEPTH                = 6    根内递归最多 6 层
STOP_AT_SKILL_BOUNDARY   = true 发现 SKILL.md 后将该目录视为完整 Atomic Skill，默认不再向下发现
EXACT_FILENAME           = true 只接受精确大小写 "SKILL.md"（忽略 SKILL.MD / skill.md 并产生诊断）
FOLLOW_NESTED_SYMLINKS   = false 默认不跟随遍历中遇到的嵌套目录符号链接
DISCOVERY_ORDER          = deterministic 稳定排序，不依赖文件系统遍历顺序
PHYSICAL_FILE_DUPLICATE  = deduplicate 同一物理文件（resolved path / dev+inode）经多个 root 发现时去重，
                            保留全部来源，最高优先级来源生效；不是同名冲突
DUPLICATE_SAME_SCOPE     = error 同一作用域下两个不同物理文件声明同名 → 确定性报错。
                            例外：builtin 内置作用域可能合法地持有同一 bundle 的多个安装副本
                            （如 .venv/ 与仓库 skills/），该场景降级为 warning，不阻断运行时
CROSS_SCOPE_CONFLICT     = shadow 高优先级覆盖低优先级（project > user > admin > builtin），
                            低优先级保留 shadowed 诊断
NAME_DIRECTORY_MISMATCH  = warning frontmatter name 与父目录名不一致仍注册，仅诊断（迁移兼容）
IGNORED_DIRS             = .git .hg .svn .venv __pycache__ node_modules 及隐藏目录
```

**不使用 `rglob("SKILL.md")`。** 遇到 Atomic Skill 后停止下钻，防止 Skill 内部 `references/`、`scripts/`、源码树中的示例 `SKILL.md` 被误注册为独立技能（对应 Codex issue #22275 类缺陷）。

入口级目录符号链接（root 的直接子级）在独立安全策略下可提升为 **adopted root**（见 symlink 策略），目标不必位于原 root 内，但必须落在当前作用域允许的 trusted path 集合内。

现有分组布局无需移动即可被发现：

```text
skills/procedures/comp-chem-workflow/SKILL.md
skills/tools/cp2k/SKILL.md
skills/aicc/procedures/comp-chem-workflow/SKILL.md   ← 深度 3，≤ MAX_DEPTH
```

## 十一、Catalog Budget 与 Override

模型 Catalog 只包含：`skill_id 或可解析 name`、`description`、`source label`。默认预算：已知 Context Window → 最多 2%；未知 → 最多 8,000 字符。

超出预算按顺序处理：manual_only 不进入 → 低优先级描述压缩 → shadowed 不进入隐式 Catalog → name_only 只保留名称 → 最后省略并产生可见诊断。

Override 复用现有配置体系：

```toml
[skills.overrides."project:repo-root:agents:cp2k"]
state = "manual_only"

[skills.resolution]
cp2k = "user:agents:cp2k"
```

Override 只控制启用状态和默认解析，不修改源文件。

## 十二、结构化调用协议

```typescript
type SkillInput = {
  type: "skill";
  skillId?: string;
  name?: string;
  arguments?: string | Record<string, string>;
};
```

显式 `/cp2k input.inp` 在 CLI 内解析为 `{type:"skill", name:"cp2k", arguments:"input.inp"}`。Resolver 后 Run 中持久化的是 Qualified ID。

参数替换支持 `$ARGUMENTS`、`$0`、`$1`、`$filename`、`$format`。替换发生在 Snapshot 创建前，最终注入内容也需要有 digest。参数不能修改 model / execution target / permission policy / available tools / RunSnapshot。

## 十三、实施顺序

| 阶段 | 名称 | 核心内容 |
| ---- | ---- | ---- |
| SKILL-0 | 现状固化 | 不改变行为；建立计划—现状矩阵、标记 Public API、保存 91 测试基线、增加 characterization 测试 |
| SKILL-1 | Descriptor/Candidate/Source | 引入三模型 + Qualified ID + 拆分 scope/dialect/trust/state + 兼容 Adapter |
| SKILL-2 | 多 Scope Discovery | 祖先目录、Admin、.agents/.claude、Add-dir、接入 Workspace Trust |
| SKILL-3 | 多候选 Catalog 与 Resolver | 候选保留、Qualified 索引、三种 Resolver Policy、Budget、Override、Generation Snapshot |
| SKILL-4 | 原子 Activation | SkillInput、ActivationService、状态机、参数替换、SnapshotRef、私有 Store |
| SKILL-5 | 单 Skill 懒挂载 | Local / Container / SSH（SSH 单独 PR） |
| SKILL-6 | Service/CLI/Desktop 统一 | skills/list、get、reload、changed、activated 事件、Picker、同一 Generation |
| SKILL-7 | Watcher 与 Nested Discovery | 监听 Roots、debounce、fingerprint 去重、Context Roots |
| SKILL-8 | 内置资源交付 | procedures/tools 内置 Root、wheel package data、Desktop bundle、smoke tests |
| SKILL-9 | 安装/更新/回滚 | 后置；用户显式调用，模型不能自行安装 |

三个核心重构边界：

```text
SkillRegistry[name] → Multi-candidate Catalog
use_skill 直接加载  → Atomic Activation
安装全部 Skill      → Activated Skill Lazy Mount
```

## 十四、迁移策略

1. 第一阶段：`SkillRegistry` 保留为 Facade，`use_skill` 保留兼容工具，旧 CLI 不改变输出默认格式。
2. 第二阶段：内部全部切到 Candidate/Catalog/Resolver，`SkillRegistry` 标记 deprecated，`use_skill` 只调 ActivationService。
3. 第三阶段：删除单值 Registry 假设，Thread 只保存 Catalog Generation 和激活记录。

不得一次同时重写 Discovery、Runtime、Sandbox、CLI、Desktop、Protocol。

## 十五、测试矩阵

Discovery / Collision / Resolver / Activation / Privacy / Dynamic / Distribution（详见 RFC 原文）。

## 十六、最终完成标准

可机器检查的验收清单（每条对应一个可运行验证；验收脚本见
`tests/test_skill_acceptance.py`）：

| # | 标准 | 机器检查方式 |
|---|------|--------------|
| 1 | 现有 Skill 功能和 91 个测试无回归 | 全量 pytest 通过，skill 专项测试文件全绿 |
| 2 | Discovery 返回全部 Candidate，不丢弃同名版本 | `load_candidates` 同源同名 → 2 个候选，Qualified ID 唯一 |
| 3 | Scope、Dialect、Trust、State 分离建模 | `SkillCandidate` 含 `enabled_state`/`trust_state`；`SkillSource` 含 `scope`/`dialect`/`trust_domain` |
| 4 | Catalog Generation 继续按 Run 冻结 | catalog 构建时冻结正文；激活只读冻结内容，文件改动不影响当前 Run |
| 5 | Qualified ID 可以唯一定位 Skill | `by_qualified_id()` 精确索引；add-dir/同源冲突加 locator hash |
| 6 | 显式、隐式和 Picker 使用不同解析策略 | `SkillResolver.resolve_qualified/unqualified/implicit` + `picker_candidates` 行为测试 |
| 7 | 未信任项目 Skill 不进入模型上下文 | `model_visible_candidates` / `resolve_implicit` 过滤 untrusted |
| 8 | Trust 复用现有 Workspace Trust | 注入评估器读取现有 trust store；trust 翻转（文件不变）触发 reload 且 `changed()` 返回 True；不建新库 |
| 9 | Activation 是可回滚的原子事务 | Snapshot+Mount+Item 完成前正文不可见；mount 失败 rollback + failed item |
| 10 | 模型看到正文前，Snapshot、Mount 和 Item 已完成 | activation 事务顺序测试（成功/失败路径） |
| 11 | 私有 Skill 正文不默认进入项目导出 | `save_catalog_snapshot` 只存元数据；`SkillSnapshotRef.export_policy=private` |
| 12 | use_skill 保持兼容但统一进入 ActivationService | `make_activation_use_skill_tool` / `make_activate_skill_tool`；`name` 走 unqualified resolver（含 resolution pin） |
| 13 | 只挂载被激活的 Skill | 发现 100 激活 1 → 沙箱只接收 1 |
| 14 | CLI、Desktop 和 Service 使用同一 Catalog | 进程级 `SkillCatalogService` 单例；wire `skills/list/get/reload/changed` |
| 15 | 内置 Skill 在真实安装产物中可用 | 真实 wheel 构建→解包→`builtin_roots()` 发现→候选加载 |
| 16 | 安装器保持后置且不能由模型自主触发 | 无模型可触发的安装器 API；SKILL-9 明确后置 |

最终实施主线：

```text
现状固化 → 候选模型 → 多 Scope 发现 → 多候选 Catalog → 原子 Activation
→ 单 Skill 懒挂载 → 客户端统一 → 动态发现 → 真实安装交付 → 安装器
```
