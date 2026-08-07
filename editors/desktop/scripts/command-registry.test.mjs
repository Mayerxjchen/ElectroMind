/** P1 Command Registry 测试 —— 统一命令定义与执行。
 *
 *  验收（修订版文档 §5）：
 *   - Registry 不重复注册（id / slash / 快捷键冲突即抛错）
 *   - 快捷键、Slash 和菜单执行同一个 Command ID
 *   - 命令有统一 availability 判断
 *   - UI 命令不创建 Run；确定性命令不交给 LLM；未知命令不发送给模型
 *   - Renderer reload 后 Registry 仍只有一份（幂等注册）
 *   - 8 个文档快捷键全部注册且无冲突
 */

import { test } from "node:test";
import assert from "node:assert/strict";

const {
  CommandRegistry,
  getCommandRegistry,
  resetCommandRegistry,
} = await import(
  new URL("../src/renderer/react/command-registry.ts", import.meta.url)
);
const { registerCoreCommands, registerSkillSlashCommands } = await import(
  new URL("../src/renderer/react/commands.ts", import.meta.url)
);
const { __seedDesktopFeaturesForTest } = await import(
  new URL("../src/renderer/features.ts", import.meta.url)
);

// ── 纯 Registry 机制 ────────────────────────────────────────────────

const mockCtx = { store: null };

function makeSpec(overrides = {}) {
  return {
    id: "cmd.test",
    title: "测试命令",
    description: "desc",
    category: "view",
    kind: "ui",
    slash: ["test"],
    shortcut: "meta+t",
    available: () => true,
    execute: () => ({ ok: true }),
    ...overrides,
  };
}

test("registry: register + get + size", () => {
  const r = new CommandRegistry();
  r.register(makeSpec());
  assert.equal(r.size, 1);
  assert.equal(r.get("cmd.test")?.title, "测试命令");
  assert.equal(r.get("nope"), undefined);
});

test("registry: duplicate id throws", () => {
  const r = new CommandRegistry();
  r.register(makeSpec());
  assert.throws(() => r.register(makeSpec()), /重复注册/);
});

test("registry: slash alias conflict throws", () => {
  const r = new CommandRegistry();
  r.register(makeSpec());
  assert.throws(
    () => r.register(makeSpec({ id: "cmd.other", slash: ["test"] })),
    /Slash 别名冲突/,
  );
  // 同一命令多个别名 OK
  const r2 = new CommandRegistry();
  r2.register(makeSpec({ slash: ["test", "t2"] }));
  assert.equal(r2.commandForSlash("T2")?.id, "cmd.test");
});

test("registry: shortcut conflict throws", () => {
  const r = new CommandRegistry();
  r.register(makeSpec());
  assert.throws(
    () => r.register(makeSpec({ id: "cmd.other", shortcut: "meta+t", slash: [] })),
    /快捷键冲突/,
  );
});

test("registry: availability gates execute", async () => {
  const r = new CommandRegistry();
  r.register(makeSpec({ available: () => false }));
  const res = await r.execute("cmd.test", mockCtx);
  assert.equal(res.ok, false);
  assert.match(res.error, /不可用/);
});

test("registry: unknown command never reaches the model", async () => {
  const r = new CommandRegistry();
  const res = await r.execute("no.such", mockCtx);
  assert.equal(res.ok, false);
  assert.match(res.error, /未知命令/);
});

test("registry: execute dispatches args + result", async () => {
  let got = null;
  const r = new CommandRegistry();
  r.register(
    makeSpec({
      execute: (ctx, args) => {
        got = { ctx, args };
        return { ok: true, message: "done" };
      },
    }),
  );
  const res = await r.execute("cmd.test", mockCtx, { level: "safe" });
  assert.equal(res.ok, true);
  assert.equal(got.args.level, "safe");
});

test("registry: execute swallows command exceptions into results", async () => {
  const r = new CommandRegistry();
  r.register(makeSpec({ execute: () => { throw new Error("boom"); } }));
  const res = await r.execute("cmd.test", mockCtx);
  assert.equal(res.ok, false);
  assert.match(res.error, /boom/);
});

test("registry: shortcut binding + slash lookup", () => {
  const r = new CommandRegistry();
  r.register(makeSpec());
  assert.equal(r.shortcutBinding("META+T")?.id, "cmd.test");
  assert.equal(r.shortcutBinding("meta+x"), undefined);
  assert.equal(r.commandForSlash("/test")?.id, undefined, "slash 不带前导 /");
  assert.equal(r.commandForSlash("TEST")?.id, "cmd.test");
});

