import { execFileSync, spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { existsSync } from "node:fs";
import { request as httpRequest, type IncomingMessage } from "node:http";
import { request as httpsRequest } from "node:https";
import { homedir } from "node:os";
import { delimiter, join } from "node:path";
import { URL } from "node:url";

/** 事件/日志/生命周期回调，wire 与 http 两种 transport 共用。 */
export type BridgeCallbacks = {
  onLine: (line: string) => void;
  onStderr: (text: string) => void;
  onExit: (code: number | null) => void;
  onError: (error: Error) => void;
};

/**
 * 前端与后端之间的传输抽象。start 建立连接，send 发命令，stop 断开。
 * 命令与事件的 JSON 形状在 wire / http 两种实现下完全一致（见 python 侧
 * handle_command）；前端只需切换实现，业务代码不变。
 */
export interface AgentTransport {
  start(): void;
  send(command: object): void;
  stop(): void;
}

export type AgentBridgeOptions = {
  command: string;
  args: string[];
  cwd: string | undefined;
  env?: Record<string, string>;
} & BridgeCallbacks;

export type CliInvocation = {
  command: string;
  args: string[];
};

/** stdio transport：spawn `pagent --wire` 子进程，走 stdin/stdout NDJSON。 */
export class AgentBridge implements AgentTransport {
  private child: ChildProcessWithoutNullStreams | undefined;
  private stdoutBuffer = "";
  private stopping = false;

  constructor(private readonly options: AgentBridgeOptions) { }

  start(): void {
    this.stopping = false;
    const child = spawn(this.options.command, this.options.args, {
      cwd: this.options.cwd,
      env: { ...process.env, ...this.options.env, PATH: enrichedPath() },
      stdio: ["pipe", "pipe", "pipe"],
    });
    this.child = child;

    child.stdout.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => this.onStdoutChunk(chunk));

    child.stderr.setEncoding("utf8");
    child.stderr.on("data", (chunk: string) => this.options.onStderr(chunk));

    child.on("error", (error) => {
      if (this.stopping || this.child !== child) {
        return;
      }
      this.child = undefined;
      this.stdoutBuffer = "";
      this.options.onError(error);
    });

    child.on("exit", (code) => {
      if (this.stopping || this.child !== child) {
        return;
      }
      this.child = undefined;
      this.stdoutBuffer = "";
      this.options.onExit(code);
    });
  }

  send(command: object): void {
    if (!this.child) {
      return;
    }
    this.child.stdin.write(JSON.stringify(command) + "\n");
  }

  stop(): void {
    if (!this.child) {
      return;
    }
    this.stopping = true;
    const child = this.child;
    this.child = undefined;
    this.stdoutBuffer = "";
    child.stdin.end();
    child.kill();
  }

  private onStdoutChunk(chunk: string): void {
    this.stdoutBuffer += chunk;
    let index = this.stdoutBuffer.indexOf("\n");
    while (index >= 0) {
      const line = this.stdoutBuffer.slice(0, index).trim();
      this.stdoutBuffer = this.stdoutBuffer.slice(index + 1);
      if (line) {
        this.options.onLine(line);
      }
      index = this.stdoutBuffer.indexOf("\n");
    }
  }
}

export type HttpBridgeOptions = {
  baseUrl: string;
  token?: string;
} & BridgeCallbacks;

/**
 * http transport：连远程 `pagent --http` 后端。命令走 POST /command，
 * 事件走 GET /events 的 SSE 流，与 wire 的 stdin/stdout 一一对应。
 *
 * 用 node 核心 http/https 而非全局 fetch：Electron 主进程的 fetch 对无限
 * 响应体会缓冲到连接关闭才吐数据，导致 SSE 首帧读不到；核心模块的
 * ``res.on("data")`` 保证增量，与 AgentBridge 增量读 stdout 一致。
 *
 * 就绪判定：收到 SSE 首帧（服务端已 subscribe）再冲刷排队命令，
 * 避免命令产生的事件早于订阅而丢失（FanoutSink 只投递给当前订阅者）。
 */
export class HttpBridge implements AgentTransport {
  private eventStream: IncomingMessage | undefined;
  private stopping = false;
  private ready = false;
  private pending: object[] = [];
  private sseBuffer = "";

  constructor(private readonly options: HttpBridgeOptions) { }

  start(): void {
    this.stopping = false;
    this.ready = false;
    this.pending = [];
    this.sseBuffer = "";
    this.openEventStream();
  }

  send(command: object): void {
    if (this.stopping) {
      return;
    }
    if (!this.ready) {
      this.pending.push(command);
      return;
    }
    this.post(command);
  }

  stop(): void {
    this.stopping = true;
    this.eventStream?.destroy();
    this.eventStream = undefined;
    this.pending = [];
    this.sseBuffer = "";
  }

