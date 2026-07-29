import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";

import {
  backendCommand,
  resolveDevConfig,
  waitForBackend,
} from "./dev-common.mjs";

test("environment project root overrides repository-relative default", () => {
  const config = resolveDevConfig({
    frontendRoot: "/repo/editors/web",
    env: {
      ELECTROMIND_PROJECT_ROOT: "/custom/electromind",
      ELECTROMIND_HTTP_HOST: "127.0.0.1",
      ELECTROMIND_HTTP_PORT: "9911",
    },
  });
  assert.equal(config.projectRoot, path.resolve("/custom/electromind"));
  assert.equal(config.backendUrl, "http://127.0.0.1:9911");
});

test("repository root defaults to two levels above editors/web", () => {
  const config = resolveDevConfig({
    frontendRoot: "/repo/editors/web",
    env: {},
  });
  assert.equal(config.projectRoot, path.resolve("/repo"));
});

test("backend command uses uv project invocation", () => {
  const config = resolveDevConfig({
    frontendRoot: "/repo/editors/web",
    env: {},
  });
  assert.deepEqual(backendCommand(config), {
    command: "uv",
    args: [
      "run",
      "--project",
      path.resolve("/repo"),
      "electromind",
      "--http",
      "--host",
      "127.0.0.1",
      "--port",
      "8848",
    ],
  });
});

test("package exposes coordinated and split development commands", async () => {
  const { readFile } = await import("node:fs/promises");
  const packageJson = JSON.parse(
    await readFile(new URL("../package.json", import.meta.url), "utf8"),
  );
  assert.equal(packageJson.scripts.dev, "node scripts/dev.mjs");
  assert.equal(packageJson.scripts["dev:ui"], "vite");
  assert.equal(packageJson.scripts["dev:api"], "node scripts/dev-api.mjs");
});

test("health polling retries until the backend is ready", async () => {
  let calls = 0;
  await waitForBackend({
    url: "http://127.0.0.1:8848/health",
    timeoutMs: 100,
    intervalMs: 1,
    fetchImpl: async () => {
      calls += 1;
      if (calls < 3) throw new Error("not ready");
      return { ok: true };
    },
  });
  assert.equal(calls, 3);
});
