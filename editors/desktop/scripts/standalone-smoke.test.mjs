/** 八: macOS Standalone 冒烟套件。
 *
 * 验证打包后的 .app 在**干净环境**（无 python/uv/全局 CLI、无源码依赖）
 * 下能启动内置 Agent 并恢复 Thread。
 *
 * 环境：
 *   ELECTROMIND_STANDALONE_APP=<path-to-.app>  （缺省自动探测 release/）
 *
 * 覆盖：
 *   1. 内置 Agent 产物一致性（version / SHA-256 / 存在性）
 *   2. 干净环境启动 .app → renderer 加载、无错误页、无"安装 CLI"引导
 *   3. 内置 Agent wire 冒烟：线程创建/工具层/Skills/CP2K Parser + 重启恢复
 *   4. App 退出后无孤立 Agent 进程
 *
 * 失败时输出完整诊断（stderr / targets / HTML / 进程列表）。
 */

import assert from "node:assert/strict";
import { execFileSync, spawn } from "node:child_process";
import {
  existsSync,
  mkdtempSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  rmSync,
  statSync,
} from "node:fs";
import { createHash } from "node:crypto";
import { tmpdir } from "node:os";
import path from "node:path";
import { test } from "node:test";

const REPO = path.resolve(import.meta.dirname, "..", "..", "..");
const DESKTOP = path.resolve(import.meta.dirname, "..");

function findApp() {
  const explicit = process.env.ELECTROMIND_STANDALONE_APP;
  if (explicit) {
    assert.ok(existsSync(explicit), `ELECTROMIND_STANDALONE_APP 不存在: ${explicit}`);
    return explicit;
  }
  const release = path.join(DESKTOP, "release");
  if (!existsSync(release)) {
    throw new Error("release/ 不存在 —— 请先 node scripts/package.js --agent-bin ...");
  }
  // .app 可能直接位于 release/ 或嵌在 <name>-<version>-<arch>/ 子目录
  const apps = readdirSync(release)
    .filter((f) => f.endsWith(".app"))
    .map((f) => path.join(release, f));
  if (apps.length === 0) {
    for (const sub of readdirSync(release)) {
      const subPath = path.join(release, sub);
      if (!statSync(subPath).isDirectory()) {
        continue;
      }
      const inner = readdirSync(subPath).filter((f) => f.endsWith(".app"));
      if (inner.length > 0) {
        apps.push(path.join(subPath, inner[0]));
      }
    }
  }
  // 可能有历史残留的 .app —— 取最新构建的
  apps.sort((a, b) => statSync(b).mtimeMs - statSync(a).mtimeMs);
  assert.ok(apps.length >= 1, `release/ 下应有 .app，实际: ${apps}`);
  return apps[0];
}

const APP = findApp();
const APP_BIN = path.join(APP, "Contents", "MacOS", "electromind Desktop");
const AGENT_BIN = path.join(APP, "Contents", "Resources", "agent", "electromind");
const AGENT_SHA_FILE = path.join(APP, "Contents", "Resources", "agent", "agent.sha256");

/** 干净环境：无 python/uv/全局 CLI，HOME 与 ELECTROMIND_HOME 隔离。
 *  DEEPSEEK_API_KEY 只用于通过 wire reset 的配置门（冒烟不发起真实
 *  模型请求）；PATH 中没有任何 python/uv/electromind。 */
function cleanEnv(home) {
  return {
    ...process.env,
    HOME: home,
    ELECTROMIND_HOME: path.join(home, ".electromind"),
    PATH: "/usr/bin:/bin:/usr/sbin:/sbin",
    DEEPSEEK_API_KEY: "sk-standalone-smoke",
    // 去掉可能泄漏到子进程的 CLI 路径
    VIRTUAL_ENV: "",
    PYTHONPATH: "",
    ELECTROMIND_STANDALONE_APP: "",
  };
}