test("registry: search matches title/description/slash", () => {
  const r = new CommandRegistry();
  r.register(makeSpec({ title: "聚焦输入框", slash: ["focus"] }));
  assert.equal(r.search("聚焦").length, 1);
  assert.equal(r.search("/focus").length, 1);
  assert.equal(r.search("不存在").length, 0);
  assert.equal(r.search("").length, 1);
});

test("registry: singleton + idempotent core registration (reload safety)", () => {
  resetCommandRegistry();
  const reg = getCommandRegistry();
  registerCoreCommands(reg);
  const count = reg.size;
  assert.ok(count > 0, "核心命令应已注册");
  // 重复注册（reload / 双 init）不产生第二份
  registerCoreCommands(reg);
  assert.equal(reg.size, count);
  resetCommandRegistry();
});

// ── 真实命令集（文档验收）───────────────────────────────────────────

test("core commands: all ids/slashes/shortcuts unique", () => {
  resetCommandRegistry();
  const reg = getCommandRegistry();
  registerCoreCommands(reg);
  const all = reg.all();
  const ids = new Set(all.map((c) => c.id));
  assert.equal(ids.size, all.length, "id 不重复");
  const slashes = all.flatMap((c) => c.slash ?? []);
  assert.equal(new Set(slashes).size, slashes.length, "slash 不重复");
  const shortcuts = all.filter((c) => c.shortcut).map((c) => c.shortcut);
  assert.equal(new Set(shortcuts).size, shortcuts.length, "快捷键不冲突");
  resetCommandRegistry();
});

test("core commands: the 8 documented shortcuts are all bound", () => {
  resetCommandRegistry();
  const reg = getCommandRegistry();
  registerCoreCommands(reg);
  const expected = [
    "meta+k", // Command Palette
    "meta+.", // 切换 Ask/Plan/Agent
    "meta+n", // 新建 Thread
    "meta+l", // 聚焦 Composer
    "meta+b", // 展开/收起 Threads
    "meta+i", // 打开/关闭 Inspector
    "escape", // 关闭浮层/停止 Run
    "meta+shift+enter", // 排队下一任务
  ];
  for (const s of expected) {
    assert.ok(reg.shortcutBinding(s), `快捷键 ${s} 应绑定到命令`);
  }
  resetCommandRegistry();
});

test("core commands: kind classification matches the doc", () => {
  resetCommandRegistry();
  const reg = getCommandRegistry();
  registerCoreCommands(reg);
  const kindOf = (id) => reg.get(id)?.kind;
  // UI 命令
  for (const id of ["help", "status.show", "permissions.set", "target.show", "skills.open", "thread.resume", "logs.open", "model.set", "permissions.prompt", "permissions.safe", "permissions.full", "jobs.show", "artifacts.show", "skills.info"]) {
    assert.equal(kindOf(id), "ui", `${id} 应为 ui`);
  }
  // 确定性命令
  for (const id of ["doctor", "reconcile", "collect", "artifact.validate", "skills.reload"]) {
    assert.equal(kindOf(id), "deterministic", `${id} 应为 deterministic`);
  }
  // Agent 命令
  for (const id of ["agent.ask", "agent.plan", "agent.agent"]) {
    assert.equal(kindOf(id), "agent", `${id} 应为 agent`);
  }
  resetCommandRegistry();
});

test("core commands: P2 first-version slash set is registered", () => {
  resetCommandRegistry();
  const reg = getCommandRegistry();
  registerCoreCommands(reg);
  const expectedSlash = [
    "new", "resume", "rename", "compact", "status", "stop",
    "ask", "plan", "agent",
    "model",
    "permissions", "prompt", "safe", "full",
    "target",
    "skills", "skill-info", "reload-skills", "jobs", "reconcile",
    "collect", "validate", "artifacts", "doctor", "logs", "help",
  ];
  for (const s of expectedSlash) {
    assert.ok(reg.commandForSlash(s), `/${s} 应注册`);
  }
  // 破坏性底层操作不做成 Slash Command
  for (const s of ["clear", "delete-thread", "delete-artifact", "sbatch", "rm"]) {
    assert.equal(reg.commandForSlash(s), undefined, `/${s} 不得注册`);
  }
  resetCommandRegistry();
});

