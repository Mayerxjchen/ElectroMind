import path from "node:path";

import {
  backendCommand,
  resolveDevConfig,
  shutdownChildren,
  startChild,
  validateDevConfig,
} from "./dev-common.mjs";

const frontendRoot = path.resolve(import.meta.dirname, "..");
const config = resolveDevConfig({ frontendRoot });
await validateDevConfig(config);
const invocation = backendCommand(config);
const backend = startChild(invocation.command, invocation.args, {
  cwd: config.projectRoot,
});
const children = new Set([backend]);

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => shutdownChildren(children, signal));
}
backend.once("error", (error) => {
  console.error(`[ElectroMind] ${error.message}`);
  process.exitCode = 1;
});
backend.once("exit", (code) => {
  process.exitCode = code ?? 1;
});
