/** PlanCard — renders a structured Plan with steps, risks, and actions.
 *
 * States:
 * - draft/ready: shows steps + [Edit Plan] [Approve & Execute]
 * - approved: shows frozen steps with status tracking
 * - executing: shows live step status (pending → running → done)
 * - completed: shows final summary
 */

import React, { useCallback, useState } from "react";

// ── Types (mirrors backend PlanState) ────────────────────────────────

type PlanStatus = "draft" | "ready" | "approved" | "executing" | "completed";
type StepStatus = "pending" | "running" | "done" | "blocked" | "skipped";

interface PlanStep {
  id: string;
  title: string;
  description?: string;
  files?: string[];
  tools?: string[];
  depends_on?: string[];
  status: StepStatus;
}

interface PlanData {
  plan_id: string;
  version: number;
  status: PlanStatus;
  objective: string;
  assumptions?: string[];
  questions?: string[];
  steps: PlanStep[];
  risks?: string[];
  verification?: string[];
  fingerprint?: string;
}

// ── Props ────────────────────────────────────────────────────────────

interface Props {
  plan: PlanData;
  onApprove?: () => void;
  onEdit?: () => void;
  onRevise?: () => void;
}

// ── Status icons ─────────────────────────────────────────────────────

const STEP_ICONS: Record<StepStatus, string> = {
  pending: "○",
  running: "◉",
  done: "✓",
  blocked: "⊘",
  skipped: "−",
};

const STEP_CLASS: Record<StepStatus, string> = {
  pending: "plan-step-pending",
  running: "plan-step-running",
  done: "plan-step-done",
  blocked: "plan-step-blocked",
  skipped: "plan-step-skipped",
};

// ── Component ────────────────────────────────────────────────────────

export const PlanCard: React.FC<Props> = ({ plan, onApprove, onEdit, onRevise }) => {
  const [expandedRisks, setExpandedRisks] = useState(false);

  const isFrozen = plan.status === "approved" || plan.status === "executing" || plan.status === "completed";
  const isApproved = plan.status === "approved";
  const isExecuting = plan.status === "executing";

  const handleApprove = useCallback(() => {
    onApprove?.();
  }, [onApprove]);

  const doneCount = plan.steps.filter((s) => s.status === "done").length;
  const totalCount = plan.steps.length;

  return (
    <div className={`plan-card plan-card-${plan.status}`}>
      {/* Header */}
      <div className="plan-card-header">
        <div className="plan-card-title-row">
          <span className="plan-card-icon">
            {isExecuting ? "⚡" : isApproved ? "📋" : "📝"}
          </span>
          <span className="plan-card-title">实施计划 · v{plan.version}</span>
          {plan.fingerprint && (
            <span className="plan-card-fp" title={plan.fingerprint}>
              {plan.fingerprint.slice(0, 8)}
            </span>
          )}
        </div>
      </div>

      {/* Objective */}
      <p className="plan-card-objective">{plan.objective}</p>

      {/* Steps */}
      <ol className="plan-steps">
        {plan.steps.map((step) => (
          <li
            key={step.id}
            className={`plan-step ${STEP_CLASS[step.status]} ${isFrozen ? "frozen" : ""}`}
          >
            <span className="plan-step-icon">{STEP_ICONS[step.status]}</span>
            <div className="plan-step-body">
              <span className="plan-step-title">{step.title}</span>
              {step.description && (
                <span className="plan-step-desc">{step.description}</span>
              )}
              {step.files && step.files.length > 0 && (
                <span className="plan-step-meta">
                  {step.files.map((f) => (
                    <code key={f} className="plan-step-file">{f}</code>
                  ))}
                </span>
              )}
            </div>
          </li>
        ))}
      </ol>

      {/* Progress bar (when executing or completed) */}
      {(isExecuting || plan.status === "completed") && (
        <div className="plan-progress">
          <div
            className="plan-progress-bar"
            style={{ width: `${totalCount > 0 ? (doneCount / totalCount) * 100 : 0}%` }}
          />
          <span className="plan-progress-text">
            {doneCount}/{totalCount} 完成
          </span>
        </div>
      )}

      {/* Risks */}
      {plan.risks && plan.risks.length > 0 && (
        <details
          className="plan-risks"
          open={expandedRisks}
          onToggle={(e) => setExpandedRisks((e.target as HTMLDetailsElement).open)}
        >
          <summary>风险 ({plan.risks.length})</summary>
          <ul>
            {plan.risks.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </details>
      )}

      {/* Verification */}
      {plan.verification && plan.verification.length > 0 && (
        <details className="plan-verification">
          <summary>验证项 ({plan.verification.length})</summary>
          <ul>
            {plan.verification.map((v, i) => (
              <li key={i}>{v}</li>
            ))}
          </ul>
        </details>
      )}

      {/* Questions (unanswered) */}
      {plan.questions && plan.questions.length > 0 && (
        <div className="plan-questions">
          <span className="plan-questions-label">待确认</span>
          <ul>
            {plan.questions.map((q, i) => (
              <li key={i}>{q}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Actions */}
      {!isFrozen && (
        <div className="plan-card-actions">
          <button className="plan-btn plan-btn-edit" onClick={onEdit}>
            编辑计划
          </button>
          <button className="plan-btn plan-btn-approve" onClick={handleApprove}>
            批准并执行
          </button>
        </div>
      )}
      {isFrozen && plan.status !== "completed" && (
        <div className="plan-card-actions">
          <span className="plan-frozen-badge">已冻结 · v{plan.version}</span>
          {onRevise && (
            <button className="plan-btn plan-btn-revise" onClick={onRevise}>
              请求修订
            </button>
          )}
        </div>
      )}
      {plan.status === "completed" && (
        <div className="plan-card-actions">
          <span className="plan-completed-badge">✓ 计划已完成</span>
        </div>
      )}
    </div>
  );
};