test("core commands: UI 命令不创建 Run（不派发 user-input）", async () => {
  resetCommandRegistry();
  const reg = getCommandRegistry();
  registerCoreCommands(reg);
  const events = [];
  const storeStub = {
    getActiveThreadId: () => "t1",
    getThread: () => ({ sessionMode: "agent", autonomy: "prompt", executionTarget: null, status: "idle", pendingPermits: [], artifacts: [] }),
    getState: () => ({ bridgeActive: true, transport: "wire", activityState: "sleeping", inspector: { open: false } }),
    updateThread: () => {},
    setInspector: () => {},
  };
  const fakeWindow = {
    dispatchEvent: (e) => events.push(e.type),
    desktop: { openLogDir: () => {}, sendWireCommand: () => {} },
  };
  const ctx = { store: storeStub };
  // 临时把 window 指到 stub（commands 的执行经 window.*）
  const prevWindow = globalThis.window;
  globalThis.window = fakeWindow;
  try {
    for (const id of ["help", "status.show", "permissions.set", "logs.open", "inspector.toggle"]) {
      const res = await reg.execute(id, ctx, {});
      assert.equal(res.ok, true, `${id} 应执行成功`);
    }
    assert.ok(
      !events.includes("electromind:user-input"),
      "UI 命令不得派发 user-input（不创建 Run）",
    );
  } finally {
    globalThis.window = prevWindow;
  }
  resetCommandRegistry();
});

test("core commands: agent 命令带任务时派发 user-input（mode 正确）", async () => {
  resetCommandRegistry();
  const reg = getCommandRegistry();
  registerCoreCommands(reg);
  const events = [];
  const storeStub = {
    getActiveThreadId: () => "t1",
    getThread: () => ({ sessionMode: "agent", status: "idle", pendingPermits: [] }),
    getState: () => ({ bridgeActive: true }),
    updateThread: () => {},
    setInspector: () => {},
  };
  const fakeWindow = {
    dispatchEvent: (e) => events.push({ type: e.type, detail: e.detail }),
    desktop: {},
  };
  const prevWindow = globalThis.window;
  globalThis.window = fakeWindow;
  try {
    const res = await reg.execute("agent.agent", { store: storeStub }, { text: "跑 CP2K" });
    assert.equal(res.ok, true);
    const input = events.find((e) => e.type === "electromind:user-input");
    assert.ok(input, "agent 命令应派发 user-input");
    assert.equal(input.detail.mode, "agent");
    assert.equal(input.detail.text, "跑 CP2K");
    // 无任务 → 只切模式不派发
    events.length = 0;
    await reg.execute("agent.plan", { store: storeStub }, {});
    assert.ok(!events.some((e) => e.type === "electromind:user-input"));
  } finally {
    globalThis.window = prevWindow;
  }
  resetCommandRegistry();
});

test("core commands: 未接线的确定性命令不可用且不执行", async () => {
  resetCommandRegistry();
  const reg = getCommandRegistry();
  registerCoreCommands(reg);
  const ctx = { store: { getState: () => ({ bridgeActive: true }), getActiveThreadId: () => "t1", getThread: () => ({ artifacts: [] }) } };
  for (const id of ["doctor", "reconcile", "collect"]) {
    assert.equal(reg.isAvailable(id, ctx), false, `${id} 后端未接线应不可用`);
    const res = await reg.execute(id, ctx, {});
    assert.equal(res.ok, false);
  }
  resetCommandRegistry();
});

// ── P4: Skill 动态命令（SKILLS 分组）───────────────────────────────

const skill = (name, extra = {}) => ({
  name,
  description: `${name} desc`,
  source: "builtin",
  sha256: "abc",
  status: "available",
  invocation: "both",
  trust_state: "trusted",
  ...extra,
});

test("skill commands: trusted + invocable skills generate /<name>", () => {
  resetCommandRegistry();
  const reg = getCommandRegistry();
  registerSkillSlashCommands(reg, [skill("cp2k"), skill("rsess")]);
  assert.ok(reg.commandForSlash("cp2k"), "/cp2k 应生成");
  assert.ok(reg.commandForSlash("rsess"), "/rsess 应生成");
  const spec = reg.get("skill.cp2k");
  assert.equal(spec.kind, "agent", "Skill 命令为 agent 类（启动 Run）");
  assert.equal(spec.category, "skills", "Skill 命令归入 SKILLS 分组");
  resetCommandRegistry();
});

