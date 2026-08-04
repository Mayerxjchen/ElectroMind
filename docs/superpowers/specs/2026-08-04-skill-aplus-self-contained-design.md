# Skill A+ 自包含迁移设计（确认稿）与 TDD 实施计划

> Status: **Approved** — 2026-08-04 用户确认最终架构，正式进入文档与 TDD 实施计划阶段。
> Baseline: `main` @ `83e006c`，1316 tests collected / 1311 passed / 5 skipped。
> 上级文档: [skill-runtime-phase2-rfc](./2026-08-03-skill-runtime-phase2-rfc.md) — 本设计是其横切约束层，不改动 SKILL-0..9 的数据模型、阶段顺序与验收标准，只对「技能自包含」这一维度增加约束。
> 现状矩阵: [skill0-matrix](./2026-08-03-skill0-matrix.md)

## 一、最终架构（A+ / self-contained skills）

> 源码按 `procedures / tools / knowledge` 组织；每个 skill 在 Git 工作树、wheel、安装环境和运行时中都必须是独立、自包含的标准 skill。第一阶段通过显式映射同步完整知识文档，不做语义切片；ElectroMind runtime 不理解 collection。

### 签署的目标状态

```text
skills/
├── procedures/
│   └── <skill>/
│       ├── SKILL.md
│       ├── references/
│       │   └── knowledge/
│       ├── scripts/
│       └── examples/
├── tools/
│   └── <skill>/
│       ├── SKILL.md
│       ├── references/
│       │   └── knowledge/
│       ├── scripts/
│       └── examples/
└── knowledge/
    └── canonical authoring sources
```

### 运行时认识 / 不认识

```text
运行时只认识:  procedures/<skill>、tools/<skill>（普通扁平 skill root）
运行时不知道:  collection、knowledge root、skills root、AGENTS marker、
               结构化根、共享挂载
跨 skill 协作:  只通过名称 + 宿主激活机制完成
```

### 命名语义

```text
skills/knowledge/                     = canonical authoring source（作者事实源）
<skill>/references/knowledge/         = committed runtime copy（提交的运行时副本）
```

任何 skill 的运行都不能依赖 `skills/knowledge/`、`skills/tools/`、`skills/procedures/`、`skills/AGENTS.md`。即使开发者在源码仓库直接运行 ElectroMind，也必须使用 skill 内的副本，不能因为顶层源码恰好存在而绕过隔离边界。

## 二、十项确认约束

### 1. 顶层 `knowledge/` 是作者事实源，不是运行时依赖

`skills/knowledge/` = canonical authoring source；`<skill>/references/knowledge/` = committed runtime copy。顶层四件套（knowledge/、tools/、procedures/、AGENTS.md）对任何 skill 的运行都不是依赖。

### 2. 第一阶段采用字节级确定性复制

不做语义切片。同步器满足 `target bytes == source bytes`。**不向副本顶部自动插入** "Generated from … / Do not edit …" 头注——来源关系由映射文件承担。

```toml
[[references]]
source = "skills/knowledge/electronic-structure.md"
targets = [
  "skills/tools/cp2k/references/knowledge/electronic-structure.md",
  "skills/tools/vasp/references/knowledge/electronic-structure.md",
]
```

`--check` 至少验证：

```text
1. 源文件存在
2. 目标文件存在
3. 源目标 SHA-256 相同
4. 映射中没有重复或冲突 target
5. 没有未声明的生成副本
6. 没有陈旧副本
```

CLI：

```bash
uv run scripts/sync-skill-references.py            # 同步
uv run scripts/sync-skill-references.py --check    # 只读，不能修改工作树
```

### 3. 完整复制还要处理知识文档的传递引用

示例链：`electronic-structure.md → bonding-analysis.md → scientific-visualization.md`。若源文档间是相对链接，目标 skill 中必须保持相同的相对目录关系（同一 `references/knowledge/` 扁平布局）。第一阶段用**显式映射**而非自动猜测语义依赖；隔离检查器必须解析本地 Markdown 链接并确认引用文件存在于当前 skill 内。

```text
全文复制 + 显式依赖映射 + 引用闭包检查 —— 三者缺一不可
```

