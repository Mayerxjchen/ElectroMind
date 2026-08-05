/** PlanPanel — Inspector 的 Plan tab 内容（G1）。
 *
 * 数据源：ThreadStore 的 ``thread.plan``（plan/state 事件与快照恢复），
 * 与后端 PlanTracker 同一状态源；操作经 wire 命令（plan/approve 等），
 * 后端变更后 plan/state 事件回流刷新，无本地状态复制。
 */

import React from "react";

import { useActiveThread } from "../useStore";
import { PlanCard } from "./PlanCard";

export const PlanPanel: React.FC = () => {
  const thread = useActiveThread();

  const plan = thread?.plan ?? null;
  if (!plan) {
    return (
      <div className="plan-empty">
        <p>暂无计划。</p>
        <p className="plan-empty-hint">
          让 Agent 提议计划（plan_propose），或在 CLI 里 /plan propose &lt;目标&gt;。
        </p>
      </div>
    );
  }

  const threadId = thread?.id ?? "";
  const send = (command: Parameters<typeof window.desktop.sendWireCommand>[0]) => {
    void window.desktop.sendWireCommand(command);
  };

  return (
    <PlanCard
      plan={plan}
      onApprove={() => send({ cmd: "plan/approve", thread_id: threadId })}
      onRevise={() => send({ cmd: "plan/revise", thread_id: threadId })}
      onCancel={() => send({ cmd: "plan/cancel", thread_id: threadId })}
    />
  );
};
