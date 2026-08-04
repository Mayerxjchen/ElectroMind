// 宿主层 —— Wire 事件解析（第 5 课）。
//
// electromind 子进程 stdout 每行是一个 JSON-RPC 2.0 notification：
//   {"jsonrpc":"2.0","method":"<事件类名>","params":{...}}
// method 即事件类名（RunBegin / TextDelta / ToolCallBegin ...），见
// src/electromind/core/events.py；序列化见 src/electromind/adapters/acp.py。
//
// 本模块把一行文本解析成 { method, params } 结构，并做最小 JSON-RPC 校验：
// 必须是 2.0、必须是 notification（没有 id）、method 必须是字符串。
// 事件字段的强类型建模留到后续渲染课程按需细化。

export type WireEvent = {
  method: string;
  params: Record<string, unknown>;
};

const JSONRPC_VERSION = "2.0";

/**
 * 解析一行 Wire NDJSON。
 *
 * @returns 解析出的事件；格式不合法时返回 null（调用方决定记日志还是忽略）。
 */
export function parseWireLine(line: string): WireEvent | null {
  let message: unknown;
  try {
    message = JSON.parse(line);
  } catch {
    return null;
  }
  if (typeof message !== "object" || message === null) {
    return null;
  }
  const record = message as Record<string, unknown>;

  // JSON-RPC 版本必须匹配。
  if (record.jsonrpc !== JSONRPC_VERSION) {
    return null;
  }
  // 事件是 notification，不应带 id（带 id 的是 request/response）。
  if ("id" in record) {
    return null;
  }
  // method 必须是非空字符串。
  const method = record.method;
  if (typeof method !== "string" || !method) {
    return null;
  }
  // params 缺省视作空对象；非对象则判非法。
  const rawParams = record.params;
  if (rawParams === undefined) {
    return { method, params: {} };
  }
  if (typeof rawParams !== "object" || rawParams === null) {
    return null;
  }
  return { method, params: rawParams as Record<string, unknown> };
}