### 4. Discovery 的唯一模型是普通扁平根

迁移完成后只存在一种 discovery 语义：

```text
<skill-root>/<skill-name>/SKILL.md
```

ElectroMind 内置 skills 提供两个普通根：

```python
def builtin_skill_roots(package_root: Path) -> tuple[Path, ...]:
    return (
        package_root / "skills" / "procedures",
        package_root / "skills" / "tools",
    )
```

同一语义覆盖：project discovery、configured roots、candidate discovery、builtin wheel discovery、`uv tool install` 后的 discovery、sandbox snapshot、doctor/validation。任何入口不得再保留：

```python
if (root / "AGENTS.md").exists():
    ...
```

短期兼容分支可以存在，但必须带删除期限和弃用测试，不能成为长期第二套发现协议。

### 5. `knowledge/` 不进入 catalog，也不需要进入运行时 wheel

运行时安装制品真正需要的是 `skills/procedures/*` 和 `skills/tools/*`（所需知识已提交到各 skill 的 `references/knowledge/`）。顶层 `knowledge/` 继续存在于 Git 仓库和源码分发（sdist）中，供作者维护和同步；普通运行时 wheel 不包含它。这直接验证「顶层 knowledge 不是隐藏运行依赖」。

### 6. 跨 skill 调用只表达能力，不表达宿主 API

可移植 `SKILL.md` 中不得硬编码 `use_skill("cp2k")`。统一使用宿主无关措辞：

```markdown
Activate the `cp2k` skill before generating or validating CP2K inputs.
Activate the `hpc-submit` skill for scheduler-managed standalone execution.
```

ElectroMind 的 system prompt 规定「activate a skill」→ 调用 `use_skill(name)`；其他宿主映射到自己的激活机制。缺少协作 skill 时返回明确状态 `required capability unavailable: cp2k`，而不是搜索兄弟目录 / 手写替代脚本 / 根据模型记忆伪造操作。

### 7. 激活 payload 建议兼容演进

现有原子激活流程保持不变（resolve → freeze → snapshot one skill → lazy mount one skill）。返回值在一段兼容期内同时保留：

```json
{
  "mounted_root": "/mounted/skills/cp2k",
  "skill_root": "/mounted/skills/cp2k",
  "resource_digest": "...",
  "resources": [
    "references/running.md",
    "references/knowledge/electronic-structure.md",
    "scripts/check_inputs.py"
  ]
}
```

- `mounted_root` = 旧字段；`skill_root` = 面向标准 skill 语义的新字段。
- 本次迁移不做破坏性 payload 删除；`mounted_root` 的废弃决定后置。

### 8. `skills/AGENTS.md` 必须按规则所有权迁移

删除 `skills/AGENTS.md` 前，必须证明每一条有效规则已经有明确的新所有者（见第五节迁移矩阵）。尤其不能只把以下规则移动进提示词——它们需要 deterministic policy、hook 或 checker：

```text
禁止越界文件访问、危险工具审批、昂贵作业审批、避免重复提交
```

### 9. 名称一致性设为硬错误

目录名必须严格等于 frontmatter `name`。`skills/tools/packmol/SKILL.md` → `name: packmol`（保留短目录名，具体能力放 `description`）。验证器对不一致直接失败（invalid skill），不产生 warning。

### 10. 隔离检查要覆盖 Markdown 之外的引用

`check-skill-isolation.py` 扫描面：

```text
SKILL.md
references/**/*.md
scripts/**/*.py
scripts/**/*.sh
examples 中的配置文件
```

至少拒绝：`../`、`../../`、`{skills_root}`、`knowledge/`、`tools/`、`procedures/`、`file:///…`、`/Users/…`、`/home/<specific-user>/…`。避免误报普通自然语言（如说明性文本中的 `tools/`）。检查区分上下文：Markdown 链接、代码路径字面量、shell 命令参数、已知模板变量——而不是简单 `grep "tools/"` 一律失败。

## 三、实施范围边界

### 本次迁移包括

```text
引用闭包
知识全文同步
标准 discovery roots
builtin/wheel/uv-tool 安装发现
原子激活资源契约
规则迁移
名称一致性
隔离和回归测试
```