function sha256File(p) {
  return createHash("sha256").update(readFileSync(p)).digest("hex");
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function fetchJson(url) {
  const res = await fetch(url);
  return res.json();
}

async function cdpEval(port, expression) {
  const targets = await fetchJson(`http://127.0.0.1:${port}/json`);
  const page = targets.find(
    (t) => t.type === "page" && t.url !== "about:blank" && (t.url || "").includes("index.html"),
  );
  assert.ok(page, `应存在 index.html page target；targets=${JSON.stringify(targets.map((t) => ({ type: t.type, url: t.url })))}`);
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    ws.onopen = resolve;
    ws.onerror = reject;
  });
  const result = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("cdp eval timeout")), 8000);
    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.id === 1) {
        clearTimeout(timer);
        resolve(msg.result);
      }
    };
    ws.send(
      JSON.stringify({
        id: 1,
        method: "Runtime.evaluate",
        params: { expression, returnByValue: true },
      }),
    );
  });
  ws.close();
  return result.result?.value;
}

// ── wire 驱动（stdio NDJSON）───────────────────────────────────────────

class WireDriver {
  constructor(agentBin, env) {
    this.proc = spawn(agentBin, ["--wire", "--execution-mode", "local"], {
      env,
      stdio: ["pipe", "pipe", "pipe"],
    });
    this.buf = "";
    this.events = [];
    this.waiter = null;
    this.stderr = "";
    this.proc.stderr.on("data", (d) => {
      this.stderr += d;
    });
    this.exitInfo = null;
    this.proc.on("exit", (code, sig) => {
      this.exitInfo = { code, sig };
    });
    this.proc.on("error", (err) => {
      this.spawnError = String(err);
    });
    this.proc.stdout.on("data", (d) => {
      this.buf += d;
      let idx;
      while ((idx = this.buf.indexOf("\n")) >= 0) {
        const line = this.buf.slice(0, idx);
        this.buf = this.buf.slice(idx + 1);
        if (!line.trim()) continue;
        let ev;
        try {
          ev = JSON.parse(line);
        } catch {
          continue;
        }
        this.events.push(ev);
        if (this.waiter && this.waiter.pred(ev)) {
          const w = this.waiter;
          this.waiter = null;
          w.resolve(ev);
        }
      }
    });
  }

  send(obj) {
    this.proc.stdin.write(`${JSON.stringify(obj)}\n`);
  }

  waitFor(pred, timeoutMs = 30_000) {
    const existing = this.events.find(pred);
    if (existing) return Promise.resolve(existing);
    return new Promise((resolve, reject) => {
      this.waiter = { pred, resolve };
      setTimeout(() => {
        if (this.waiter) {
          this.waiter = null;
          reject(
            new Error(
              `wire 等待超时；stderr=${this.stderr.slice(-500)}` +
                (this.exitInfo ? `；exit=${JSON.stringify(this.exitInfo)}` : "") +
                (this.spawnError ? `；spawnError=${this.spawnError}` : "") +
                `；events=${this.events.map((e) => e.method).slice(-8).join(",")}`,
            ),
          );
        }
      }, timeoutMs);
    });
  }

  async kill() {
    this.proc.kill("SIGTERM");
    await new Promise((r) => setTimeout(r, 300));
    try {
      this.proc.kill("SIGKILL");
    } catch {
      /* already dead */
    }
  }
}

function procTreeSnap() {
  return new Promise((resolve) => {
    spawn("ps", ["-axo", "pid,ppid,command"], { stdio: ["ignore", "pipe", "ignore"] })
      .stdout.on("data", (d) => resolve(String(d)));
  });
}

// ── 1. 内置 Agent 产物一致性 ───────────────────────────────────────────