test("skill commands: untrusted and model-only skills are excluded", () => {
  resetCommandRegistry();
  const reg = getCommandRegistry();
  registerSkillSlashCommands(reg, [
    skill("untrusted-skill", { trust_state: "untrusted" }),
    skill("model-only", { invocation: "model" }),
    skill("ok-skill"),
  ]);
  assert.equal(reg.commandForSlash("untrusted-skill"), undefined, "未信任不出现");
  assert.equal(reg.commandForSlash("model-only"), undefined, "model-only 不出现");
  assert.ok(reg.commandForSlash("ok-skill"), "both 出现");
  resetCommandRegistry();
});

test("skill commands: missing trust_state fails closed even when loaded", () => {
  // spec 2026-08-07 §P3：trust_state 缺失 → 不可执行；不再用 available/loaded
  // 推断 trusted。任何状态回退都是信任边界缺陷。
  resetCommandRegistry();
  const reg = getCommandRegistry();
  registerSkillSlashCommands(reg, [
    skill("no-trust-loaded", { trust_state: undefined, status: "loaded" }),
    skill("no-trust-available", { trust_state: undefined, status: "available" }),
  ]);
  assert.equal(
    reg.commandForSlash("no-trust-loaded"),
    undefined,
    "缺 trust_state 即使 loaded 也不生成命令（fail-closed）",
  );
  assert.equal(
    reg.commandForSlash("no-trust-available"),
    undefined,
    "缺 trust_state 即使 available 也不生成命令（fail-closed）",
  );
  resetCommandRegistry();
});

test("skill commands: catalog refresh rebuilds without duplicates", () => {
  resetCommandRegistry();
  const reg = getCommandRegistry();
  registerSkillSlashCommands(reg, [skill("cp2k")]);
  const before = reg.size;
  // catalog 变化 → 重建（旧命令注销）
  registerSkillSlashCommands(reg, [skill("cp2k"), skill("vasp")]);
  assert.equal(reg.commandForSlash("cp2k")?.id, "skill.cp2k", "cp2k 仍在");
  assert.ok(reg.commandForSlash("vasp"), "vasp 新增");
  const cp2kCount = reg.all().filter((c) => c.id === "skill.cp2k").length;
  assert.equal(cp2kCount, 1, "刷新后无重复命令");
  assert.ok(reg.size >= before, "命令集只增不重复");
  resetCommandRegistry();
});

test("skill commands: execute dispatches user-input with skill + task", async () => {
  resetCommandRegistry();
  const reg = getCommandRegistry();
  registerSkillSlashCommands(reg, [skill("cp2k")]);
  const events = [];
  const storeStub = {
    getActiveThreadId: () => "t1",
    getThread: () => ({}),
    getState: () => ({ bridgeActive: true }),
    updateThread: () => {},
    setInspector: () => {},
  };
  const prevWindow = globalThis.window;
  globalThis.window = {
    dispatchEvent: (e) => events.push({ type: e.type, detail: e.detail }),
    desktop: {},
  };
  try {
    const res = await reg.execute("skill.cp2k", { store: storeStub }, { text: "跑输入文件" });
    assert.equal(res.ok, true);
    const input = events.find((e) => e.type === "electromind:user-input");
    assert.ok(input, "应派发 user-input");
    assert.equal(input.detail.skill, "cp2k", "skill 名随行（后端确定性激活）");
    assert.equal(input.detail.text, "跑输入文件");
  } finally {
    globalThis.window = prevWindow;
  }
  resetCommandRegistry();
});

// ── P3: /skill 根命令（slash_skill_v2 门控）──────────────────────────

test("skill root: /skill is gated on slash_skill_v2 (fail-closed default)", async () => {
  __seedDesktopFeaturesForTest({});
  resetCommandRegistry();
  const reg = getCommandRegistry();
  registerCoreCommands(reg);
  // 默认 flag=false → 不可用 + 任何入口执行都被拒（registry 层 fail-closed）
  assert.equal(reg.isAvailable("skill.root", mockCtx), false, "默认不可用");
  const res = await reg.execute("skill.root", mockCtx, {});
  assert.equal(res.ok, false);
  assert.match(res.error, /命令当前不可用/, "registry 拒绝执行不可用命令");
  resetCommandRegistry();
});