### 本次迁移不包括

```text
语义知识切片
skill export
export-pack
plugin manager
collection manifest
共享资源运行时
新的工作流 DSL
```

以上独立立项，避免把核心迁移做成无限扩张的重构。

## 四、TDD 实施计划

工作项按设计「实施范围边界」的顺序编号（W1..W8）。每项遵循：**先写测试（红）→ 实现 → 全量回归（绿）**。每项完成后仓库必须保持全绿（1316 基线或其显式修订）。

受影响既有测试（各 W 项会显式修订，不允许静默修改）：`test_skill_builtin.py`、`test_project_skill_autodiscovery.py`、`test_skill_acceptance.py`（RFC 验收 #15）、`test_skill_candidates.py`（名称诊断）、`test_skill_activation.py`、`test_skills_snapshot.py`。

### W1 知识同步器（约束 1、2、3 的工具基座）

**新文件**：`scripts/sync-skill-references.py`、`scripts/skill-knowledge-map.toml`、`tests/test_sync_skill_references.py`。
**同步记录**：`skills/knowledge/sync-manifest.json`（提交进 Git），逐 target 记录 `{source, sha256}`，作为「未声明生成副本 / 陈旧副本」的事实源。

测试先行（红）：

1. TOML 映射解析：`[[references]]` 的 source + targets；非法映射（source 缺省、targets 空、target 被两个 source 声明）→ 明确错误。
2. 复制后目标字节 == 源字节（无头注、无改写）。
3. `--check` 六项验证各一测：源缺失 / 目标缺失 / SHA-256 不等 / 冲突 target / 未声明生成副本（`references/knowledge/` 下存在 manifest 未记录文件）/ 陈旧副本（manifest 记录但映射已删除，副本仍在）。
4. `--check` 只读：运行前后临时 git 工作树 `git status` 无任何变化。
5. 幂等：连续两次 sync，第二次不产生任何差异。
6. 相对目录关系保持：源文档间相对链接在目标 `references/knowledge/` 中保持同级扁平布局（约束 3）。
7. **阶段规则**：`references/knowledge/` 是同步专用目录；skill 手写内容放 `references/` 根，不进 `references/knowledge/`（保证检查 5 成立）。

实现要点：`--check` 模式禁止任何写操作；路径全部基于 repo root 解析；同步顺序与输出确定性。

### W2 隔离检查器 + 引用闭包检查（约束 3、10）

**新文件**：`scripts/check-skill-isolation.py`、`tests/test_skill_isolation_checker.py`。接入 `electromind doctor` 与 `scripts/ci-check.sh`。

测试先行（红）：

1. 扫描面：SKILL.md、references/**/*.md、scripts/**/*.py、scripts/**/*.sh、examples 配置文件，逐一有测试样例。
2. Markdown 链接闭包：本地相对链接必须在当前 skill 目录内解析；`references/knowledge/foo.md` 引用 `bar.md` 但缺失 → 失败。
3. 上下文感知：自然语言 prose 含 `tools/` → 通过；代码路径字面量（`Path("skills/tools/cp2k")`）→ 失败；shell 命令参数 → 失败；模板变量 `{skills_root}` → 失败；`file:///…`、`/Users/…`、`/home/<user>/…` → 失败。
4. 拒绝模式清单（约束 10）逐项有测试。
5. 对当前仓库全量运行：**先红**（迁移前 41 处 `knowledge/` 顶层引用 + 可能的 `{skills_root}` 残留），迁移后（W4）转绿。
6. 白名单机制：不可避免的集合级提及（如 README 说明性文字）走显式白名单，白名单本身受审。

### W3 名称一致性硬错误（约束 9）

测试先行（红）：

1. 目录名 ≠ frontmatter `name` → invalid skill：不进 catalog、诊断 severity 为 error、`electromind doctor` 非零退出（替代现 `candidate.py:377` 的 warning 语义）。
2. 全部方言（electromind / agents / claude / builtin）统一硬错误。
3. 盘点前置：迁移前全量 catalog 断言现有 16 个 skill 零不一致；如有不一致先改名再启用硬错误。
4. 既有「warning 不致命」测试改写为「error 致命」。