test("bundled agent: version + SHA consistent", () => {
  assert.ok(existsSync(AGENT_BIN), `内置 Agent 不存在: ${AGENT_BIN}`);
  assert.ok(existsSync(AGENT_SHA_FILE), "agent.sha256 缺失");
  const recorded = readFileSync(AGENT_SHA_FILE, "utf8").trim().split(/\s+/)[0];
  assert.equal(sha256File(AGENT_BIN), recorded, "agent.sha256 与实际文件不符");

  const home = mkdtempSync(path.join(tmpdir(), "standalone-sha-"));
  try {
    const out = spawnSyncBin(AGENT_BIN, ["version"], cleanEnv(home));
    const agentVer = (out.match(/\d+\.\d+\.\d+/) || [""])[0];
    const desktopVer = JSON.parse(
      readFileSync(path.join(DESKTOP, "package.json"), "utf8"),
    ).version;
    assert.equal(agentVer, desktopVer, "Agent 版本与 Desktop 不一致");
  } finally {
    rmSync(home, { recursive: true, force: true });
  }
});

function spawnSyncBin(bin, args, env) {
  return execFileSync(bin, args, { env, encoding: "utf8", timeout: 60_000 });
}

// ── 2. 干净环境启动 .app ───────────────────────────────────────────────

test("clean env app launch: renderer loads, no error page, no install-CLI onboarding", async () => {
  const home = mkdtempSync(path.join(tmpdir(), "standalone-app-"));
  const port = 9400 + Math.floor(Math.random() * 200);
  const proc = spawn(APP_BIN, [`--remote-debugging-port=${port}`, "--no-sandbox"], {
    env: cleanEnv(home),
    stdio: ["ignore", "ignore", "pipe"],
  });
  let stderr = "";
  proc.stderr.on("data", (d) => {
    stderr += d;
  });
  let page = null;
  try {
    const deadline = Date.now() + 60_000;
    while (Date.now() < deadline) {
      try {
        page = await cdpEval(port, "document.readyState");
        if (page === "complete") break;
      } catch {
        /* not up yet */
      }
      await sleep(500);
    }
    assert.equal(page, "complete", `页面应加载完成；stderr=${stderr.slice(-500)}`);

    const hasApp = await cdpEval(port, "!!document.getElementById('app')");
    assert.equal(hasApp, true, "#app 应挂载");
    const errorPage = await cdpEval(
      port,
      "!!(document.querySelector('#app > pre'))",
    );
    assert.equal(errorPage, false, "不应出现启动错误页");
    // 干净环境不应出现"安装 CLI"引导（内置 Agent 必须可用）
    const installPrompt = await cdpEval(
      port,
      "!!document.querySelector('.setup-cmd')",
    );
    assert.equal(installPrompt, false, "不应出现安装 CLI 引导（内置 Agent 应就绪）");
  } finally {
    proc.kill("SIGTERM");
    await sleep(500);
    try {
      proc.kill("SIGKILL");
    } catch {
      /* already dead */
    }
    await sleep(800);
  }

  // 4. 退出后无孤立 Agent 进程
  const snap = await procTreeSnap();
  const orphans = snap
    .split("\n")
    .filter((l) => l.includes("Resources/agent/electromind") || l.includes("agent/electromind"));
  assert.equal(
    orphans.length,
    0,
    `App 退出后仍有 Agent 进程:\n${orphans.join("\n")}`,
  );
  rmSync(home, { recursive: true, force: true });
});

// ── 3. 内置 Agent wire 冒烟：线程/工具/Skills/CP2K + 重启恢复 ─────────

const CP2K_FIXTURE = path.join(REPO, "tests", "fixtures", "cp2k", "success.out");