test("skill root: /skill no args opens picker (flag on)", async () => {
  __seedDesktopFeaturesForTest({ slash_skill_v2: true });
  resetCommandRegistry();
  const reg = getCommandRegistry();
  registerCoreCommands(reg);
  const events = [];
  const storeStub = {
    getActiveThreadId: () => "t1",
    getThread: () => ({}),
    getState: () => ({ bridgeActive: true }),
  };
  const prevWindow = globalThis.window;
  globalThis.window = {
    dispatchEvent: (e) => events.push({ type: e.type, detail: e.detail }),
    desktop: {},
  };
  try {
    assert.equal(reg.isAvailable("skill.root", { store: storeStub }), true);
    const res = await reg.execute(
      "skill.root",
      { store: storeStub },
      { name: "", rest: "", text: "" },
    );
    assert.equal(res.ok, true);
    assert.ok(
      events.some((e) => e.type === "electromind:skill-picker-toggle"),
      "无参 → 打开 Skill Picker",
    );
  } finally {
    globalThis.window = prevWindow;
  }
  __seedDesktopFeaturesForTest({});
  resetCommandRegistry();
});

test("skill root: /skill list and /skill info (read-only)", async () => {
  __seedDesktopFeaturesForTest({ slash_skill_v2: true });
  resetCommandRegistry();
  const reg = getCommandRegistry();
  registerCoreCommands(reg);
  const storeStub = {
    getActiveThreadId: () => "t1",
    getThread: () => ({
      skillsState: {
        skills: [
          skill("cp2k"),
          skill("demo", { trust_state: "untrusted" }),
        ],
      },
    }),
    getState: () => ({ bridgeActive: true }),
  };
  const ctx = { store: storeStub };
  const list = await reg.execute(
    "skill.root",
    ctx,
    { name: "list", rest: "", text: "list" },
  );
  assert.equal(list.ok, true);
  assert.match(list.message, /cp2k · Trusted/);
  assert.match(list.message, /demo · Untrusted/);
  const info = await reg.execute(
    "skill.root",
    ctx,
    { name: "info", rest: "cp2k", text: "info cp2k" },
  );
  assert.equal(info.ok, true);
  assert.match(info.message, /名称: cp2k/);
  const miss = await reg.execute(
    "skill.root",
    ctx,
    { name: "info", rest: "nope", text: "info nope" },
  );
  assert.equal(miss.ok, false);
  __seedDesktopFeaturesForTest({});
  resetCommandRegistry();
});

test("skill root: /skill <name> <task> blocks untrusted and runs trusted", async () => {
  __seedDesktopFeaturesForTest({ slash_skill_v2: true });
  resetCommandRegistry();
  const reg = getCommandRegistry();
  registerCoreCommands(reg);
  const events = [];
  const storeStub = {
    getActiveThreadId: () => "t1",
    getThread: () => ({
      skillsState: {
        skills: [
          skill("cp2k"),
          skill("demo", { trust_state: "untrusted" }),
          skill("model-skill", { invocation: "model" }),
        ],
      },
    }),
    getState: () => ({ bridgeActive: true }),
  };
  const prevWindow = globalThis.window;
  globalThis.window = {
    dispatchEvent: (e) => events.push({ type: e.type, detail: e.detail }),
    desktop: {},
  };
  try {
    const ctx = { store: storeStub };
    // untrusted 被阻止
    const blocked = await reg.execute(
      "skill.root",
      ctx,
      { name: "demo", rest: "跑任务", text: "demo 跑任务" },
    );
    assert.equal(blocked.ok, false);
    assert.match(blocked.error, /未信任/);
    // trusted + 任务 → user-input 携带 skill（确定性激活）
    const ok = await reg.execute(
      "skill.root",
      ctx,
      { name: "cp2k", rest: "跑输入文件", text: "cp2k 跑输入文件" },
    );
    assert.equal(ok.ok, true);
    const input = events.find((e) => e.type === "electromind:user-input");
    assert.ok(input, "应派发 user-input");
    assert.equal(input.detail.skill, "cp2k");
    assert.equal(input.detail.text, "跑输入文件");
    // 缺任务描述 → 报错
    const noTask = await reg.execute(
      "skill.root",
      ctx,
      { name: "cp2k", rest: "", text: "cp2k" },
    );
    assert.equal(noTask.ok, false);
    // model-only → 拒绝用户调用
    const modelOnly = await reg.execute(
      "skill.root",
      ctx,
      { name: "model-skill", rest: "x", text: "model-skill x" },
    );
    assert.equal(modelOnly.ok, false);
  } finally {
    globalThis.window = prevWindow;
  }
  __seedDesktopFeaturesForTest({});
  resetCommandRegistry();
});

