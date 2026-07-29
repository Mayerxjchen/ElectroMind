import { spawn, spawnSync } from "node:child_process";
import { access } from "node:fs/promises";
import path from "node:path";

export function resolveDevConfig({ frontendRoot, env = process.env }) {
  const projectRoot = path.resolve(
    env.ELECTROMIND_PROJECT_ROOT || path.join(frontendRoot, "..", ".."),
  );
  const host = env.ELECTROMIND_HTTP_HOST || "127.0.0.1";
  const port = env.ELECTROMIND_HTTP_PORT || "8848";
  return {
    frontendRoot,
    projectRoot,
    host,
    port,
    backendUrl: `http://${host}:${port}`,
  };
}

export async function validateDevConfig(config) {
  await access(path.join(config.projectRoot, "pyproject.toml"));
  const probe = spawnSync("uv", ["--version"], { encoding: "utf8" });
  if (probe.error || probe.status !== 0) {
    throw new Error("uv was not found; install uv and ensure it is on PATH");
  }
}

export function backendCommand(config) {
  return {
    command: "uv",
    args: [
      "run",
      "--project",
      config.projectRoot,
      "electromind",
      "--http",
      "--host",
      config.host,
      "--port",
      String(config.port),
    ],
  };
}

export async function waitForBackend({
  url,
  fetchImpl = fetch,
  timeoutMs = 30_000,
  intervalMs = 300,
}) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetchImpl(url);
      if (response.ok) return;
    } catch {
      // backend still starting
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  throw new Error(`ElectroMind backend did not become ready at ${url}`);
}

export function startChild(command, args, options = {}) {
  return spawn(command, args, {
    stdio: "inherit",
    env: process.env,
    ...options,
  });
}

export function shutdownChildren(children, signal = "SIGTERM") {
  for (const child of children) {
    if (child.exitCode === null && !child.killed) child.kill(signal);
  }
}
