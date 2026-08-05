/** PlanCard — renders a structured Plan with steps, risks, and actions.
 *
 * States:
 * - draft/ready: shows steps + [Approve & Execute]
 * - approved/executing: frozen steps with live status tracking
 * - completed: shows final summary
 *
 * G1: types mirror the backend PlanState (execution/plan.py) — step
 * statuses include the full M2 enum (completed/verified/failed/skipped)
 * and evidence is displayed per step.
 */

import React, { useCallback, useState } from "react";

import type { PlanState } from "../../../shared/protocol";

// ── Props ────────────────────────────────────────────────────────────

interface Props {
  plan: PlanState;
  onApprove?: () => void;
  onRevise?: () => void;
  onCancel?: () => void;
}

// ── Status icons (M2 StepStatus full enum) ───────────────────────────

const STEP_ICONS: Record<string, string> = {
  pending: "○",
  ready: "○",
  running: "◉",
  blocked: "⊘",
  completed: "✓",
  verified: "✓✓",
  failed: "✗",
  skipped: "−",
};

const STEP_CLASS: Record<string, string> = {
  pending: "plan-step-pending",
  ready: "plan-step-pending",
  running: "plan-step-running",
  blocked: "plan-step-blocked",
  completed: "plan-step-done",
  verified: "plan-step-done",
  failed: "plan-step-failed",
  skipped: "plan-step-skipped",
};

// ── Component ────────────────────────────────────────────────────────

export const PlanCard: React.FC<Props> = ({ plan, onApprove, onRevise, onCancel }) => {
  const [expandedRisks, setExpandedRisks] = useState(false);

  const isFrozen =
    plan.status === "approved" ||
    plan.status === "executing" ||
    plan.status === "completed" ||
    plan.status === "revising";
  const isApproved = plan.status === "approved";
  const isExecuting = plan.status === "executing";

  const handleApprove = useCallback(() => {
    onApprove?.();
  }, [onApprove]);

  const doneCount = plan.steps.filter(
    (s) => s.status === "completed" || s.status === "verified" || s.status === "skipped",
  ).length;
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
            <span className="plan-step-icon">
              {STEP_ICONS[step.status] ?? "○"}
            </span>
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
              {step.depends_on && step.depends_on.length > 0 && (
                <span className="plan-step-meta plan-step-deps">
                  依赖: {step.depends_on.join(", ")}
                </span>
              )}
              {/* G1: Evidence（确定性完成依据，sha256 前缀） */}
              {step.evidence && step.evidence.length > 0 && (
                <span className="plan-step-evidence">
                  {step.evidence.map((e, i) => (
                    <code key={i} title={`${e.kind} by ${e.by}`}>
                      {e.kind}
                      {e.sha256 ? `:${e.sha256.slice(0, 8)}` : ""}
                    </code>
                  ))}
                </span>
              )}
              {step.error && (
                <span className="plan-step-error">{step.error}</span>
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
      {!isFrozen && plan.status !== "completed" && plan.status !== "cancelled" && (
        <div className="plan-card-actions">
          <button className="plan-btn plan-btn-approve" onClick={handleApprove}>
            批准并执行
          </button>
          {onCancel && (
            <button className="plan-btn plan-btn-cancel" onClick={onCancel}>
              取消计划
            </button>
          )}
        </div>
      )}
      {isFrozen && plan.status !== "completed" && plan.status !== "cancelled" && (
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