// ── P3 阶段 2: /skill 管理命令（deterministic 后端接口）─────────────

const MANAGER_IDS = [
  "skill.add",
  "skill.trust",
  "skill.revoke",
  "skill.update",
  "skill.remove",
  "skill.doctor",
];

/** wire 命令 spy 窗口：EventTarget（confirm-bridge 可收发）+ desktop spy。 */
function makeWireWindow(events, opts = {}) {
  const win = new EventTarget();
  win.desktop = {
    sendWireCommand: (cmd) => events.push({ type: "wire", cmd }),
    ...(opts.desktop ?? {}),
  };
  const realDispatch = win.dispatchEvent.bind(win);
  win.dispatchEvent = (e) => {
    events.push({ type: e.type, detail: e.detail });
    return realDispatch(e);
  };
  if (opts.confirm !== undefined) {
    win.addEventListener("electromind:confirm-request", (e) => {
      const d = e.detail;
      win.dispatchEvent(
        new CustomEvent("electromind:confirm-resolved", {
          detail: { requestId: d.requestId, ok: opts.confirm === "yes" },
        }),
      );
    });
  }
  return win;
}

function wireStore(skills) {
  return {
    getActiveThreadId: () => "t1",
    getThread: () => ({ skillsState: { skills } }),
    getState: () => ({ bridgeActive: true }),
  };
}

test("skill manager: all deterministic commands gated on slash_skill_v2 (fail-closed)", async () => {
  __seedDesktopFeaturesForTest({});
  resetCommandRegistry();
  const reg = getCommandRegistry();
  registerCoreCommands(reg);
  const prevWindow = globalThis.window;
  globalThis.window = makeWireWindow([]);
  try {
    for (const id of MANAGER_IDS) {
      assert.equal(reg.isAvailable(id, wireStore([])), false, `${id} 默认不可用`);
      const res = await reg.execute(id, wireStore([]), {});
      assert.equal(res.ok, false);
      assert.match(res.error, /命令当前不可用/, `${id} 被 registry 拒绝`);
    }
  } finally {
    globalThis.window = prevWindow;
  }
  __seedDesktopFeaturesForTest({});
  resetCommandRegistry();
});

test("skill trust/revoke/update: wire payloads correct", async () => {
  __seedDesktopFeaturesForTest({ slash_skill_v2: true });
  resetCommandRegistry();
  const reg = getCommandRegistry();
  registerCoreCommands(reg);
  const events = [];
  const prevWindow = globalThis.window;
  globalThis.window = makeWireWindow(events);
  try {
    const ctx = { store: wireStore([skill("cp2k")]) };
    const trust = await reg.execute("skill.trust", ctx, { name: "CP2K" });
    assert.equal(trust.ok, true);
    let wire = events.find((e) => e.type === "wire")?.cmd;
    assert.equal(wire.cmd, "skills/trust");
    assert.equal(wire.name, "cp2k");
    assert.equal(wire.granted, true);

    events.length = 0;
    const revoke = await reg.execute("skill.revoke", ctx, { name: "cp2k" });
    assert.equal(revoke.ok, true);
    wire = events.find((e) => e.type === "wire")?.cmd;
    assert.equal(wire.cmd, "skills/trust");
    assert.equal(wire.granted, false);

    events.length = 0;
    const update = await reg.execute("skill.update", ctx, { name: "cp2k" });
    assert.equal(update.ok, true);
    wire = events.find((e) => e.type === "wire")?.cmd;
    assert.equal(wire.cmd, "skills/update");
    assert.equal(wire.name, "cp2k");
  } finally {
    globalThis.window = prevWindow;
  }
  __seedDesktopFeaturesForTest({});
  resetCommandRegistry();
});