  private authHeaders(): Record<string, string> {
    const token = this.options.token?.trim();
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  private requestFn(url: URL): typeof httpRequest {
    return url.protocol === "https:" ? httpsRequest : httpRequest;
  }

  private post(command: object): void {
    const url = new URL(`${this.options.baseUrl}/command`);
    const body = JSON.stringify(command);
    const req = this.requestFn(url)(
      url,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Content-Length": Buffer.byteLength(body),
          ...this.authHeaders(),
        },
      },
      (res) => {
        if ((res.statusCode ?? 0) >= 400) {
          this.options.onStderr(`[http] POST /command -> ${res.statusCode}\n`);
        }
        res.resume(); // 丢弃响应体，释放 socket
      },
    );
    req.on("error", (error) => {
      if (!this.stopping) {
        this.options.onError(toError(error));
      }
    });
    req.end(body);
  }

  private openEventStream(): void {
    const url = new URL(`${this.options.baseUrl}/events`);
    const req = this.requestFn(url)(
      url,
      {
        method: "GET",
        headers: { Accept: "text/event-stream", ...this.authHeaders() },
      },
      (res) => this.onEventResponse(res),
    );
    req.on("error", (error) => {
      if (!this.stopping) {
        this.options.onError(toError(error));
      }
    });
    req.end();
  }

  private onEventResponse(res: IncomingMessage): void {
    if ((res.statusCode ?? 0) >= 400) {
      res.resume();
      if (!this.stopping) {
        this.options.onError(new Error(`GET /events -> ${res.statusCode}`));
      }
      return;
    }
    this.eventStream = res;
    res.setEncoding("utf8");
    res.on("data", (chunk: string) => {
      this.sseBuffer += chunk;
      this.drainSseBuffer();
    });
    res.on("end", () => this.onStreamClosed());
    res.on("close", () => this.onStreamClosed());
    res.on("error", (error) => {
      if (!this.stopping) {
        this.options.onError(toError(error));
      }
    });
  }

  private onStreamClosed(): void {
    if (this.stopping || this.eventStream === undefined) {
      return;
    }
    this.eventStream = undefined;
    this.options.onExit(null);
  }

  /** 按 SSE 帧（空行分隔）切分，取每帧的 data: 行交给 onLine。 */
  private drainSseBuffer(): void {
    let boundary = this.sseBuffer.indexOf("\n\n");
    while (boundary >= 0) {
      const frame = this.sseBuffer.slice(0, boundary);
      this.sseBuffer = this.sseBuffer.slice(boundary + 2);
      this.emitFrame(frame);
      boundary = this.sseBuffer.indexOf("\n\n");
    }
  }

  private emitFrame(frame: string): void {
    for (const rawLine of frame.split("\n")) {
      if (!rawLine.startsWith("data:")) {
        continue;
      }
      const line = rawLine.slice(5).trim();
      if (line) {
        this.options.onLine(line);
      }
    }
    this.markReady();
  }

  private markReady(): void {
    if (this.ready) {
      return;
    }
    this.ready = true;
    const queued = this.pending;
    this.pending = [];
    for (const command of queued) {
      this.post(command);
    }
  }
}

function toError(value: unknown): Error {
  return value instanceof Error ? value : new Error(String(value));
}

/** 规整后端地址：补默认 http:// 方案、去掉尾部斜杠。空输入回退到本地默认端口。 */
export function normalizeBaseUrl(raw: string): string {
  const trimmed = raw.trim() || "127.0.0.1:8848";
  const withScheme = /^https?:\/\//i.test(trimmed) ? trimmed : `http://${trimmed}`;
  return withScheme.replace(/\/+$/, "");
}

export function enrichedPath(base = process.env.PATH ?? ""): string {
  const home = homedir();
  const extras = [
    join(home, ".local", "bin"),
    "/opt/homebrew/bin",
    "/usr/local/bin",
  ];
  const parts = [...extras, ...base.split(delimiter).filter(Boolean)];
  return [...new Set(parts)].join(delimiter);
}

export function resolveCliCommand(command: string): string {
  const trimmed = command.trim() || "pagent";
  if (trimmed.includes("/") || trimmed.includes("\\")) {
    return trimmed.replace(/^~/, homedir());
  }
  const local = join(homedir(), ".local", "bin", trimmed);
  if (existsSync(local)) {
    return local;
  }
  try {
    const found = execFileSync(
      "/bin/sh",
      ["-c", `command -v ${shellQuote(trimmed)}`],
      {
        encoding: "utf8",
        env: { ...process.env, PATH: enrichedPath() },
      },
    ).trim();
    if (found) {
      return found;
    }
  } catch {
    return trimmed;
  }
  return trimmed;
}

export function resolvePagentWireInvocation(
  projectRoot: string,
  options?: { yolo?: boolean },
): CliInvocation {
  // 桌面端默认 local sandbox：不依赖本机 Docker daemon。
  const wireArgs = ["--wire", "--backend", "local"];
  if (options?.yolo) {
    wireArgs.push("--permission-mode", "auto");
  }
  const pyproject = projectRoot ? join(projectRoot, "pyproject.toml") : "";
  const uv = resolveCliCommand("uv");
  if (pyproject && existsSync(pyproject) && uv) {
    return {
      command: uv,
      args: ["run", "--project", projectRoot, "pagent", ...wireArgs],
    };
  }
  return {
    command: resolveCliCommand("pagent"),
    args: wireArgs,
  };
}

function shellQuote(value: string): string {
  return `'${value.replace(/'/g, `'\\''`)}'`;
}
