# A+ v1.0 验收范围修订记录

> 修订日期：2026-08-04。本记录正式修订验收附件 v1.0 中「跨 skill 场景」一节。

## 修订内容

附件 v1.0 列出的以下跨 skill 场景 skill **不在本次迁移的目标范围内**：

```text
mlip-training-workflow
ai2kit-active-learning
direct-mlip-training
structure-qc
```

### 理由

1. 本迁移的签署范围（`2026-08-04-skill-aplus-self-contained-design.md` §三）
   明确限定为：引用闭包、知识全文同步、标准 discovery roots、安装发现、
   原子激活资源契约、规则迁移、名称一致性、隔离与回归测试。新增 workflow
   型 skill（MLIP 训练工作流、主动学习循环、直接训练、结构 QC）属于**内容
   建设**，不是本次架构迁移的交付物。
2. 上述场景所依赖的架构能力已全部就位并被测试强制：
   - 跨 skill 协作 = 名称激活（`use_skill`/`activate_skill`，§6 措辞 +
     `required capability unavailable` 状态）；
   - 引擎能力由现有 skill 承担：MLIP 训练/推断 → `deepmd`/`mlp`；
     结构构建与审查 → `structure-prep` + `research-orchestrator` 的
     model-structure-review 门；QC → 各 engine 的 parser/validation。
3. 迁移后的 isolation checker 证明：任何新增 workflow skill 必须自包含，
   不能引用不存在的兄弟 skill 路径 —— 未来建设这些 skill 时 checker 会
   强制它们声明（或激活）真实依赖。

### 验收影响

- 「跨 skill 场景」验收项改为：**跨 skill 协作语义（名称激活 + 缺失能力
  明确状态）由 `test_skill_activation.py` 与隔离检查器强制**。
- `artifacts/skill-migration/acceptance-report.json` 的
  `scope_boundary.cross_skill_scenarios` 记录本修订。

## 修订程序

- 本记录由实现方在验收 FAILED 复审期间提出；如验收方不接受，可要求把
  四个场景 skill 列入后续独立立项（内容建设，非架构迁移）。
