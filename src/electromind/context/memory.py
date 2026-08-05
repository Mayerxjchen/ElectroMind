"""Memory 分层（M3 §8.5）— Thread / Project / Artifact 三层记忆。

- Thread Memory：当前任务、用户约束、当前 Plan、未解决问题、最近决策。
- Project Memory：项目目录约定、执行环境、集群模块、软件版本、科学约定。
- Artifact Memory：按类型/路径/Step/Run/软件/验证状态/创建时间检索。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(slots=True)
class ThreadMemory:
    """当前会话的短期记忆。"""

    current_task: str = ""
    constraints: list[str] = field(default_factory=list)
    plan_id: str = ""
    current_step_id: str = ""
    unresolved_questions: list[str] = field(default_factory=list)
    recent_decisions: list[str] = field(default_factory=list)
    updated_at: float = field(default_factory=time.time)

    def add_constraint(self, text: str) -> None:
        if text and text not in self.constraints:
            self.constraints.append(text)
            self.updated_at = time.time()

    def add_unresolved(self, question: str) -> None:
        if question and question not in self.unresolved_questions:
            self.unresolved_questions.append(question)
            self.updated_at = time.time()

    def add_decision(self, decision: str) -> None:
        self.recent_decisions.append(decision)
        self.recent_decisions = self.recent_decisions[-20:]
        self.updated_at = time.time()

    def to_dict(self) -> dict:
        return {
            "current_task": self.current_task,
            "constraints": list(self.constraints),
            "plan_id": self.plan_id,
            "current_step_id": self.current_step_id,
            "unresolved_questions": list(self.unresolved_questions),
            "recent_decisions": list(self.recent_decisions),
        }


@dataclass(slots=True)
class ProjectMemory:
    """项目级约定（跨会话保留）。"""

    directory_conventions: dict[str, str] = field(default_factory=dict)
    execution_environment: str = ""
    cluster_modules: list[str] = field(default_factory=list)
    software_versions: dict[str, str] = field(default_factory=dict)
    scientific_conventions: list[str] = field(default_factory=list)

    def set_convention(self, key: str, value: str) -> None:
        self.directory_conventions[key] = value

    def to_dict(self) -> dict:
        return {
            "directory_conventions": dict(self.directory_conventions),
            "execution_environment": self.execution_environment,
            "cluster_modules": list(self.cluster_modules),
            "software_versions": dict(self.software_versions),
            "scientific_conventions": list(self.scientific_conventions),
        }


@dataclass(frozen=True, slots=True)
class ArtifactMemoryEntry:
    """Artifact 记忆索引（检索字段见 M3 §8.5）。"""

    artifact_id: str
    type: str
    path: str
    step_id: str = ""
    run_id: str = ""
    software: str = ""
    validation_status: str = "created"
    created_at: float = field(default_factory=time.time)


class ArtifactMemory:
    """Artifact 索引，支持多字段检索。"""

    def __init__(self) -> None:
        self._entries: list[ArtifactMemoryEntry] = []

    def add(self, entry: ArtifactMemoryEntry) -> None:
        self._entries.append(entry)

    def search(
        self,
        *,
        type: str = "",
        path: str = "",
        step_id: str = "",
        run_id: str = "",
        software: str = "",
        validation_status: str = "",
        created_after: float = 0.0,
    ) -> list[ArtifactMemoryEntry]:
        results = []
        for entry in self._entries:
            if type and entry.type != type:
                continue
            if path and path not in entry.path:
                continue
            if step_id and entry.step_id != step_id:
                continue
            if run_id and entry.run_id != run_id:
                continue
            if software and entry.software != software:
                continue
            if validation_status and entry.validation_status != validation_status:
                continue
            if entry.created_at < created_after:
                continue
            results.append(entry)
        return results

    def all(self) -> list[ArtifactMemoryEntry]:
        return list(self._entries)

    def __len__(self) -> int:
        return len(self._entries)
