/** 与 electromind wire protocol 对齐的类型定义。 */

export type WireEvent = {
  method: string;
  params: Record<string, unknown>;
};

/** HistoryReplay 中的消息项 */
export type HistoryMessage =
  | { kind: "text" | "thinking"; role: "user" | "assistant"; text: string }
  | { kind: "tool_call"; tool_call_id: string; name: string; arguments: string }
  | { kind: "tool_result"; tool_call_id: string; content: string };

/** HistoryReplay 事件 params */
export type HistoryReplayParams = {
  thread_id: string;
  title: string;
  project_path: string;
  messages: HistoryMessage[];
  context_limit?: number;
  usage?: Record<string, unknown>;
};

/** ThreadList 中的单个会话 */
export type ThreadSummary = {
  id: string;
  title: string;
  project_path: string;
  backend: string;
};
