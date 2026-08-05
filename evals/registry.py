"""任务注册表 — 从 evals/tasks/ 加载 Golden Tasks，校验声明合法性。"""

from __future__ import annotations

import json
from pathlib import Path

from .task import TaskSpec

DEFAULT_TASKS_DIR = Path(__file__).parent / "tasks"


def load_task_file(path: Path) -> TaskSpec:
    """加载单个任务 JSON 文件并校验。"""
    if path.suffix not in (".json",):
        raise ValueError(f"任务文件必须是 JSON: {path.name}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    spec = TaskSpec.from_dict(raw)
    errors = spec.validate()
    if errors:
        raise ValueError(f"任务 {path.name} 声明非法: {errors}")
    return spec


def load_all_tasks(tasks_dir: Path = DEFAULT_TASKS_DIR) -> list[TaskSpec]:
    """加载 tasks_dir 下所有任务（递归），按 id 排序。"""
    tasks: list[TaskSpec] = []
    for path in sorted(tasks_dir.glob("**/*.json")):
        tasks.append(load_task_file(path))
    return tasks


class TaskRegistry:
    """任务集合：按 id / 类别查询。"""

    def __init__(self, tasks: list[TaskSpec] | None = None) -> None:
        self._tasks: dict[str, TaskSpec] = {}
        if tasks is not None:
            self.add_all(tasks)

    def add_all(self, tasks: list[TaskSpec]) -> None:
        for task in tasks:
            if task.id in self._tasks:
                raise ValueError(f"重复任务 id: {task.id}")
            self._tasks[task.id] = task

    def get(self, task_id: str) -> TaskSpec:
        return self._tasks[task_id]

    def by_category(self, category: str) -> list[TaskSpec]:
        return [t for t in self._tasks.values() if t.category == category]

    def all(self) -> list[TaskSpec]:
        return list(self._tasks.values())

    def ids(self) -> list[str]:
        return sorted(self._tasks)

    def __len__(self) -> int:
        return len(self._tasks)


def category_counts(tasks: list[TaskSpec]) -> dict[str, int]:
    """按类别统计任务数（验收要求每类 ≥10）。"""
    counts: dict[str, int] = {}
    for task in tasks:
        counts[task.category] = counts.get(task.category, 0) + 1
    return counts