test("bundled agent wire: thread create → tools/skills/cp2k validate → restart restore", async () => {
  const home = mkdtempSync(path.join(tmpdir(), "standalone-wire-"));
  const env = cleanEnv(home);
  const project = path.join(home, "project");
  mkdirSync(project, { recursive: true });

  // ── 第一段：创建线程 + 检查工具层/Skills/CP2K Parser ──
  const wire = new WireDriver(AGENT_BIN, env);
  try {
    // reset 创建会话并发出 HistoryReplay（携带 thread_id）
    wire.send({ cmd: "reset", project_path: project });
    const boot = await wire.waitFor(
      (e) => e.method === "HistoryReplay" && !!e.params?.thread_id,
      60_000,
    );
    const threadId = boot.params.thread_id;
    assert.ok(threadId, "reset 后应有 thread_id");
    wire.send({ cmd: "list_threads", project_path: project });
    const list1 = await wire.waitFor((e) => e.method === "ThreadList", 30_000);
    assert.ok((list1.params?.threads ?? []).length >= 1, "list_threads 应返回会话");

    // 工具层（无需 LLM Key）
    wire.send({ cmd: "commands" });
    const cmds = await wire.waitFor((e) => e.method === "SlashCommands", 30_000);
    const toolNames = (cmds.params?.commands ?? cmds.params ?? []);
    assert.ok(
      Array.isArray(toolNames) && toolNames.length > 0,
      `commands 应返回工具列表: ${JSON.stringify(cmds.params).slice(0, 200)}`,
    );

    // Skills：内置 cp2k/vasp/lammps/deepmd 可见
    wire.send({ cmd: "skills/list", thread_id: threadId });
    const skills = await wire.waitFor((e) => e.method === "skills/list", 30_000);
    const names = (skills.params?.skills ?? []).map((s) => s.name);
    assert.ok(names.length > 0, "skills/list 应返回候选");
    assert.ok(
      names.some((n) => ["cp2k", "vasp", "lammps", "deepmd"].includes(n)),
      `内置科学 Skill 应可见: ${names.slice(0, 20)}`,
    );

    // CP2K Parser：register → complete → validate → VALIDATED
    const sha = sha256File(CP2K_FIXTURE);
    wire.send({
      cmd: "artifact/register",
      thread_id: threadId,
      manifest: {
        artifact_id: "smoke-cp2k",
        type: "log",
        path: CP2K_FIXTURE,
        sha256: sha,
        software: "cp2k",
      },
    });
    wire.send({
      cmd: "artifact/complete",
      thread_id: threadId,
      artifact_id: "smoke-cp2k",
    });
    wire.send({
      cmd: "artifact/validate",
      thread_id: threadId,
      artifact_id: "smoke-cp2k",
      parser: "cp2k",
    });
    await sleep(1500);
    wire.send({ cmd: "artifact/state", thread_id: threadId });
    const state = await wire.waitFor((e) => e.method === "artifact/state" && Array.isArray(e.params?.artifacts), 30_000);
    const art = (state.params?.artifacts ?? []).find((a) => a.artifact_id === "smoke-cp2k");
    assert.ok(art, "artifact 应存在");
    assert.equal(
      art.validation_status,
      "validated",
      `CP2K 冒烟产物应 VALIDATED: ${JSON.stringify(art.validation_status)}`,
    );

    await wire.kill();
  } catch (err) {
    await wire.kill();
    throw err;
  }

  // ── 第二段：重启后线程可恢复 ──
  const wire2 = new WireDriver(AGENT_BIN, env);
  try {
    wire2.send({ cmd: "list_threads", project_path: project });
    const list = await wire2.waitFor((e) => e.method === "ThreadList", 60_000);
    const threads = list.params?.threads ?? [];
    assert.ok(threads.length >= 1, `重启后应能看到原线程: ${JSON.stringify(threads)}`);

    wire2.send({ cmd: "resume", thread_id: threads[0].id ?? threads[0].thread_id });
    const resumed = await wire2.waitFor(
      (e) => e.params && e.params.thread_id,
      60_000,
    );
    assert.ok(resumed.params.thread_id, "resume 应恢复线程");
    await wire2.kill();
  } catch (err) {
    await wire2.kill();
    throw err;
  } finally {
    rmSync(home, { recursive: true, force: true });
  }
});
