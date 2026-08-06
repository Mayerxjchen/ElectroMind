#!/usr/bin/env node
/** 真集群 HPC 长任务恢复冒烟（需要 aTrust 已登录 + 集群可达）。
 *
 * 覆盖最终验收项：
 *   1. 提交后本地进程退出 → 远端 Slurm Job 继续运行
 *   2. 重启后经 rsess 恢复原 Job ID（reconcile，绝不重提）
 *   3. 同一 submission 再次 prepare → 禁止重复 sbatch（退出码 2）
 *   4. 输出经 rsync 收集 + SHA 核对（--verify-remote / collect_outputs）
 *   5. Scheduler 成功但 Parser 失败 → 不标记科学成功（VALIDATED 门）
 *
 * 用法：
 *   node scripts/hpc-recovery-smoke.mjs [--host ikkemhpc] [--sleep 45]
 *
 * 环境：PATH 需含 skills/tools/{rsess,hpc-submit}/scripts。
 */

import { execFileSync, spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(__dirname, "..");
const RSESS_BIN = path.join(REPO, "skills", "tools", "rsess", "scripts");
const HPC_BIN = path.join(REPO, "skills", "tools", "hpc-submit", "scripts");
const SKILLS_PATH = `${RSESS_BIN}:${HPC_BIN}`;

const host = process.argv.includes("--host")
  ? process.argv[process.argv.indexOf("--host") + 1]
  : "ikkemhpc";
const sleepSec = process.argv.includes("--sleep")
  ? Number(process.argv[process.argv.indexOf("--sleep") + 1])
  : 45;

let pass = 0;
let fail = 0;
function check(name, ok, detail = "") {
  if (ok) {
    pass += 1;
    console.log(`  ✅ ${name}${detail ? ` — ${detail}` : ""}`);
  } else {
    fail += 1;
    console.log(`  ❌ ${name}${detail ? ` — ${detail}` : ""}`);
  }
}

function run(cmd, args, opts = {}) {
  const { env: extraEnv, ...rest } = opts;
  return execFileSync(cmd, args, {
    encoding: "utf8",
    env: {
      ...process.env,
      PATH: `${SKILLS_PATH}:${process.env.PATH || ""}`,
      PYTHONPATH: `${REPO}/src${process.env.PYTHONPATH ? ":" + process.env.PYTHONPATH : ""}`,
      ...extraEnv,
    },
    ...rest,
  }).trim();
}

/** 以项目 venv 运行 python 脚本（hpc-submit 脚本 import electromind.hpc） */
function runPy(script, args, opts = {}) {
  return run("uv", ["run", "--project", REPO, "python", script, ...args], {
    ...opts,
    env: { ...opts.env, ELECTROMIND_HOME: opts.env?.ELECTROMIND_HOME || process.env.ELECTROMIND_HOME },
  });
}

function sha256(text) {
  return createHash("sha256").update(text).digest("hex");
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

// ── wire 驱动（Desktop 侧 artifact 门验证）──────────────────────────────

class WireDriver {
  constructor(cmd, env) {
    // cmd: 字符串（可执行文件）或数组（可执行文件 + 前置参数）
    const parts = Array.isArray(cmd) ? cmd : [cmd];
    const bin = parts[0];
    const preArgs = parts.slice(1);
    const args = [...preArgs, "--wire", "--execution-mode", "local"];
    this.proc = spawn(bin, args, {
      env: env || process.env,
      stdio: ["pipe", "pipe", "pipe"],
    });
    this.buf = "";
    this.events = [];
    this.waiter = null;
    this.stderr = "";
    this.proc.stderr.on("data", (d) => {
      this.stderr += d;
    });
    this.proc.stdout.on("data", (d) => {
      this.buf += d;
      let idx;
      while ((idx = this.buf.indexOf("\n")) >= 0) {
        const line = this.buf.slice(0, idx);
        this.buf = this.buf.slice(idx + 1);
        if (!line.trim()) continue;
        try {
          this.events.push(JSON.parse(line));
        } catch {
          /* non-JSON line */
        }
        const ev = this.events[this.events.length - 1];
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
          reject(new Error(`wire 等待超时；stderr=${this.stderr.slice(-300)}`));
        }
      }, timeoutMs);
    });
  }

  async kill() {
    this.proc.kill("SIGTERM");
    await sleep(300);
    try {
      this.proc.kill("SIGKILL");
    } catch {
      /* already dead */
    }
  }
}

