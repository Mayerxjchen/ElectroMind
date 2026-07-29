/**
 * ExternalStoreRuntime：将 electromind wire protocol 事件映射为 assistant-ui 的
 * ThreadMessage 模型。Python 后端是唯一 truth source，本模块只做转译。
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  useExternalStoreRuntime,
  type AppendMessage,
  type ThreadMessageLike,
  type MessageStatus,
} from "@assistant-ui/react";
import { BackendClient } from "./adapter";
import type { WireEvent } from "./protocol";

/* ------------------------------------------------------------------ */
/*  全局 BackendClient 引用（供 ToolRenderer 发送审批命令）               */
/* ------------------------------------------------------------------ */

let _globalClient: BackendClient | null = null;
export function getGlobalClient(): BackendClient | null {
  return _globalClient;
}

/* ------------------------------------------------------------------ */
/*  我们的消息格式                                                      */
/* ------------------------------------------------------------------ */

type ToolCallEntry = {
  toolCallId: string;
  name: string;
  arguments: string;
  result?: string;
  /** PermitRequest 已到达，等待用户审批 */
  permitPending?: boolean;
};

type MyMessage = {
  id: string;
  role: "user" | "assistant";
  text: string;
  thinking?: string;
  toolCalls?: ToolCallEntry[];
  status: "running" | "complete" | "requires-action";
};

/* ------------------------------------------------------------------ */
/*  消息转换器                                                          */
/* ------------------------------------------------------------------ */

