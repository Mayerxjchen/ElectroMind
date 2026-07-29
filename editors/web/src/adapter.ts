/**
 * SSE 事件适配层：连接 electromind HTTP 后端，收事件、发命令。
 *
 * GET /events  → SSE 流，每帧 data: <JSON-RPC notification>
 * POST /command → 发送命令（body 为 JSON 对象，含 cmd 字段）
 *
 * 命令排队：SSE 订阅建立前（FanoutSink 尚未注册），命令会被缓冲；
 * SSE open 事件触发后立即冲刷，避免 HistoryReplay 等初始化消息丢失。
 */

import type { WireEvent } from "./protocol";

const JSONRPC_VERSION = "2.0";

export type EventHandler = (event: WireEvent) => void;
export type ErrorHandler = (error: Error) => void;

export function parseWireLine(line: string): WireEvent | null {
  let message: unknown;
  try {
    message = JSON.parse(line);
  } catch {
    return null;
  }
  if (typeof message !== "object" || message === null) return null;
  const record = message as Record<string, unknown>;
  if (record.jsonrpc !== JSONRPC_VERSION) return null;
  if ("id" in record) return null;
  const method = record.method;
  if (typeof method !== "string" || !method) return null;
  const rawParams = record.params;
  if (rawParams === undefined) return { method, params: {} };
  if (typeof rawParams !== "object" || rawParams === null) return null;
  return { method, params: rawParams as Record<string, unknown> };
}

export class BackendClient {
  private eventSource: EventSource | null = null;
  private onEvent: EventHandler;
  private onError: ErrorHandler;
  private baseUrl: string;
  private ready = false;
  private pending: Record<string, unknown>[] = [];

  constructor(
    baseUrl: string,
    handlers: { onEvent: EventHandler; onError: ErrorHandler },
  ) {
    this.baseUrl = baseUrl;
    this.onEvent = handlers.onEvent;
    this.onError = handlers.onError;
  }

  /** 连接 SSE 事件流 */
  connect(): void {
    this.disconnect();
    this.ready = false;
    this.pending = [];
    const es = new EventSource(`${this.baseUrl}/events`);
    this.eventSource = es;

    // SSE 连接成功打开 → 标记就绪，冲刷排队命令
    es.onopen = () => {
      this.ready = true;
      const queued = this.pending;
      this.pending = [];
      for (const cmd of queued) {
        this.sendCommand(cmd).catch((err) => {
          console.error("[electromind] queued command failed:", err);
        });
      }
    };

    es.onmessage = (msg) => {
      const event = parseWireLine(msg.data);
      if (event) {
        this.onEvent(event);
      }
    };

    es.onerror = () => {
      if (es.readyState === EventSource.CLOSED) {
        this.ready = false;
        this.onError(new Error("SSE 连接已关闭"));
      }
    };
  }

  /** 断开 SSE 连接 */
  disconnect(): void {
    this.eventSource?.close();
    this.eventSource = null;
    this.ready = false;
  }

  /** 连接是否已就绪（SSE 已打开）。 */
  get isReady(): boolean {
    return this.ready;
  }

  /** 发送一条命令到 POST /command。连接未就绪时自动排队。 */
  async sendCommand(command: Record<string, unknown>): Promise<void> {
    if (!this.ready) {
      this.pending.push(command);
      return;
    }
    const res = await fetch(`${this.baseUrl}/command`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(command),
    });
    if (!res.ok) {
      const detail = await res.text().catch(() => "");
      throw new Error(`command failed (${res.status}): ${detail}`);
    }
  }
}
