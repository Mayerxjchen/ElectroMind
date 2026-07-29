import { useState } from "react";
import {
  AssistantRuntimeProvider,
  ThreadPrimitive,
  ComposerPrimitive,
  MessagePrimitive,
  useAuiState,
  type TextMessagePartComponent,
  type ToolCallMessagePartComponent,
  type ReasoningMessagePartComponent,
} from "@assistant-ui/react";
import { useElectromindRuntime, getGlobalClient } from "./runtime";

const BACKEND_URL = "/api";

/* ------------------------------------------------------------------ */
/*  Message Part Renderers                                             */
/* ------------------------------------------------------------------ */

const TextRenderer: TextMessagePartComponent = ({ text, status }) => {
  const isStreaming = status.type === "running";
  return (
    <span className="text-sm whitespace-pre-wrap">
      {text}
      {isStreaming && (
        <span className="inline-block w-1.5 h-4 ml-0.5 bg-blue-400 animate-pulse align-text-bottom" />
      )}
    </span>
  );
};

const ReasoningRenderer: ReasoningMessagePartComponent = ({ text }) => {
  return (
    <details className="my-2" open>
      <summary className="text-xs text-zinc-500 cursor-pointer hover:text-zinc-400 transition-colors select-none">
        思考过程
      </summary>
      <div className="mt-1.5 pl-3 border-l-2 border-zinc-600 text-xs text-zinc-400 whitespace-pre-wrap leading-relaxed">
        {text}
      </div>
    </details>
  );
};

