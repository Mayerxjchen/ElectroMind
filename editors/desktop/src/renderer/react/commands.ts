/** 核心命令集 —— P1（修订版文档 §5 三类命令）。
 *
 * 只做注册；执行时经 window / window.desktop / 事件桥 / store 访问能力。
 * 注册本身无副作用（可在 node --test 下直接导入测试元数据与行为）。
 *
 * 事件桥（main.ts 监听）：
 *   electromind:open-shortcuts / open-settings / toggle-threads
 *   electromind:user-input / stop / skills-open / focus-composer /
 *   palette-toggle / enqueue-next
 */

import type { CommandRegistry, CommandSpec, CommandContext } from "./command-registry";
import { modelPolicyLabel, modelSelectionFromPolicy } from "./model-policy.ts";

/** /full 等危险命令的二次确认 —— 经事件桥走 vanilla confirm 模态。
 *  main.ts 监听 electromind:confirm-request，完成后回发
 *  electromind:confirm-resolved{requestId, ok}。 */
let confirmSeq = 0;
function requestConfirm(opts: {
  title: string;
  message: string;
  confirmText: string;
  cancelText?: string;
}): Promise<boolean> {
  const requestId = `confirm-${++confirmSeq}`;
  return new Promise<boolean>((resolve) => {
    const onResolved = (e: Event) => {
      const d = (e as CustomEvent).detail as {
        requestId?: string;
        ok?: boolean;
      };
      if (d.requestId !== requestId) return;
      window.removeEventListener("electromind:confirm-resolved", onResolved);
      resolve(Boolean(d.ok));
    };
    window.addEventListener("electromind:confirm-resolved", onResolved);
    window.dispatchEvent(
      new CustomEvent("electromind:confirm-request", {
        detail: {
          requestId,
          title: opts.title,
          message: opts.message,
          confirmText: opts.confirmText,
          cancelText: opts.cancelText,
        },
      }),
    );
  });
}

// ── 事件 / 能力助手 ─────────────────────────────────────────────────

function dispatch(name: string, detail?: unknown): void {
  window.dispatchEvent(new CustomEvent(name, { detail }));
}

function sendInput(text: string, mode: string): void {
  dispatch("electromind:user-input", { text, delivery: "auto", mode });
}

function activeThread(ctx: CommandContext) {
  const id = ctx.store.getActiveThreadId();
  return id ? ctx.store.getThread(id) ?? null : null;
}

function activeThreadId(ctx: CommandContext): string | null {
  return ctx.store.getActiveThreadId();
}

function targetLabel(thread: ReturnType<typeof activeThread>): string {
  const t = thread?.executionTarget as { kind?: string; host?: string } | null;
  if (!t || t.kind === "local") return "Local";
  if (t.kind === "ssh") return `SSH · ${t.host ?? ""}`;
  if (t.kind === "sandbox") return "Docker Sandbox";
  return "Local";
}

function modeLabel(mode: string): string {
  return mode === "plan" ? "Plan" : mode === "ask" ? "Ask" : "Agent";
}

// ── 命令构建 ────────────────────────────────────────────────────────

/** UI 命令：不经过 LLM、不创建 Run。 */
function ui(
  spec: Omit<CommandSpec, "kind">,
): CommandSpec {
  return { ...spec, kind: "ui" };
}

/** 确定性命令：调用后端结构化接口。 */
function deterministic(
  spec: Omit<CommandSpec, "kind">,
): CommandSpec {
  return { ...spec, kind: "deterministic" };
}

/** Agent 命令：启动或排队 Agent Run。 */
function agent(
  spec: Omit<CommandSpec, "kind">,
): CommandSpec {
  return { ...spec, kind: "agent" };
}

// ── 注册 ────────────────────────────────────────────────────────────

/** 注册核心命令集（幂等：已注册过则跳过 —— renderer reload 后 Registry
 *  仍只有一份）。 */