test("skill add: parses source + --trust → skills/install", async () => {
  __seedDesktopFeaturesForTest({ slash_skill_v2: true });
  resetCommandRegistry();
  const reg = getCommandRegistry();
  registerCoreCommands(reg);
  const events = [];
  const prevWindow = globalThis.window;
  globalThis.window = makeWireWindow(events);
  try {
    const ctx = { store: wireStore([]) };
    const res = await reg.execute("skill.add", ctx, {
      source: "https://github.com/x/demo",
      trust: true,
    });
    assert.equal(res.ok, true);
    let wire = events.find((e) => e.type === "wire")?.cmd;
    assert.equal(wire.cmd, "skills/install");
    assert.equal(wire.source, "https://github.com/x/demo");
    assert.equal(wire.trust, true);

    // 缺 source → 报错，不触发 wire
    events.length = 0;
    const noSrc = await reg.execute("skill.add", ctx, { source: "" });
    assert.equal(noSrc.ok, false);
    assert.equal(events.some((e) => e.type === "wire"), false);
  } finally {
    globalThis.window = prevWindow;
  }
  __seedDesktopFeaturesForTest({});
  resetCommandRegistry();
});

test("skill remove: confirm-yes → skills/remove; confirm-no → aborted", async () => {
  __seedDesktopFeaturesForTest({ slash_skill_v2: true });
  resetCommandRegistry();
  const reg = getCommandRegistry();
  registerCoreCommands(reg);
  const events = [];
  const ctx = { store: wireStore([skill("demo")]) };
  const prevWindow = globalThis.window;
  try {
    // 确认通过 → 触发 skills/remove
    globalThis.window = makeWireWindow(events, { confirm: "yes" });
    const yes = await reg.execute("skill.remove", ctx, { name: "demo" });
    assert.equal(yes.ok, true);
    const wire = events.find((e) => e.type === "wire")?.cmd;
    assert.equal(wire.cmd, "skills/remove");
    assert.equal(wire.name, "demo");

    // 取消 → 不触发 wire
    events.length = 0;
    globalThis.window = makeWireWindow(events, { confirm: "no" });
    const no = await reg.execute("skill.remove", ctx, { name: "demo" });
    assert.equal(no.ok, false);
    assert.match(no.error, /已取消/);
    assert.equal(events.some((e) => e.type === "wire"), false);
  } finally {
    globalThis.window = prevWindow;
  }
  __seedDesktopFeaturesForTest({});
  resetCommandRegistry();
});

test("skill doctor: read-only health text from skillsState", async () => {
  __seedDesktopFeaturesForTest({ slash_skill_v2: true });
  resetCommandRegistry();
  const reg = getCommandRegistry();
  registerCoreCommands(reg);
  const prevWindow = globalThis.window;
  const events = [];
  globalThis.window = makeWireWindow(events);
  try {
    const ctx = {
      store: wireStore([
        skill("cp2k"),
        skill("ghost", { trust_state: undefined }),
      ]),
    };
    const res = await reg.execute("skill.doctor", ctx, {});
    assert.equal(res.ok, true);
    assert.match(res.message, /Skills 2 · Trusted 1 · Untrusted 1/);
    assert.match(res.message, /缺少 trust_state/);
    assert.equal(events.some((e) => e.type === "wire"), false, "doctor 只读，不触发 wire");
  } finally {
    globalThis.window = prevWindow;
  }
  __seedDesktopFeaturesForTest({});
  resetCommandRegistry();
});

test("skill root: /skill trust <name> and /skill add <src> --trust delegate to deterministic", async () => {
  __seedDesktopFeaturesForTest({ slash_skill_v2: true });
  resetCommandRegistry();
  const reg = getCommandRegistry();
  registerCoreCommands(reg);
  const events = [];
  const prevWindow = globalThis.window;
  globalThis.window = makeWireWindow(events);
  try {
    const ctx = { store: wireStore([skill("cp2k")]) };
    // /skill trust cp2k
    const t = await reg.execute("skill.root", ctx, {
      name: "trust",
      rest: "cp2k",
      text: "trust cp2k",
    });
    assert.equal(t.ok, true);
    let wire = events.find((e) => e.type === "wire")?.cmd;
    assert.equal(wire.cmd, "skills/trust");
    assert.equal(wire.name, "cp2k");
    assert.equal(wire.granted, true);

    // /skill add https://x --trust
    events.length = 0;
    const a = await reg.execute("skill.root", ctx, {
      name: "add",
      rest: "https://github.com/x/demo --trust",
      text: "add https://github.com/x/demo --trust",
    });
    assert.equal(a.ok, true);
    wire = events.find((e) => e.type === "wire")?.cmd;
    assert.equal(wire.cmd, "skills/install");
    assert.equal(wire.source, "https://github.com/x/demo");
    assert.equal(wire.trust, true);
  } finally {
    globalThis.window = prevWindow;
  }
  __seedDesktopFeaturesForTest({});
  resetCommandRegistry();
});
