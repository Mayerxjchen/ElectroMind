import path from "node:path";

import {
  backendCommand,
  resolveDevConfig,
  shutdownChildren,
  startChild,
  validateDevConfig,
  waitForBackend,
} from "./dev-common.mjs";

const frontendRoot = path.resolve(import.meta.dirname, "..");
const config = resolveDevConfig({ frontendRoot });
await validateDevConfig(config);
const children = new Set();
let shuttingDown = false;

function shutdown(code, signal = "SIGTERM") {
  if (shuttingDown) return;
  shuttingDown = true;
  shutdownChildren(children, signal);
  process.exitCode = code;
}

const invocation = backendCommand(config);
console.log(`[ElectroMind] project: ${config.projectRoot}`);
console.log(`[ElectroMind] backend: ${config.backendUrl}`);
console.log("[ElectroMind] starting backend...");
const backend = startChild(invocation.command, invocation.args, {
  cwd: config.projectRoot,
});
children.add(backend);
backend.once("error", (error) => {
  console.error(`[ElectroMind] ${error.message}`);
  shutdown(1);
});
backend.once("exit", (code) => {
  children.delete(backend);
  if (!shuttingDown) shutdown(code ?? 1);
});

try {
  await waitForBackend({ url: `${config.backendUrl}/health` });
  console.log("[ElectroMind] backend ready");
  console.log("[Web] starting Vite...");
  const npm = process.platform === "win32" ? "npm.cmd" : "npm";
  const frontend = startChild(npm, ["run", "dev:ui"], { cwd: frontendRoot });
  children.add(frontend);
  frontend.once("error", (error) => {
    console.error(`[Web] ${error.message}`);
    shutdown(1);
  });
  frontend.once("exit", (code) => {
    children.delete(frontend);
    if (!shuttingDown) shutdown(code ?? 0);
  });
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  shutdown(1);
}

process.on("SIGINT", () => shutdown(130, "SIGTERM"));
process.on("SIGTERM", () => shutdown(143, "SIGTERM"));