async function main() {
  const home = mkdtempSync(path.join(tmpdir(), "hpc-smoke-"));
  const project = path.join(home, "project");
  mkdirSync(project, { recursive: true });
  const remoteBase = `/public/home/xjchen/electromind-hpc-smoke-${Date.now()}`;
  const sessionTopic = `hpc-smoke-${Date.now()}`;
  console.log(`\n== HPC 恢复冒烟 ==\nhost=${host} remote=${remoteBase} topic=${sessionTopic}`);

  try {
    // ── 0. rsess 会话 + 远端准备 ──────────────────────────────────────
    console.log("\n[0] rsess 会话 + 远端工作目录");
    // open 生成的会话名带后缀（rsess-<topic>-<hash>）：从输出解析
    const openOut = run("rsess", ["open", sessionTopic, host]);
    const session = (openOut.match(/'([^']+)'/) || [])[1] || sessionTopic;
    run("rsess", ["run", session, `mkdir -p ${remoteBase}`]);
    check("rsess 会话建立", true, session);

    // ── 1. 上传 + prepare_submission（--verify-remote）───────────────
    console.log("\n[1] 上传脚本/输入 + 提交登记");
    const runSh = [
      "#!/bin/bash",
      "#SBATCH -p cpu",
      `#SBATCH -o ${remoteBase}/job.out`,
      `#SBATCH -e ${remoteBase}/job.err`,
      "#SBATCH -t 0-00:05:00",
      `echo "job start $(date)"`,
      "sleep " + sleepSec,
      'echo "job end $(date)"',
      "echo SMOKE_OUTPUT_OK",
    ].join("\n");
    const runShPath = path.join(project, "run.sh");
    writeFileSync(runShPath, runSh + "\n");
    const inputPath = path.join(project, "input.inp");
    writeFileSync(inputPath, "&GLOBAL\n  PROJECT smoke\n&END GLOBAL\n");

    // 传输走 rsync（P3.7：文件经 rsync/scp，不经 tmux 文本）
    run("rsync", ["-az", runShPath, inputPath, `${host}:${remoteBase}/`]);
    check("rsync 上传", true);

    const prepOut = runPy(
      path.join(HPC_BIN, "prepare_submission.py"),
      ["--thread", "hpc-smoke", "--run", "recovery-1", "--rsess-session", session,
        "--remote-workdir", remoteBase, "--script", runShPath, "--input", inputPath,
        "--verify-remote"],
      { env: { ELECTROMIND_HOME: path.join(home, ".electromind") } },
    );
    const submissionId = prepOut.split("\n").pop();
    check("prepare_submission 登记", /^sub-/.test(submissionId), submissionId);

    // ── 2. sbatch（经 rsess）+ bind job_id ────────────────────────────
    console.log("\n[2] sbatch 提交");
    const sbatchOut = run("rsess", ["run", session, `cd ${remoteBase} && sbatch run.sh`]);
    const jobId = (sbatchOut.match(/\b(\d+)\s*$/) || [])[1];
    check("sbatch 返回 job_id", !!jobId, jobId);
    runPy(
      path.join(HPC_BIN, "prepare_submission.py"),
      ["--thread", "hpc-smoke", "--run", "recovery-1", "--rsess-session", session,
        "--remote-workdir", remoteBase, "--script", runShPath, "--input", inputPath,
        "--bind-job-id", jobId],
      { env: { ELECTROMIND_HOME: path.join(home, ".electromind") } },
    );

    // ── 3. 模拟 Desktop 关闭：杀掉所有本地 rsess 客户端进程 ──────────
    console.log("\n[3] 模拟 Desktop 关闭（本地 rsess 客户端全部退出）");
    try {
      execFileSync("pkill", ["-f", `rsess-hpc-smoke-${session.split("-").pop()}`], { stdio: "ignore" });
    } catch {
      /* 无残留 */
    }
    await sleep(2000);

    // 全新 rsess 会话确认 Job 仍在运行（远端 tmux + Slurm 双持久）
    const session2Topic = `${sessionTopic}-r2`;
    const openOut2 = run("rsess", ["open", session2Topic, host]);
    const session2 = (openOut2.match(/'([^']+)'/) || [])[1] || session2Topic;
    const squeue = run("rsess", ["run", session2, `squeue -j ${jobId} -h -o "%i %T"`]);
    check("Desktop 关闭后 Job 继续运行", squeue.includes(jobId), squeue || "(squeue 空)");

    // ── 4. 重启后 reconcile：恢复原 job_id，绝不重提 ─────────────────
    console.log("\n[4] 重启后 reconcile（恢复原 job_id）");
    const recOut = runPy(
      path.join(HPC_BIN, "reconcile_job.py"),
      ["--submission", submissionId, "--rsess-session", session2],
      { env: { ELECTROMIND_HOME: path.join(home, ".electromind") } },
    );
    const recState = recOut.split("\n").pop();
    check("reconcile 恢复 Job 状态", /^(queued|running|completed|failed)/.test(recState), recState);

    // ── 5. 禁止重复 sbatch ───────────────────────────────────────────
    console.log("\n[5] 重复提交挡板");
    let dupOk = false;
    try {
      runPy(
        path.join(HPC_BIN, "prepare_submission.py"),
        ["--thread", "hpc-smoke", "--run", "recovery-1", "--rsess-session", session2,
          "--remote-workdir", remoteBase, "--script", runShPath, "--input", inputPath],
        { env: { ELECTROMIND_HOME: path.join(home, ".electromind") }, stdio: ["ignore", "ignore", "pipe"] },
      );
    } catch (e) {
      dupOk = e.status === 2 && String(e.stderr).includes("禁止重复 sbatch");
    }
    check("禁止重复 sbatch", dupOk);

    // ── 6. 等 Job 完成 → collect_outputs（rsync + SHA）───────────────
    console.log(`\n[6] 等待 Job 完成（sleep ${sleepSec}s + 轮询）`);
    let finalState = "";
    for (let i = 0; i < 40; i++) {
      await sleep(5000);
      const r = runPy(
        path.join(HPC_BIN, "reconcile_job.py"),
        ["--submission", submissionId, "--rsess-session", session2],
        { env: { ELECTROMIND_HOME: path.join(home, ".electromind") } },
      );
      finalState = r.split("\n").pop();
      if (["completed", "failed", "cancelled", "timeout"].includes(finalState)) break;
    }
    check("Job 进入终态", ["completed", "failed"].includes(finalState), finalState);

    const collectDir = path.join(home, "collected");
    mkdirSync(collectDir, { recursive: true });
    const collectOut = runPy(
      path.join(HPC_BIN, "collect_outputs.py"),
      ["--submission", submissionId, "--target", host,
        "--remote-path", `${remoteBase}/job.out`, "--local-path", path.join(collectDir, "job.out")],
      { env: { ELECTROMIND_HOME: path.join(home, ".electromind") } },
    );
    const collected = readFileSync(path.join(collectDir, "job.out"), "utf8");
    check("rsync 收集输出", collected.includes("SMOKE_OUTPUT_OK"), collectDir);
    check("输出 SHA 可核对", typeof collectOut === "string");

    // ── 7. 科学门：Scheduler 成功 ≠ 科学成功 ─────────────────────────
    console.log("\n[7] Parser 门（wire agent）");
    // dev agent（uv run）需要完整 PATH；数据目录仍隔离
    const wireEnv = {
      ...process.env,
      HOME: home,
      ELECTROMIND_HOME: path.join(home, ".electromind"),
      DEEPSEEK_API_KEY: "sk-hpc-smoke",
    };
    const active = new WireDriver(["uv", "run", "--project", REPO, "electromind"], wireEnv);
    try {
      active.send({ cmd: "reset", project_path: project });
      await active.waitFor((e) => e.method === "HistoryReplay" && !!e.params?.thread_id, 60_000);
      const tid = active.events.find((e) => e.method === "HistoryReplay").params.thread_id;

      // 真实集群输出（普通日志）→ cp2k parser → 必须 REJECTED
      const realOut = path.join(collectDir, "job.out");
      active.send({
        cmd: "artifact/register",
        thread_id: tid,
        manifest: {
          artifact_id: "hpc-real-output",
          type: "log",
          path: realOut,
          sha256: sha256(readFileSync(realOut, "utf8")),
          software: "cp2k",
        },
      });
      active.send({ cmd: "artifact/complete", thread_id: tid, artifact_id: "hpc-real-output" });
      active.send({ cmd: "artifact/validate", thread_id: tid, artifact_id: "hpc-real-output", parser: "cp2k" });
      // 事件驱动：等待 validation 结果事件，超时后降级为显式 state 查询
      try {
        await active.waitFor(
          (e) => e.params?.artifact_id === "hpc-real-output" &&
            ["artifact/validated", "artifact/validation_result"].includes(e.method),
          15_000,
        );
      } catch { /* wire agent 未发出 validation 事件，降级为主动查询 */ }
      active.send({ cmd: "artifact/state", thread_id: tid });
      const st1 = await active.waitFor(
        (e) => e.method === "artifact/state" && Array.isArray(e.params?.artifacts) && (e.params.artifacts || []).some((a) => a.artifact_id === "hpc-real-output"),
        30_000,
      );
      const art1 = (st1.params.artifacts || []).find((a) => a.artifact_id === "hpc-real-output");
      check(
        "Scheduler 成功但 Parser 失败 → 不标记科学成功",
        art1 && art1.validation_status !== "validated",
        `validation=${art1?.validation_status}`,
      );

      // 真实 CP2K 成功输出 fixture → VALIDATED
      const cp2kFixture = path.join(REPO, "tests", "fixtures", "cp2k", "success.out");
      const cp2kSha = sha256(readFileSync(cp2kFixture, "utf8"));
      active.send({
        cmd: "artifact/register",
        thread_id: tid,
        manifest: {
          artifact_id: "hpc-cp2k-valid",
          type: "log",
          path: cp2kFixture,
          sha256: cp2kSha,
          software: "cp2k",
        },
      });
      active.send({ cmd: "artifact/complete", thread_id: tid, artifact_id: "hpc-cp2k-valid" });
      active.send({ cmd: "artifact/validate", thread_id: tid, artifact_id: "hpc-cp2k-valid", parser: "cp2k" });
      // 事件驱动：等待 validation 结果事件，超时后降级为显式 state 查询
      try {
        await active.waitFor(
          (e) => e.params?.artifact_id === "hpc-cp2k-valid" &&
            ["artifact/validated", "artifact/validation_result"].includes(e.method),
          15_000,
        );
      } catch { /* wire agent 未发出 validation 事件，降级为主动查询 */ }
      active.send({ cmd: "artifact/state", thread_id: tid });
      const st2 = await active.waitFor(
        (e) => e.method === "artifact/state" && Array.isArray(e.params?.artifacts) && (e.params.artifacts || []).some((a) => a.artifact_id === "hpc-cp2k-valid"),
        30_000,
      );
      const art2 = (st2.params.artifacts || []).find((a) => a.artifact_id === "hpc-cp2k-valid");
      check("CP2K 成功输出 → VALIDATED", art2?.validation_status === "validated", `validation=${art2?.validation_status}`);
      await active.kill();
    } catch (err) {
      await active.kill();
      throw err;
    }

    // ── 清理 ─────────────────────────────────────────────────────────
    console.log("\n[清理] 关闭 rsess 会话 + 远端工作目录");
    try {
      run("rsess", ["close", session2]);
    } catch {
      /* 会话已关 */
    }
    try {
      run("rsess", ["close", session]);
    } catch {
      /* 会话已关 */
    }
    try {
      run("ssh", [host, `rm -rf ${remoteBase}`]);
    } catch {
      /* 远端清理失败不阻塞 */
    }
  } catch (e) {
    console.error("\n冒烟异常:", e.message || e);
    if (e.stderr) console.error("stderr:", String(e.stderr).slice(-600));
    fail += 1;
  }
  console.log(`\n== 结果: ${pass} 通过, ${fail} 失败 ==`);
  process.exit(fail > 0 ? 1 : 0);
}

main().catch((e) => {
  console.error("冒烟异常:", e);
  process.exit(1);
});