### W4 知识内容迁移（约束 1、6 + 语义落地）

**前置**：W1、W2、W3 完成。迁移后 11 个 SKILL.md 的 41 处顶层 `knowledge/` 引用全部变为 in-skill 相对链接。

测试先行（红→绿）：

1. 从 41 处 `knowledge/` 引用 + `skills/AGENTS.md` 路由表（如 lobster → bonding-analysis、multiwfn → scientific-visualization）+ knowledge 文档间链接推导初始映射（人工确认后提交）。
2. sync 落盘：每个相关 skill 获得 `references/knowledge/` 提交副本；副本自成引用闭包（W2 检查）。
3. 链接重写：SKILL.md 与 references/*.md 中顶层 `knowledge/foo.md` → `references/knowledge/foo.md`（相对）；不得出现根相对 / `{skills_root}` 前缀。
4. §6 措辞：扫描 skills/ 全树无宿主专用激活硬编码（`use_skill("…")` 只允许出现在 README 等文档说明中）；SKILL.md 统一为「Activate the `X` skill …」。
5. system prompt 映射条款：定位系统提示词定义处，加入「activate a skill → use_skill(name)」条款（ElectroMind 宿主侧）。
6. 缺失协作 skill 行为：activation 对缺失 skill 返回 `required capability unavailable: <name>` 状态（覆盖 resolver 错误路径测试）。
7. 更新 `skills/README.md`、`skills/STRUCTURE.md`：新约定（无 AGENTS.md 必需项；knowledge/ = authoring source；references/knowledge/ = committed runtime copy）。
8. 全量回归：1316 基线保持绿；隔离检查器对仓库全量绿（W2 测试 5 转绿）。

### W5 扁平 discovery 统一（约束 4）

测试先行（红）：

1. `builtin_skill_roots(package_root)` 返回 `(…/procedures, …/tools)`，**不要求 AGENTS.md**。
2. 删除 `builtin.py` 的 `_is_bundle_dir`（AGENTS.md marker）；`builtin_roots()` 探测改为两个扁平根（`<sys.prefix>/skills/procedures`、`<sys.prefix>/skills/tools`、源码树 `skills/procedures`、`skills/tools`）。
3. 删除 `discovery.py` 的 `STRUCTURED_MARKER` 结构根判定与 `scopes.py` 的 structured bundle 分支——project / configured / candidate / builtin wheel / uv tool / sandbox snapshot / doctor 七个入口 + builtin 共八个表面同语义（每入口一测）。
4. grep 测试：`src/electromind` 下不得存在 `(root / "AGENTS.md").exists()` 或等价 marker 分支。
5. `global_instructions`（AGENTS.md 内容注入）：本项保留为**短期兼容读取**（非发现 marker），带删除期限（随 W8）与弃用测试；删除期限标注于测试与代码注释。
6. 受影响测试修订：`test_skill_builtin.py`（bundle 形状断言）、`test_project_skill_autodiscovery.py`、`test_skill_acceptance.py` #15。

### W6 wheel / 安装产物排除 `knowledge/`（约束 5）

测试先行（红）：

1. 真实 wheel 构建 → 解包：wheel data 中**不存在** `skills/knowledge/`（约束 5 验收）。
2. 真实 wheel 构建 → 安装进临时 venv：builtin 发现全部 16 个 skill（回归，RFC 验收 #15 扩展）。
3. sdist：**包含**完整 `skills/`（作者同步源，默认决定，可逆），`source-include` 显式声明。
4. `uv tool install` smoke：安装后 discovery 与 wheel 一致。

实现要点（按实测选路）：首选 `wheel-exclude = ["skills/knowledge/**"]`（需实测 uv_build 的 wheel-exclude 是否作用于 `data` 目录）；若无效，备选构建脚本把 `procedures/` + `tools/` stage 到 `build/bundle/`，`data = "build/bundle"`（`builtin.py` 已探测 venv-root 布局）。TDD 验收测试先行，实现按实测结果落定，并在 pyproject.toml 注释记录选择理由。

### W7 激活 payload 契约（约束 7）

测试先行（红）：

1. payload 同时含 `mounted_root`（旧）与 `skill_root`（新）；兼容期内两者相等。
2. `resource_digest` 保留不变。
3. `resources`：skill root 内资源相对路径列表（来自 snapshot 文件清单）。
4. 旧消费者（读 `mounted_root`）行为零变化；新消费者按 `skill_root` 工作。
5. 兼容期约束：本次迁移不做破坏性字段删除；`mounted_root` 废弃另行立项。

实现要点：`activation.py:_build_payload` 增加字段；`resources` 从挂载 snapshot 的文件清单构造。

### W8 规则迁移与 `skills/AGENTS.md` 删除（约束 8）

测试先行（红→绿）：

1. 审计：逐条枚举 `skills/AGENTS.md` 的有效规则 → 完成第五节迁移矩阵（每行有明确新所有者与强制机制）。
2. **删除前置证明**：矩阵中每一条 machine-enforced 规则都有对应测试证明现有强制机制有效（越界访问被 sandbox policy 拦截、危险命令需审批、昂贵 HPC 作业需审批、重复提交被 lease 拦截——各写一个行为测试；prompt 类规则验证已进入所属 skill 的 SKILL.md）。
3. 删除 `skills/AGENTS.md`；移除 `global_instructions` 加载（W5 的兼容分支随本项删除，弃用测试同时删除）。
4. 路由表 → catalog `name + description`：审计确认现有 description 覆盖路由语义（RFC 路由表），gap 补齐。
5. 更新 `skills/README.md` / `STRUCTURE.md` / AGENTS.md 相关文档引用；全量回归绿；隔离检查器绿。

## 五、迁移矩阵：`skills/AGENTS.md` 规则所有权

| 原规则类别 | 新所有者 | 是否机器强制 |
| ---------- | -------- | ------------ |
| 路径访问边界 | Sandbox policy | 是 |
| 危险命令审批 | Runtime permission/hook | 是 |
| 昂贵 HPC 提交审批 | Runtime hook + `hpc-submit` | 是 |
| 计算完成不等于收敛 | `comp-chem-workflow` 和 engine skill | 部分 |
| 不伪造参数或证据 | 各相关 skill 最小规则 | 否 |
| `.research` 状态协议 | `research-orchestrator` | 由 checker 强制 |
| 集群环境发现 | `hpc-submit` | 部分 |
| 远程连接规则 | `rsess`/SSH policy | 部分 |
| CP2K/VASP/DeepMD 规则 | 对应 tool skill | parser/checker 强制 |
| 路由表 | catalog 的 `name + description` | runtime |

禁止只搬进提示词的确定性规则：越界访问 / 危险工具审批 / 昂贵作业审批 / 避免重复提交。

## 六、最终验收（可机器检查）

| # | 标准 | 机器检查方式 |
|---|------|--------------|
| 1 | 知识副本字节级等于作者源 | `sync-skill-references.py --check` 六项全过 |
| 2 | 顶层 knowledge 不是运行时依赖 | wheel 解包无 `skills/knowledge/`；源码树运行也不读顶层 |
| 3 | 每个 skill 引用自成闭包 | `check-skill-isolation.py` 对 `skills/` 全量零违规 |
| 4 | Discovery 唯一语义为扁平根 | `builtin_skill_roots()` 返回两个根；八个入口共享实现；无 AGENTS.md marker 分支（grep 测试） |
| 5 | 名称一致性硬错误 | 不一致 skill 被拒为 invalid，doctor 非零退出 |
| 6 | 激活 payload 兼容演进 | payload 含 `mounted_root`+`skill_root`+`resource_digest`+`resources`；旧消费者不变 |
| 7 | 跨 skill 只表达能力 | skills/ 全树无宿主激活硬编码；缺失 skill 返回 `required capability unavailable: <name>` |
| 8 | 规则迁移完成 | `skills/AGENTS.md` 已删除；每类 machine-enforced 规则有行为测试证明强制机制有效 |
| 9 | 全量回归 | 1316 基线（或其显式修订）全绿；Ruff 全绿 |
| 10 | 不进入本次迁移的项目 | 无语义切片 / export / plugin / collection manifest / 共享资源运行时代码 |