const ToolRenderer: ToolCallMessagePartComponent = ({
  toolCallId,
  toolName,
  args,
  result,
  status,
  respondToApproval,
}) => {
  const needsApproval =
    status.type === "requires-action" && status.reason === "interrupt";
  const [approvalError, setApprovalError] = useState<string | null>(null);

  const argsStr =
    typeof args === "string"
      ? args
      : args && typeof args === "object"
        ? JSON.stringify(args, null, 2)
        : String(args ?? "");

  const handleApprove = async () => {
    setApprovalError(null);
    const client = getGlobalClient();
    if (!client) {
      setApprovalError("客户端未连接，请刷新页面");
      return;
    }
    if (!client.isReady) {
      setApprovalError("连接未就绪，请稍后重试");
      return;
    }
    try {
      await client.sendCommand({ cmd: "permit", tool_call_id: toolCallId });
    } catch (err) {
      setApprovalError(
        err instanceof Error ? err.message : "批准请求失败",
      );
      return;
    }
    respondToApproval({ approved: true });
  };

  const handleDeny = async () => {
    setApprovalError(null);
    const client = getGlobalClient();
    if (!client) {
      setApprovalError("客户端未连接，请刷新页面");
      return;
    }
    if (!client.isReady) {
      setApprovalError("连接未就绪，请稍后重试");
      return;
    }
    try {
      await client.sendCommand({
        cmd: "deny",
        tool_call_id: toolCallId,
        reason: "用户拒绝",
      });
    } catch (err) {
      setApprovalError(
        err instanceof Error ? err.message : "拒绝请求失败",
      );
      return;
    }
    respondToApproval({ approved: false, reason: "用户拒绝" });
  };

  return (
    <div className="my-2 rounded-lg border border-zinc-700 bg-zinc-900 overflow-hidden">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-zinc-700">
        <span className="text-zinc-400 text-xs font-mono font-semibold">
          {toolName}
        </span>
        {status.type === "running" && (
          <span className="text-blue-400 text-xs animate-pulse">执行中…</span>
        )}
        {status.type === "complete" && (
          <span className="text-green-400 text-xs">完成</span>
        )}
        {needsApproval && (
          <span className="text-yellow-400 text-xs ml-auto">需要审批</span>
        )}
      </div>

      <div className="px-3 py-2 space-y-2">
        <pre className="text-xs text-zinc-300 bg-zinc-950 rounded p-2 overflow-x-auto max-h-32">
          {argsStr}
        </pre>

        {result !== undefined && result !== null && (
          <pre className="text-xs text-green-300 bg-zinc-950 rounded p-2 overflow-x-auto max-h-48">
            {typeof result === "string"
              ? result
              : JSON.stringify(result, null, 2)}
          </pre>
        )}

        {needsApproval && (
          <div className="flex gap-2 items-center">
            <button
              className="px-3 py-1 text-xs bg-green-700 hover:bg-green-600 rounded text-white transition-colors"
              onClick={handleApprove}
            >
              批准
            </button>
            <button
              className="px-3 py-1 text-xs bg-red-700 hover:bg-red-600 rounded text-white transition-colors"
              onClick={handleDeny}
            >
              拒绝
            </button>
            {approvalError && (
              <span className="text-xs text-red-400">{approvalError}</span>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

const MESSAGE_PART_COMPONENTS = {
  Text: TextRenderer,
  Reasoning: ReasoningRenderer,
  tools: {
    Fallback: ToolRenderer,
  },
} satisfies MessagePrimitive.Parts.Props["components"];

/* ------------------------------------------------------------------ */
/*  Message Bubbles                                                     */
/* ------------------------------------------------------------------ */

function UserMessageBubble() {
  return (
    <div className="flex justify-end mb-4">
      <div className="max-w-[80%] rounded-2xl px-4 py-2.5 bg-blue-600 text-white">
        <MessagePrimitive.Parts components={MESSAGE_PART_COMPONENTS} />
      </div>
    </div>
  );
}

function AssistantMessageBubble() {
  return (
    <div className="flex justify-start mb-4">
      <div className="max-w-[85%] rounded-2xl px-4 py-2.5 bg-zinc-800 text-zinc-100">
        <MessagePrimitive.Parts components={MESSAGE_PART_COMPONENTS} />
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Composer                                                            */
/* ------------------------------------------------------------------ */

function Composer() {
  const isRunning = useAuiState((s) => s.thread.isRunning);

  return (
    <div className="border-t border-zinc-800 p-3">
      <ComposerPrimitive.Root className="flex items-end gap-2">
        <ComposerPrimitive.Input
          className="flex-1 resize-none rounded-xl border border-zinc-700 bg-zinc-900 px-4 py-2.5 text-sm text-zinc-100 placeholder:text-zinc-500 focus:outline-none focus:ring-2 focus:ring-blue-500 min-h-[40px] max-h-[200px]"
          placeholder="输入消息… (Enter 发送，Shift+Enter 换行)"
          rows={1}
          autoFocus
        />
        {isRunning ? (
          <ComposerPrimitive.Cancel className="shrink-0 rounded-xl bg-red-700 px-4 py-2.5 text-sm font-medium text-white hover:bg-red-600 disabled:opacity-40 transition-colors">
            停止
          </ComposerPrimitive.Cancel>
        ) : (
          <ComposerPrimitive.Send className="shrink-0 rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-40 transition-colors">
            发送
          </ComposerPrimitive.Send>
        )}
      </ComposerPrimitive.Root>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Thread View                                                         */
/* ------------------------------------------------------------------ */

function WelcomeScreen() {
  return (
    <div className="flex flex-col items-center justify-center h-full text-center">
      <p className="text-2xl mb-2">⚡</p>
      <p className="text-zinc-400 text-sm">electromind Web UI 已就绪</p>
      <p className="text-zinc-600 text-xs mt-1">发送消息开始对话</p>
    </div>
  );
}

function ChatThread() {
  const isEmpty = useAuiState((s) => s.thread.isEmpty);
  const isRunning = useAuiState((s) => s.thread.isRunning);

  return (
    <div className="flex flex-col h-screen max-w-3xl mx-auto bg-gray-950">
      <header className="shrink-0 border-b border-zinc-800 px-4 py-3">
        <h1 className="text-sm font-semibold text-zinc-200">electromind</h1>
        <p className="text-xs text-zinc-500">Web UI · 本地后端</p>
      </header>

      <ThreadPrimitive.Viewport className="flex-1 overflow-y-auto px-4 py-4">
        {isEmpty && <WelcomeScreen />}

        <ThreadPrimitive.Messages>
          {({ message }) => {
            if (message.role === "user") return <UserMessageBubble />;
            return <AssistantMessageBubble />;
          }}
        </ThreadPrimitive.Messages>

        {isRunning && (
          <div className="flex items-center gap-2 text-xs text-zinc-500 px-4 py-1">
            <span className="inline-block w-2 h-2 rounded-full bg-blue-400 animate-pulse" />
            运行中…
          </div>
        )}

        <ThreadPrimitive.ViewportFooter>
          <ThreadPrimitive.ScrollToBottom />
        </ThreadPrimitive.ViewportFooter>
      </ThreadPrimitive.Viewport>

      <Composer />
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  App Root                                                            */
/* ------------------------------------------------------------------ */

export default function App() {
  const runtime = useElectromindRuntime(BACKEND_URL);

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ThreadPrimitive.Root>
        <ChatThread />
      </ThreadPrimitive.Root>
    </AssistantRuntimeProvider>
  );
}
