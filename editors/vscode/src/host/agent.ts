// 宿主层 —— electromind 子进程桥（第 4 课）。
//
// 用 child_process.spawn 起一个 Python 进程跑 `electromind --wire`：
//   - 子进程 stdout：每行一个事件（Wire NDJSON），本课先原样转发给回调。
//   - 子进程 stdin：每行一个 JSON 命令，驱动 Agent。
//   - 子进程 stderr：诊断日志。
//
// 这里只做“进程生命周期 + 管道搬运”，不理解事件语义；NDJSON 逐行解析在第 5 课
// 的 wire.ts 里做。

import { type ChildProcessWithoutNullStreams, spawn } from "node:child_process";

import { enrichedPath } from "./cli";

export type AgentBridgeOptions = {
  // 启动子进程的命令与参数。默认全局 `electromind --wire`（uv tool install）。
  command: string;
  args: string[];
  // 子进程工作目录，通常是当前工作区根目录（只影响会话落盘，不用于找包）。
  cwd: string | undefined;
  // stdout 每来一整行（已去掉换行）回调一次。
  onLine: (line: string) => void;
  // stderr 文本回调（诊断日志）。
  onStderr: (text: string) => void;
  // 子进程意外退出回调。主动 stop() 不会触发，避免杀旧进程时误伤新 bridge。
  onExit: (code: number | null) => void;
};

export class AgentBridge {
  private child: ChildProcessWithoutNullStreams | undefined;
  // stdout 可能把一行拆到多个 data 事件里，用缓冲拼到换行再切分。
  private stdoutBuffer = "";
  // 主动 stop 后忽略迟到的 exit，防止切换 backend 时清掉后起的进程引用。
  private stopping = false;

  constructor(private readonly options: AgentBridgeOptions) {}

  /** 起子进程并接线三条流。重复 start 前应先 stop。 */
  start(): void {
    this.stopping = false;
    const child = spawn(this.options.command, this.options.args, {
      cwd: this.options.cwd,
      env: { ...process.env, PATH: enrichedPath() },
      // stdin/stdout/stderr 都用管道，父子进程通过它们通信。
      stdio: ["pipe", "pipe", "pipe"],
    });
    this.child = child;

    child.stdout.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => this.onStdoutChunk(chunk));

    child.stderr.setEncoding("utf8");
    child.stderr.on("data", (chunk: string) => this.options.onStderr(chunk));

    child.on("exit", (code) => {
      if (this.stopping || this.child !== child) {
        return;
      }
      this.child = undefined;
      this.stdoutBuffer = "";
      this.options.onExit(code);
    });
  }

  /** 发一条命令给子进程（自动补换行，因为 Python 侧按行读）。 */
  send(command: object): void {
    if (!this.child) {
      return;
    }
    this.child.stdin.write(JSON.stringify(command) + "\n");
  }

  /** 关闭子进程。先关 stdin 让 Python 侧读到 EOF 优雅退出，再兜底 kill。 */
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

  /** 把 stdout 分片拼成整行，逐行回调。 */
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
