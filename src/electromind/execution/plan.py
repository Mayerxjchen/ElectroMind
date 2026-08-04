"""Plan protocol — structured plan generation, approval, and execution.

A Plan is a structured object (not just Markdown) that the agent
produces in Plan mode.  It contains:
- Objective, assumptions, open questions
- Ordered steps with dependencies
- Risk assessment
- Verification criteria

The lifecycle:
  draft → ready → approved → executing → completed
                                  ↓
                               revising → ready (user requested changes)

Key invariant: once approved, the plan version is FROZEN.  The agent
cannot modify an approved plan — it must create a new revision.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field, fields
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


class PlanStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    APPROVED = "approved"
    EXECUTING = "executing"
    COMPLETED = "completed"
    REVISING = "revising"


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class PlanStep:
    id: str
    title: str
    description: str = ""
    files: tuple[str, ...] = ()  # expected files this step touches
    tools: tuple[str, ...] = ()  # tools this step needs
    depends_on: tuple[str, ...] = ()  # step ids that must complete first
    status: StepStatus = StepStatus.PENDING

    def copy_with(self, **kwargs) -> PlanStep:
        d = {f.name: getattr(self, f.name) for f in fields(self)}
        d.update(kwargs)
        return PlanStep(**d)


@dataclass(frozen=True, slots=True)
class PlanState:
    plan_id: str
    version: int
    status: PlanStatus
    objective: str
    assumptions: tuple[str, ...] = ()
    questions: tuple[str, ...] = ()  # open questions for the user
    steps: tuple[PlanStep, ...] = ()
    risks: tuple[str, ...] = ()
    verification: tuple[str, ...] = ()  # how to verify completion
    created_at: float = field(default_factory=time.time)
    approved_at: float | None = None
    # Content-addressed fingerprint — changes whenever plan content changes
    fingerprint: str = ""

    def compute_fingerprint(self) -> str:
        """Return SHA-256 of all plan content fields."""
        h = hashlib.sha256()
        h.update(self.objective.encode())
        for a in sorted(self.assumptions):
            h.update(("a:" + a).encode())
        for q in sorted(self.questions):
            h.update(("q:" + q).encode())
        for s in self.steps:
            h.update(
                f"s:{s.id}|{s.title}|{s.description}|{','.join(sorted(s.files))}|{','.join(sorted(s.tools))}|{','.join(sorted(s.depends_on))}".encode()
            )
        for r in sorted(self.risks):
            h.update(("r:" + r).encode())
        for v in sorted(self.verification):
            h.update(("v:" + v).encode())
        return h.hexdigest()

    def freeze(self) -> PlanState:
        """Return a copy with computed fingerprint, ready for approval."""
        return PlanState(
            plan_id=self.plan_id,
            version=self.version,
            status=PlanStatus.READY,
            objective=self.objective,
            assumptions=self.assumptions,
            questions=self.questions,
            steps=self.steps,
            risks=self.risks,
            verification=self.verification,
            created_at=self.created_at,
            fingerprint=self.compute_fingerprint(),
        )

    def approve(self) -> PlanState:
        return PlanState(
            plan_id=self.plan_id,
            version=self.version,
            status=PlanStatus.APPROVED,
            objective=self.objective,
            assumptions=self.assumptions,
            questions=self.questions,
            steps=self.steps,
            risks=self.risks,
            verification=self.verification,
            created_at=self.created_at,
            approved_at=time.time(),
            fingerprint=self.fingerprint,
        )

    def with_step_status(self, step_id: str, status: StepStatus) -> PlanState:
        new_steps = tuple(
            s.copy_with(status=status) if s.id == step_id else s for s in self.steps
        )
        return PlanState(
            plan_id=self.plan_id,
            version=self.version,
            status=self.status,
            objective=self.objective,
            assumptions=self.assumptions,
            questions=self.questions,
            steps=new_steps,
            risks=self.risks,
            verification=self.verification,
            created_at=self.created_at,
            approved_at=self.approved_at,
            fingerprint=self.fingerprint,
        )

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "version": self.version,
            "status": str(self.status),
            "objective": self.objective,
            "assumptions": list(self.assumptions),
            "questions": list(self.questions),
            "steps": [
                {
                    "id": s.id,
                    "title": s.title,
                    "description": s.description,
                    "files": list(s.files),
                    "tools": list(s.tools),
                    "depends_on": list(s.depends_on),
                    "status": str(s.status),
                }
                for s in self.steps
            ],
            "risks": list(self.risks),
            "verification": list(self.verification),
            "fingerprint": self.fingerprint,
        }


# ── Plan tracker (per-thread) ─────────────────────────────────────────


class PlanTracker:
    """Tracks the current plan for a thread.

    Only one plan can be active at a time.  Approving a plan freezes it;
    changes require a new revision (version bump).
    """

    def __init__(self) -> None:
        self._current: PlanState | None = None
        self._history: list[PlanState] = []

    @property
    def current(self) -> PlanState | None:
        return self._current

    def propose(self, plan: PlanState) -> PlanState:
        """Set a new draft plan."""
        frozen = plan.freeze()
        self._current = frozen
        return frozen

    def approve(self) -> PlanState | None:
        if self._current is None:
            return None
        if self._current.status != PlanStatus.READY:
            return None
        approved = self._current.approve()
        self._history.append(approved)
        self._current = approved
        return approved

    def revise(self) -> PlanState | None:
        """Start a new revision of the current plan."""
        if self._current is None:
            return None
        revised = PlanState(
            plan_id=self._current.plan_id,
            version=self._current.version + 1,
            status=PlanStatus.REVISING,
            objective=self._current.objective,
            assumptions=self._current.assumptions,
            questions=self._current.questions,
            steps=self._current.steps,
            risks=self._current.risks,
            verification=self._current.verification,
        )
        self._current = revised
        return revised

    def update_step(self, step_id: str, status: StepStatus) -> PlanState | None:
        if self._current is None:
            return None
        self._current = self._current.with_step_status(step_id, status)
        return self._current

    def complete(self) -> PlanState | None:
        if self._current is None:
            return None
        self._current = PlanState(
            plan_id=self._current.plan_id,
            version=self._current.version,
            status=PlanStatus.COMPLETED,
            objective=self._current.objective,
            assumptions=self._current.assumptions,
            questions=self._current.questions,
            steps=self._current.steps,
            risks=self._current.risks,
            verification=self._current.verification,
            created_at=self._current.created_at,
            approved_at=self._current.approved_at,
            fingerprint=self._current.fingerprint,
        )
        self._history.append(self._current)
        return self._current

    @property
    def history(self) -> tuple[PlanState, ...]:
        return tuple(self._history)
