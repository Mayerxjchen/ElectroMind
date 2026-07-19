import { execFileSync, spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { delimiter, join } from "node:path";

export type AgentBridgeOptions = {
  command: string;
  args: string[];
  cwd: string | undefined;
  env?: Record<string, string>;
  onLine: (line: string) => void;
  onStderr: (text: string) => void;
  onExit: (code: number | null) => void;
  onError: (error: Error) => void;
};

export type CliInvocation = {
  command: string;
  args: string[];
};

export class AgentBridge {
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