export function registerCoreCommands(registry: CommandRegistry): void {
  if (registry.size > 0) return;

  const specList: CommandSpec[] = [
    // ── View ──────────────────────────────────────────────────────
    ui({
      id: "palette.open",
      title: "打开 Command Palette",
      description: "搜索并执行所有可用操作",
      category: "view",
      shortcut: "meta+k",
      available: () => true,
      execute: () => {
        dispatch("electromind:palette-toggle");
        return { ok: true };
      },
    }),
    ui({
      id: "composer.focus",
      title: "聚焦输入框",
      description: "把焦点移到 Composer",
      category: "view",
      shortcut: "meta+l",
      available: () => true,
      execute: () => {
        dispatch("electromind:focus-composer");
        return { ok: true };
      },
    }),
    ui({
      id: "composer.enqueue",
      title: "排队下一任务",
      description: "下一轮执行（Cmd+Shift+Enter）",
      category: "view",
      shortcut: "meta+shift+enter",
      available: () => true,
      execute: () => {
        dispatch("electromind:enqueue-next");
        return { ok: true };
      },
    }),
    ui({
      id: "sidebar.toggle-threads",
      title: "展开 / 收起 Threads",
      description: "切换左侧线程列表",
      category: "view",
      shortcut: "meta+b",
      available: () => true,
      execute: () => {
        dispatch("electromind:toggle-threads");
        return { ok: true };
      },
    }),
    ui({
      id: "inspector.toggle",
      title: "打开 / 关闭 Inspector",
      description: "右侧详情抽屉",
      category: "view",
      shortcut: "meta+i",
      available: () => true,
      execute: (ctx) => {
        const open = ctx.store.getState().inspector.open;
        ctx.store.setInspector({ open: !open });
        return { ok: true, message: open ? "Inspector 已关闭" : "Inspector 已打开" };
      },
    }),
    ui({
      id: "run.stop",
      title: "停止当前 Run",
      description: "停止正在运行的 Agent",
      category: "view",
      shortcut: "escape",
      slash: ["stop"],
      available: (ctx) => {
        const t = activeThread(ctx);
        return t?.status === "running" || (t?.pendingPermits?.length ?? 0) > 0;
      },
      execute: () => {
        dispatch("electromind:stop");
        return { ok: true };
      },
    }),

    // ── Thread ────────────────────────────────────────────────────
    ui({
      id: "thread.new",
      title: "新建 Thread",
      description: "创建新会话",
      category: "thread",
      slash: ["new"],
      shortcut: "meta+n",
      usage: "/new [title]",
      available: () => true,
      execute: async (ctx, args) => {
        const sm = ctx.sessionManager as
          | { newThread: (opts?: Record<string, unknown>) => Promise<string> }
          | undefined;
        if (!sm) return { ok: false, error: "会话管理器未就绪" };
        const title = String(args.title ?? "");
        await sm.newThread(title ? { title } : undefined);
        return { ok: true };
      },
    }),
    ui({
      id: "thread.resume",
      title: "恢复 Thread",
      description: "重放当前会话历史",
      category: "thread",
      slash: ["resume"],
      usage: "/resume",
      available: () => true,
      execute: async (ctx) => {
        const sm = ctx.sessionManager as
          | { switchThread: (id: string) => Promise<void> }
          | undefined;
        const id = activeThreadId(ctx);
        if (!sm || !id) return { ok: false, error: "没有可恢复的会话" };
        await sm.switchThread(id);
        return { ok: true };
      },
    }),
    // 后端无 thread/rename 写接口 —— 注册但不可用（P2 不假装能持久化）
    ui({
      id: "thread.rename",
      title: "重命名 Thread",
      description: "修改会话标题（需后端写接口，尚未接线）",
      category: "thread",
      slash: ["rename"],
      usage: "/rename <title>",
      available: () => false,
      execute: () => ({ ok: false, error: "thread/rename 后端写接口尚未接线" }),
    }),
    ui({
      id: "thread.compact",
      title: "压缩上下文",
      description: "压缩当前会话上下文（需后端接口，尚未接线）",
      category: "thread",
      slash: ["compact"],
      usage: "/compact [focus]",
      available: () => false,
      execute: () => ({ ok: false, error: "compact 后端接口尚未接线" }),
    }),

    // ── Mode ──────────────────────────────────────────────────────
    ui({
      id: "mode.cycle",
      title: "切换任务模式",
      description: "Ask → Plan → Agent 循环",
      category: "mode",
      shortcut: "meta+.",
      available: () => true,
      execute: (ctx) => {
        const id = activeThreadId(ctx);
        if (!id) return { ok: false, error: "没有活动会话" };
        const current = ctx.store.getThread(id)?.sessionMode ?? "agent";
        const next = current === "ask" ? "plan" : current === "plan" ? "agent" : "ask";
        ctx.store.updateThread(id, { sessionMode: next } as never);
        return { ok: true, message: `模式已切换为 ${modeLabel(next)}` };
      },
    }),

    // ── Permissions ───────────────────────────────────────────────
    ui({
      id: "permissions.set",
      title: "设置权限模式",
      description: "Prompt / Auto-safe / Full access",
      category: "permissions",
      slash: ["permissions"],
      usage: "/permissions [prompt|safe|full]",
      available: () => true,
      execute: (ctx, args) => {
        const id = activeThreadId(ctx);
        if (!id) return { ok: false, error: "没有活动会话" };
        const level = String(args.level ?? "");
        if (level) {
          const mapped =
            level === "full" || level === "full-access"
              ? "full-access"
              : level === "safe" || level === "auto-safe"
                ? "auto-safe"
                : level === "prompt"
                  ? "prompt"
                  : "";
          if (!mapped) return { ok: false, error: `未知权限级别: ${level}` };
          ctx.store.updateThread(id, { autonomy: mapped } as never);
          return { ok: true, message: `权限已切换为 ${mapped}` };
        }
        const current = ctx.store.getThread(id)?.autonomy ?? "prompt";
        return { ok: true, message: `当前权限: ${current}` };
      },
    }),
    // P2: 短别名 —— /prompt /safe 直接生效；/full 二次确认，只作用于当前 Thread
    ui({
      id: "permissions.prompt",
      title: "权限：Prompt",
      description: "每次工具调用都询问",
      category: "permissions",
      slash: ["prompt"],
      available: () => true,
      execute: (ctx) => {
        const id = activeThreadId(ctx);
        if (!id) return { ok: false, error: "没有活动会话" };
        ctx.store.updateThread(id, { autonomy: "prompt" } as never);
        return { ok: true, message: "权限已切换为 prompt" };
      },
    }),
    ui({
      id: "permissions.safe",
      title: "权限：Auto-safe",
      description: "只读操作自动放行，外部副作用询问",
      category: "permissions",
      slash: ["safe"],
      available: () => true,
      execute: (ctx) => {
        const id = activeThreadId(ctx);
        if (!id) return { ok: false, error: "没有活动会话" };
        ctx.store.updateThread(id, { autonomy: "auto-safe" } as never);
        return { ok: true, message: "权限已切换为 auto-safe" };
      },
    }),
    ui({
      id: "permissions.full",
      title: "权限：Full access",
      description: "自动批准（需二次确认，只作用于当前 Thread）",
      category: "permissions",
      slash: ["full"],
      available: () => true,
      execute: async (ctx) => {
        const id = activeThreadId(ctx);
        if (!id) return { ok: false, error: "没有活动会话" };
        const ok = await requestConfirm({
          title: "切换到 Full access？",
          message: "Full access 会自动批准工具调用（含可能的外部副作用）。此设置只作用于当前 Thread，不改变全局默认。",
          confirmText: "切换到 Full access",
          cancelText: "取消",
        });
        if (!ok) return { ok: false, error: "已取消" };
        ctx.store.updateThread(id, { autonomy: "full-access" } as never);
        return { ok: true, message: "权限已切换为 full-access（当前 Thread）" };
      },
    }),

    // ── Execution ─────────────────────────────────────────────────
    ui({
      id: "target.show",
      title: "查看执行目标",
      description: "Local / Docker Sandbox / SSH",
      category: "execution",
      slash: ["target"],
      usage: "/target [local|sandbox|ssh]",
      // 切换目标需要后端 target/switch（尚未接线）；展示恒可用，
      // 带参数执行时返回明确错误。
      available: () => true,
      execute: (ctx, args) => {
        if (args.target) {
          return { ok: false, error: "执行目标切换需要后端接线（当前仅可查看 /target）" };
        }
        return { ok: true, message: `执行目标: ${targetLabel(activeThread(ctx))}` };
      },
    }),

    // ── Model ─────────────────────────────────────────────────────
    ui({
      id: "model.set",
      title: "选择模型",
      description: "Auto / Fast / Balanced / Best / Plan→Execute / 指定模型",
      category: "execution",
      slash: ["model"],
      usage: "/model [auto|fast|balanced|best|plan-execute|<model-id>]",
      available: () => true,
      execute: (ctx, args) => {
        const id = activeThreadId(ctx);
        if (!id) return { ok: false, error: "没有活动会话" };
        const modelArg = String(args.model ?? "");
        if (!modelArg) {
          // 无参数 → 打开 Model Picker
          dispatch("electromind:model-picker-toggle");
          return { ok: true, message: "Model Picker 已打开" };
        }
        const selection = modelSelectionFromPolicy(modelArg);
        ctx.store.updateThread(id, { model: selection } as never);
        return { ok: true, message: `模型策略已切换为 ${modelPolicyLabel(selection)}` };
      },
    }),

    // ── Skills ────────────────────────────────────────────────────
    ui({
      id: "skills.open",
      title: "打开 Skills 面板",
      description: "查看 / 安装 / 信任 Skills",
      category: "skills",
      slash: ["skills"],
      available: () => true,
      execute: () => {
        dispatch("electromind:skills-open");
        return { ok: true };
      },
    }),
    ui({
      id: "skills.info",
      title: "查看 Skill 信息",
      description: "名称 / 来源 / Digest / 状态",
      category: "skills",
      slash: ["skill-info"],
      usage: "/skill-info <name>",
      available: (ctx) => {
        const t = activeThread(ctx);
        return Boolean(t?.skillsState?.skills.length);
      },
      execute: (ctx, args) => {
        const name = String(args.name ?? "").trim().toLowerCase();
        if (!name) return { ok: false, error: "需要 skill 名称（/skill-info <name>）" };
        const t = activeThread(ctx);
        const skill = t?.skillsState?.skills.find(
          (s) => s.name.toLowerCase() === name,
        );
        if (!skill) {
          return { ok: false, error: `Skill 不存在: ${args.name}` };
        }
        return {
          ok: true,
          message: `${skill.name} · ${skill.source} · sha256 ${skill.sha256.slice(0, 8)} · ${skill.status}`,
        };
      },
    }),
    ui({
      id: "jobs.show",
      title: "查看 Slurm 作业",
      description: "打开 Inspector 的 Job 视图并刷新提交记录",
      category: "diagnostics",
      slash: ["jobs"],
      available: (ctx) => Boolean(ctx.store.getState().bridgeActive && window.desktop?.sendWireCommand),
      execute: (ctx) => {
        const id = activeThreadId(ctx);
        if (!id) return { ok: false, error: "没有活动会话" };
        ctx.store.setInspector({ open: true, activeTab: "jobs" });
        void window.desktop.sendWireCommand({ cmd: "hpc/submissions", thread_id: id });
        return { ok: true, message: "作业列表已刷新（Inspector → 任务）" };
      },
    }),
    ui({
      id: "artifacts.show",
      title: "查看 Artifacts",
      description: "打开 Inspector 的产物视图",
      category: "diagnostics",
      slash: ["artifacts"],
      available: () => true,
      execute: (ctx) => {
        ctx.store.setInspector({ open: true, activeTab: "artifacts" });
        return { ok: true, message: "产物视图已打开（Inspector → 产物）" };
      },
    }),

    // ── Diagnostics ───────────────────────────────────────────────
    ui({
      id: "status.show",
      title: "查看状态",
      description: "模式 / 权限 / 目标 / 传输 / 活动状态",
      category: "diagnostics",
      slash: ["status"],
      available: () => true,
      execute: (ctx) => {
        const s = ctx.store.getState();
        const t = activeThread(ctx);
        const parts = [
          `模式 ${modeLabel(t?.sessionMode ?? "agent")}`,
          `权限 ${t?.autonomy ?? "prompt"}`,
          `目标 ${targetLabel(t)}`,
          `传输 ${s.transport}`,
          `活动 ${s.activityState}`,
        ];
        return { ok: true, message: parts.join(" · ") };
      },
    }),
    ui({
      id: "logs.open",
      title: "打开日志目录",
      description: "Desktop / Agent / Wire 日志",
      category: "diagnostics",
      slash: ["logs"],
      available: () => Boolean(window.desktop?.openLogDir),
      execute: () => {
        void window.desktop.openLogDir();
        return { ok: true };
      },
    }),
    ui({
      id: "help",
      title: "帮助与快捷键",
      description: "打开快捷键与心智模型面板",
      category: "developer",
      slash: ["help"],
      available: () => true,
      execute: () => {
        dispatch("electromind:open-shortcuts");
        return { ok: true };
      },
    }),

    // ── Deterministic（后端结构化接口，不让模型猜测）──────────────
    deterministic({
      id: "skills.reload",
      title: "重新发现 Skills",
      description: "触发 Catalog 重新加载",
      category: "skills",
      slash: ["reload-skills"],
      available: (ctx) => {
        const id = activeThreadId(ctx);
        return Boolean(id && window.desktop?.sendWireCommand);
      },
      execute: (ctx) => {
        const id = activeThreadId(ctx);
        if (!id) return { ok: false, error: "没有活动会话" };
        void window.desktop.sendWireCommand({ cmd: "skills/reload", thread_id: id });
        return { ok: true, message: "Skills 目录重新发现已触发" };
      },
    }),
    deterministic({
      id: "artifact.validate",
      title: "验证产物",
      description: "用解析器验证 Artifact",
      category: "diagnostics",
      slash: ["validate"],
      usage: "/validate <artifact_id> [parser]",
      available: (ctx) => {
        const t = activeThread(ctx);
        return Boolean(t && t.artifacts?.length && window.desktop?.sendWireCommand);
      },
      execute: (ctx, args) => {
        const id = activeThreadId(ctx);
        const artifactId = String(args.artifact_id ?? "");
        if (!id || !artifactId) {
          return { ok: false, error: "需要 artifact_id（/validate <artifact_id> [parser]）" };
        }
        void window.desktop.sendWireCommand({
          cmd: "artifact/validate",
          thread_id: id,
          artifact_id: artifactId,
          parser: String(args.parser ?? "auto"),
        });
        return { ok: true, message: `验证已触发: ${artifactId}` };
      },
    }),
    // 后端接口尚未接线（P2 接入）—— 注册但不可用，避免出现在可用列表
    deterministic({
      id: "doctor",
      title: "数据 Doctor",
      description: "检查 Thread / Artifact 数据健康",
      category: "diagnostics",
      slash: ["doctor"],
      usage: "/doctor [data]",
      available: () => false,
      execute: () => ({ ok: false, error: "doctor 后端接口尚未接线（P2）" }),
    }),
    deterministic({
      id: "reconcile",
      title: "对账 Slurm 作业",
      description: "同步远端作业状态",
      category: "diagnostics",
      slash: ["reconcile"],
      usage: "/reconcile [job-id]",
      available: () => false,
      execute: () => ({ ok: false, error: "reconcile 后端接口尚未接线（P2）" }),
    }),
    deterministic({
      id: "collect",
      title: "收集作业输出",
      description: "拉取远端作业产物",
      category: "diagnostics",
      slash: ["collect"],
      usage: "/collect [job-id]",
      available: () => false,
      execute: () => ({ ok: false, error: "collect 后端接口尚未接线（P2）" }),
    }),

    // ── Agent（启动或排队 Agent Run）─────────────────────────────
    agent({
      id: "agent.ask",
      title: "Ask",
      description: "解释与查询（不执行任务）",
      category: "mode",
      slash: ["ask"],
      usage: "/ask <task>",
      available: (ctx) => Boolean(ctx.store.getState().bridgeActive),
      execute: (ctx, args) => {
        const id = activeThreadId(ctx);
        if (!id) return { ok: false, error: "没有活动会话" };
        ctx.store.updateThread(id, { sessionMode: "ask" } as never);
        const text = String(args.text ?? "").trim();
        if (text) sendInput(text, "ask");
        return { ok: true, message: text ? "Ask 任务已发送" : "已切换 Ask 模式" };
      },
    }),
    agent({
      id: "agent.plan",
      title: "Plan",
      description: "调研并制定计划",
      category: "mode",
      slash: ["plan"],
      usage: "/plan <task>",
      available: (ctx) => Boolean(ctx.store.getState().bridgeActive),
      execute: (ctx, args) => {
        const id = activeThreadId(ctx);
        if (!id) return { ok: false, error: "没有活动会话" };
        ctx.store.updateThread(id, { sessionMode: "plan" } as never);
        const text = String(args.text ?? "").trim();
        if (text) sendInput(text, "plan");
        return { ok: true, message: text ? "Plan 任务已发送" : "已切换 Plan 模式" };
      },
    }),
    agent({
      id: "agent.agent",
      title: "Agent",
      description: "执行完整任务",
      category: "mode",
      slash: ["agent"],
      usage: "/agent <task>",
      available: (ctx) => Boolean(ctx.store.getState().bridgeActive),
      execute: (ctx, args) => {
        const id = activeThreadId(ctx);
        if (!id) return { ok: false, error: "没有活动会话" };
        ctx.store.updateThread(id, { sessionMode: "agent" } as never);
        const text = String(args.text ?? "").trim();
        if (text) sendInput(text, "agent");
        return { ok: true, message: text ? "Agent 任务已发送" : "已切换 Agent 模式" };
      },
    }),
  ];

  for (const spec of specList) {
    registry.register(spec);
  }
}
