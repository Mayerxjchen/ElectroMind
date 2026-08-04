# Skill AGENTS 规则迁移清单

> 来源：`skills/AGENTS.md`（2026-08-04 已删除）的全部有效规则 → 新所有者。
> 每条规则一个 ID、唯一 owner、执行方式、对应测试与状态。机器可核对的
> JSON 版见 `artifacts/skill-migration/agents-rule-inventory.json`（由
> `scripts/accept-self-contained-skills.sh` 重新生成）。

## 规则清单

| ID | 规则 | 新所有者 | 执行方式 | 对应测试 | 状态 |
|----|------|----------|----------|----------|------|
| R-001 | 路由：请求类型 → skill 选择 | catalog `name + description` | machine（runtime resolver） | `test_project_skill_autodiscovery.py`、`test_skill_acceptance.py::test_02` | 完成 |
| R-002 | `.research` 状态协议（task DAG/artifacts/decisions/events/leases） | `research-orchestrator` | machine（checker：validate_state.py/ready_tasks.py/claim_task.py） | `test_skill_w8_self_containment.py::TestExpensiveJobApprovalAndNoDuplicateSubmit` | 完成 |
| R-003 | 结构建模 review gate（slab/surface/defect/adsorbate 先审后算） | `research-orchestrator`（model-structure-review.md） | partial（checker 校验任务 DAG） | `test_skill_w8_self_containment.py` | 完成 |
| R-004 | 昂贵执行单一 owner + lease/heartbeat | `research-orchestrator` + `hpc-submit` | machine（lease 校验 fail_if_invalid + check_pre_submit） | `test_skill_w8_runtime_enforcement.py` | 完成 |
| R-005 | 状态语义 `completed`/`validated`/`accepted` 不折叠 | `research-orchestrator` | machine（validate_state 状态机） | `test_skill_w8_runtime_enforcement.py` | 完成 |
| R-006 | 先查已交付内容再自写（reflex 表） | 各 skill `Where to find what` | prompt | `test_skill_isolation_checker.py`（引用闭包） | 完成 |
| R-007 | 生命周期顺序（intake → … → record） | `comp-chem-workflow` | prompt | `test_skill_w8_self_containment.py::TestPromptRuleMigration` | 完成 |
| R-008 | 不伪造参数或证据（never invent） | `comp-chem-workflow` + engine skills | prompt | 同上 | 完成 |
| R-009 | 计算完成 ≠ 收敛 ≠ 科学有效 | engine skills（validation.md/parser） | partial（parser/checker 退出码） | `test_skill_w8_self_containment.py` | 完成 |
| R-010 | 文献派生模型 exploratory | `comp-chem-workflow` | prompt | 同上 | 完成 |
| R-011 | 缺失原始结构不是停止条件（有界自建） | `research-orchestrator` + `structure-prep` | prompt + checker（任务门） | `test_skill_w8_self_containment.py` | 完成 |
| R-012 | 保留 provenance（文件/命令/作业 ID/日志） | `comp-chem-workflow` + `.research` | prompt + checker（artifact 契约） | `test_skill_w8_runtime_enforcement.py` | 完成 |
| R-013 | 单位约定（eV/Å/fs/K/GPa，异单位显式标注） | `comp-chem-workflow` | prompt | `test_skill_w8_self_containment.py` | 完成 |
| R-014 | 许可数据不打印全文 | 各 tool skill | prompt | 同上 | 完成 |
| R-015 | 参考值不是背书（源设置优先） | 各 tool skill | prompt | 同上 | 完成 |
| R-016 | 操作模式：semi-automatic 默认、autonomous 按请求 | `comp-chem-workflow` | prompt | 同上 | 完成 |
| R-017 | 昂贵 HPC 作业审批断点 | `hpc-submit` + runtime approval + `.research approval` 字段 | machine（task `approval: expensive_hpc_submission` 由 check_pre_submit 强制） | `test_skill_w8_runtime_enforcement.py` | 完成 |
| R-018 | 覆盖/删除/模型选择/结果推广审批断点 | `comp-chem-workflow` + `review-response` | prompt | `test_skill_w8_self_containment.py` | 完成 |
| R-019 | 集群三 tier 事实发现 + `~/.cluster-agents.md` | `hpc-submit` | partial（cluster guide 模板 + 启动前检查） | `test_skill_w8_self_containment.py::TestPromptRuleMigration` | 完成 |
| R-020 | 远程连接规则（rsess 有状态会话） | `rsess` | prompt | 同上 | 完成 |
| R-021 | 现代 Python/uv 约定（PEP 723/uv run） | `hpc-submit` | prompt | 同上 | 完成 |
| R-022 | 信息缺失只问一个聚焦问题 | `comp-chem-workflow` | prompt | `test_skill_w8_self_containment.py` | 完成 |
| R-023 | 路径访问边界（越界读写拒绝） | Sandbox policy | machine | `test_skill_w8_self_containment.py::TestPathAccessBoundary`、`test_electromind_sandbox.py` | 完成 |
| R-024 | 危险命令审批 | Runtime permission/policy | machine | `test_skill_w8_self_containment.py::TestDangerousCommandApproval`、`test_app_tool_permit.py` | 完成 |
| R-025 | 避免重复提交（诊断→单点修改→重提→记录） | `hpc-submit` + lease | machine（lease + check_pre_submit 拦截未 claim 提交） | `test_skill_w8_runtime_enforcement.py` | 完成 |

## 机器强制行（不得只搬进提示词）

```text
R-023 路径访问边界 → sandbox policy
R-024 危险工具审批   → permission/hook
R-017 昂贵作业审批   → runtime hook + hpc-submit + .research approval
R-025 避免重复提交   → lease + check_pre_submit
```

以上四类的运行时行为测试见 `tests/test_skill_w8_runtime_enforcement.py`（直接
驱动 skill 脚本验证行为，而非检查文案）。
