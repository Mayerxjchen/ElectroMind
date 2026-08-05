"""ElectroMind Agent Eval 框架（M0）。

顶层结构：

- ``task``：Golden Task 声明（TaskSpec / ProviderStep / ExpectedOutcome）
- ``provider``：脚本化 Provider（确定性模型步骤）
- ``harness``：任务执行（Runner 驱动 / driver 驱动 / 参考审批闸门）
- ``verifier``：确定性验证（工具序列 / Artifact / 状态 / 约束）
- ``drivers``：engine 类任务的确定性场景
- ``registry``：任务加载与查询
- ``report``：机器可读 JSON 报告与基线对比
- ``cli``：``python -m evals`` 命令行
"""

from .task import (
    ExpectedArtifact,
    ExpectedOutcome,
    ExpectedState,
    ExpectedToolCall,
    FailureCategory,
    ProviderStep,
    RiskLevel,
    TaskSpec,
)

__all__ = [
    "ExpectedArtifact",
    "ExpectedOutcome",
    "ExpectedState",
    "ExpectedToolCall",
    "FailureCategory",
    "ProviderStep",
    "RiskLevel",
    "TaskSpec",
]