function convertMessage(msg: MyMessage): ThreadMessageLike {
  if (msg.role === "user") {
    return {
      id: msg.id,
      role: "user",
      content: [{ type: "text" as const, text: msg.text }],
    };
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const parts: any[] = [];

  // 思考文本（reasoning）
  if (msg.thinking) {
    parts.push({ type: "reasoning", text: msg.thinking });
  }

  // 正文
  if (msg.text) {
    parts.push({ type: "text", text: msg.text });
  }

  // 工具调用
  if (msg.toolCalls) {
    for (const tc of msg.toolCalls) {
      const part: Record<string, unknown> = {
        type: "tool-call",
        toolCallId: tc.toolCallId,
        toolName: tc.name,
        args: safeParseArgs(tc.arguments),
        argsText: tc.arguments,
        result: tc.result,
      };

      // PermitRequest 到达：添加审批门
      if (tc.permitPending && !tc.result) {
        part.approval = { id: tc.toolCallId };
        part.status = { type: "requires-action", reason: "interrupt" };
      } else if (tc.result) {
        part.status = { type: "complete" };
      } else {
        part.status = { type: "running" };
      }

      parts.push(part);
    }
  }

  // 消息级状态
  let status: MessageStatus;
  if (msg.status === "running") {
    status = { type: "running" };
  } else if (msg.status === "requires-action") {
    status = { type: "requires-action", reason: "tool-calls" };
  } else {
    status = { type: "complete", reason: "stop" };
  }

  return {
    id: msg.id,
    role: "assistant",
    content: parts.length > 0 ? parts : [{ type: "text", text: "" }],
    status,
  };
}

function safeParseArgs(args: string): Record<string, unknown> {
  try {
    const parsed = JSON.parse(args);
    return typeof parsed === "object" && parsed !== null
      ? (parsed as Record<string, unknown>)
      : { args };
  } catch {
    return { args };
  }
}

/* ------------------------------------------------------------------ */
/*  Runtime Provider                                                    */
/* ------------------------------------------------------------------ */

let nextId = 0;
function genId(): string {
  nextId += 1;
  return `msg-${Date.now()}-${nextId}`;
}

export function useElectromindRuntime(backendUrl: string) {
  const [messages, setMessages] = useState<MyMessage[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const clientRef = useRef<BackendClient | null>(null);

  /* ------- 事件处理 ------- */

  const handleEvent = useCallback((event: WireEvent) => {
    const { method, params } = event;

    switch (method) {
      case "HistoryReplay": {
        const msgs = params.messages as Array<Record<string, unknown>> | undefined;
        if (!msgs || msgs.length === 0) {
          setMessages([]);
          return;
        }
        const replayed: MyMessage[] = [];
        for (const m of msgs) {
          const kind = m.kind as string;
          if (kind === "text" || kind === "thinking") {
            replayed.push({
              id: genId(),
              role: m.role as "user" | "assistant",
              text: kind === "text" ? (m.text as string) : "",
              thinking: kind === "thinking" ? (m.text as string) : undefined,
              status: "complete",
            });
          } else if (kind === "tool_call") {
            replayed.push({
              id: genId(),
              role: "assistant",
              text: "",
              toolCalls: [
                {
                  toolCallId: m.tool_call_id as string,
                  name: m.name as string,
                  arguments: m.arguments as string,
                },
              ],
              status: "complete",
            });
          } else if (kind === "tool_result") {
            for (let i = replayed.length - 1; i >= 0; i--) {
              const prev = replayed[i];
              if (prev.role === "assistant" && prev.toolCalls) {
                const tc = prev.toolCalls.find(
                  (t) => t.toolCallId === m.tool_call_id,
                );
                if (tc) {
                  tc.result = m.content as string;
                  tc.permitPending = false;
                }
                break;
              }
            }
          }
        }
        setMessages(replayed);
        return;
      }

      case "RunBegin": {
        setIsRunning(true);
        return;
      }

      case "TextDelta": {
        const text = params.text as string;
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          if (
            last &&
            last.role === "assistant" &&
            last.status === "running" &&
            !last.toolCalls
          ) {
            return prev.map((m, i) =>
              i === prev.length - 1 ? { ...m, text: m.text + text } : m,
            );
          }
          return [
            ...prev,
            { id: genId(), role: "assistant", text, status: "running" },
          ];
        });
        return;
      }

      case "ReasoningDelta": {
        const text = params.text as string;
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          if (
            last &&
            last.role === "assistant" &&
            last.status === "running"
          ) {
            return prev.map((m, i) =>
              i === prev.length - 1
                ? { ...m, thinking: (m.thinking ?? "") + text }
                : m,
            );
          }
          return [
            ...prev,
            {
              id: genId(),
              role: "assistant",
              text: "",
              thinking: text,
              status: "running",
            },
          ];
        });
        return;
      }

      case "ToolCallBegin": {
        const toolCallId = params.tool_call_id as string;
        const name = params.name as string;
        const args = params.arguments as string;
        setMessages((prev) => [
          ...prev,
          {
            id: genId(),
            role: "assistant",
            text: "",
            toolCalls: [{ toolCallId, name, arguments: args }],
            status: "running",
          },
        ]);
        return;
      }

      case "ToolResult": {
        const toolCallId = params.tool_call_id as string;
        const content = params.content as string;
        setMessages((prev) =>
          prev.map((m) => {
            if (m.role === "assistant" && m.toolCalls) {
              const updated = m.toolCalls.map((tc) =>
                tc.toolCallId === toolCallId
                  ? { ...tc, result: content, permitPending: false }
                  : tc,
              );
              const allDone = updated.every(
                (tc) => tc.result !== undefined && !tc.permitPending,
              );
              return {
                ...m,
                toolCalls: updated,
                status: allDone ? ("complete" as const) : m.status,
              };
            }
            return m;
          }),
        );
        return;
      }

      case "PermitRequest": {
        const toolCallId = params.tool_call_id as string;
        setMessages((prev) =>
          prev.map((m) => {
            // Only consider messages that are still running – stale
            // permitPending flags from previous turns must not match.
            if (
              m.role === "assistant" &&
              m.toolCalls &&
              m.status === "running"
            ) {
              const updated = m.toolCalls.map((tc) =>
                tc.toolCallId === toolCallId
                  ? { ...tc, permitPending: true }
                  : tc,
              );
              const matched = updated.some((tc) => tc.permitPending);
              return matched
                ? { ...m, toolCalls: updated, status: "requires-action" as const }
                : m;
            }
            return m;
          }),
        );
        return;
      }

      case "RunEnd":
      case "TurnEnd": {
        setIsRunning(false);
        setMessages((prev) =>
          prev.map((m) =>
            m.role === "assistant" &&
            (m.status === "running" || m.status === "requires-action")
              ? {
                  ...m,
                  status: "complete" as const,
                  toolCalls: m.toolCalls?.map((tc) => ({
                    ...tc,
                    permitPending: false,
                  })),
                }
              : m,
          ),
        );
        return;
      }

      case "SlashCommands":
      case "CurrentThread":
      case "ConfigSnapshot":
      case "ThreadList":
      case "SlashResult": {
        return;
      }

      case "Error": {
        setIsRunning(false);
        return;
      }
    }
  }, []);

  /* ------- 用户发送消息 ------- */

  const onNew = useCallback(
    async (message: AppendMessage) => {
      const content = message.content[0];
      if (content?.type !== "text") return;

      const text = content.text;
      setMessages((prev) => [
        ...prev,
        { id: genId(), role: "user", text, status: "complete" },
      ]);

      try {
        await clientRef.current?.sendCommand({ cmd: "user", text });
      } catch (err) {
        setMessages((prev) => [
          ...prev,
          {
            id: genId(),
            role: "assistant",
            text: `发送失败：${err instanceof Error ? err.message : String(err)}`,
            status: "complete",
          },
        ]);
      }
    },
    [],
  );

  /* ------- 取消 ------- */

  const onCancel = useCallback(async () => {
    try {
      await clientRef.current?.sendCommand({ cmd: "cancel" });
    } catch (err) {
      console.error("[electromind] cancel failed:", err);
    }
    setIsRunning(false);
  }, []);

  /* ------- 生命周期 ------- */

  useEffect(() => {
    const client = new BackendClient(backendUrl, {
      onEvent: handleEvent,
      onError: (err) => console.error("[electromind]", err.message),
    });
    clientRef.current = client;
    _globalClient = client;
    client.connect();
    // 连接就绪后 BackendClient 自动冲刷排队命令，这里直接发即可
    client.sendCommand({ cmd: "history" }).catch((err) => {
      console.error("[electromind] history fetch failed:", err);
    });

    return () => {
      _globalClient = null;
      client.disconnect();
    };
  }, [backendUrl, handleEvent]);

  /* ------- 构建 runtime ------- */

  const runtime = useExternalStoreRuntime({
    messages,
    isRunning,
    convertMessage,
    onNew,
    onCancel,
  });

  return runtime;
}
