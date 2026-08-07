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

import type { CommandRegistry, CommandSpec, CommandContext, ParsedArgs } from "./command-registry.ts";
import { getCommandRegistry } from "./command-registry.ts";
import { modelPolicyLabel, modelSelectionFromPolicy } from "./model-policy.ts";
import { requestConfirm } from "./confirm-bridge.ts";
import { isSkillTrusted } from "../store/types.ts";
import { currentFeature } from "../features.ts";
import { skillDoctorText, skillInfoText, skillListText } from "./skill-view.ts";

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

/** /skill add 参数：`<source> [--trust]` → { source, trust }。 */
function parseAddArgs(rest: string): ParsedArgs {
  const tokens = rest.trim().split(/\s+/).filter(Boolean);
  const trust = tokens.includes("--trust");
  const source = tokens.filter((t) => t !== "--trust").join(" ");
  return { source, trust };
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
    // ── /skill 根命令（P3，slash_skill_v2 门控）────────────────────
    // 无参 → Skill Picker（选择只补全 /skill <name>，不立即执行）；
    // /skill list、/skill info <name> 为只读 UI 命令；
    // /skill <name> <task> 为 agent 命令（携带 skill 行，确定性激活）；
    // 管理动词（add/trust/revoke/update/remove/reload/doctor）在 P3
    // 阶段 2（deterministic 后端命令）接线。
    ui({
      id: "skill.root",
      title: "Skill 命令",
      description: "查看 / 调用已安装 Skills（/skill 打开 Picker）",
      category: "skills",
      slash: ["skill"],
      usage: "/skill | /skill list | /skill info <name> | /skill <name> <task>",
      available: () => currentFeature("slash_skill_v2"),
      execute: (ctx, args) => {
        // fail-closed：flag 关闭时任何入口都不可执行
        if (!currentFeature("slash_skill_v2")) {
          return { ok: false, error: "slash_skill_v2 未启用" };
        }
        const threadId = activeThreadId(ctx);
        const name = String(args.name ?? "").trim().toLowerCase();
        if (!name) {
          if (!threadId) return { ok: false, error: "没有活动会话" };
          dispatch("electromind:skill-picker-toggle");
          return { ok: true, message: "Skill Picker 已打开" };
        }
        if (name === "list") {
          const t = activeThread(ctx);
          const skills = t?.skillsState?.skills ?? [];
          return { ok: true, message: skillListText(skills) };
        }
        if (name === "info") {
          const target = String(args.rest ?? "").trim().toLowerCase();
          if (!target) {
            return { ok: false, error: "需要 skill 名称（/skill info <name>）" };
          }
          const t = activeThread(ctx);
          const skill = t?.skillsState?.skills.find(
            (s) => s.name.toLowerCase() === target,
          );
          if (!skill) return { ok: false, error: `Skill 不存在: ${target}` };
          return { ok: true, message: skillInfoText(skill) };
        }
        // 管理动词 → 委派给 deterministic 命令（本文件下方注册）。
        // 委派经 registry.execute 重跑 availability（一致 fail-closed）。
        const rest = String(args.rest ?? "").trim();
        if (name === "add") {
          return getCommandRegistry().execute(
            "skill.add",
            ctx,
            parseAddArgs(rest),
          );
        }
        const VERB_TARGETS: Record<string, string> = {
          trust: "skill.trust",
          revoke: "skill.revoke",
          update: "skill.update",
          remove: "skill.remove",
          reload: "skills.reload",
          doctor: "skill.doctor",
        };
        if (VERB_TARGETS[name]) {
          const noArg = name === "doctor" || name === "reload";
          return getCommandRegistry().execute(
            VERB_TARGETS[name],
            ctx,
            noArg ? {} : { name: rest },
          );
        }
        // /skill <name> <task> —— agent 执行（Skill 确定性激活）
        const task = rest;
        if (!task) {
          return { ok: false, error: `需要任务描述（/skill ${name} <task>）` };
        }
        const t = activeThread(ctx);
        const skill = t?.skillsState?.skills.find(
          (s) => s.name.toLowerCase() === name,
        );
        if (!skill) return { ok: false, error: `Skill 不存在: ${name}` };
        if (!isSkillTrusted(skill)) {
          return {
            ok: false,
            error: `Skill 未信任，不可调用（/skill trust ${name}）`,
          };
        }
        const invocation = skill.invocation ?? "both";
        if (invocation === "model") {
          return { ok: false, error: `${name} 仅模型可调用` };
        }
        if (!threadId) return { ok: false, error: "没有活动会话" };
        // 携带 skill 名 + 任务文本；后端确定性激活（不绕过权限模式）
        dispatch("electromind:user-input", {
          text: task,
          delivery: "auto",
          mode: "agent",
          skill: name,
        });
        return { ok: true, message: `已启动 ${name} 任务（Skill 激活注入上下文）` };
      },
    }),
    // ── /skill 管理命令（P3 阶段 2，deterministic 后端接口）──────────
    // 全部门控 slash_skill_v2 + 活动会话 + sendWireCommand；wire 命令在
    // main 侧属 ALLOWED_WIRE_COMMANDS（模型不可触发，仅用户显式操作）。
    deterministic({
      id: "skill.add",
      title: "安装 Skill",
      description: "从 git URL / 本地目录安装（/skill add <source> [--trust]）",
      category: "skills",
      slash: ["skill-add"],
      usage: "/skill add <source> [--trust]",
      available: (ctx) =>
        currentFeature("slash_skill_v2") &&
        Boolean(activeThreadId(ctx) && window.desktop?.sendWireCommand),
      execute: (ctx, args) => {
        const id = activeThreadId(ctx);
        const source = String(args.source ?? "").trim();
        if (!id || !source) {
          return {
            ok: false,
            error: "需要 source（/skill add <git-url|本地目录> [--trust]）",
          };
        }
        const trust = Boolean(args.trust);
        void window.desktop.sendWireCommand({
          cmd: "skills/install",
          thread_id: id,
          source,
          trust,
        });
        return {
          ok: true,
          message: `安装已触发: ${source}${trust ? "（并授予信任）" : ""}`,
        };
      },
    }),
    deterministic({
      id: "skill.trust",
      title: "信任 Skill",
      description: "授予已安装 Skill 信任（/skill trust <name>）",
      category: "skills",
      slash: ["skill-trust"],
      usage: "/skill trust <name>",
      available: (ctx) =>
        currentFeature("slash_skill_v2") &&
        Boolean(activeThreadId(ctx) && window.desktop?.sendWireCommand),
      execute: (ctx, args) => {
        const id = activeThreadId(ctx);
        const name = String(args.name ?? "").trim().toLowerCase();
        if (!id || !name) {
          return { ok: false, error: "需要 skill 名称（/skill trust <name>）" };
        }
        void window.desktop.sendWireCommand({
          cmd: "skills/trust",
          thread_id: id,
          name,
          granted: true,
        });
        return { ok: true, message: `已触发信任: ${name}` };
      },
    }),
    deterministic({
      id: "skill.revoke",
      title: "撤销 Skill 信任",
      description: "撤销已安装 Skill 的信任（/skill revoke <name>）",
      category: "skills",
      slash: ["skill-revoke"],
      usage: "/skill revoke <name>",
      available: (ctx) =>
        currentFeature("slash_skill_v2") &&
        Boolean(activeThreadId(ctx) && window.desktop?.sendWireCommand),
      execute: (ctx, args) => {
        const id = activeThreadId(ctx);
        const name = String(args.name ?? "").trim().toLowerCase();
        if (!id || !name) {
          return { ok: false, error: "需要 skill 名称（/skill revoke <name>）" };
        }
        void window.desktop.sendWireCommand({
          cmd: "skills/trust",
          thread_id: id,
          name,
          granted: false,
        });
        return { ok: true, message: `已触发撤销信任: ${name}` };
      },
    }),
    deterministic({
      id: "skill.update",
      title: "更新 Skill",
      description: "从记录来源重新安装并刷新（/skill update <name>）",
      category: "skills",
      slash: ["skill-update"],
      usage: "/skill update <name>",
      available: (ctx) =>
        currentFeature("slash_skill_v2") &&
        Boolean(activeThreadId(ctx) && window.desktop?.sendWireCommand),
      execute: (ctx, args) => {
        const id = activeThreadId(ctx);
        const name = String(args.name ?? "").trim().toLowerCase();
        if (!id || !name) {
          return { ok: false, error: "需要 skill 名称（/skill update <name>）" };
        }
        void window.desktop.sendWireCommand({
          cmd: "skills/update",
          thread_id: id,
          name,
        });
        return { ok: true, message: `已触发更新: ${name}` };
      },
    }),
    deterministic({
      id: "skill.remove",
      title: "卸载 Skill",
      description: "卸载 installer 管理的 Skill（需二次确认）",
      category: "skills",
      slash: ["skill-remove"],
      usage: "/skill remove <name>",
      available: (ctx) =>
        currentFeature("slash_skill_v2") &&
        Boolean(activeThreadId(ctx) && window.desktop?.sendWireCommand),
      execute: async (ctx, args) => {
        const id = activeThreadId(ctx);
        const name = String(args.name ?? "").trim().toLowerCase();
        if (!id || !name) {
          return { ok: false, error: "需要 skill 名称（/skill remove <name>）" };
        }
        const ok = await requestConfirm({
          title: `卸载 Skill「${name}」？`,
          message: `将移除 ${name} 及其安装目录（installer 管理的 Skill）。此操作不可撤销。`,
          confirmText: "卸载",
          cancelText: "取消",
        });
        if (!ok) return { ok: false, error: "已取消" };
        void window.desktop.sendWireCommand({
          cmd: "skills/remove",
          thread_id: id,
          name,
        });
        return { ok: true, message: `已触发卸载: ${name}` };
      },
    }),
    deterministic({
      id: "skill.doctor",
      title: "Skills 健康检查",
      description: "检查 Skills 状态完整性（信任 / 命名 / 重复）",
      category: "skills",
      slash: ["skill-doctor"],
      usage: "/skill doctor",
      available: () => currentFeature("slash_skill_v2"),
      execute: (ctx) => {
        const t = activeThread(ctx);
        const skills = t?.skillsState?.skills ?? [];
        return { ok: true, message: skillDoctorText(skills) };
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

/** Skill 命令 id 前缀（动态命令集刷新用）。 */
export const SKILL_COMMAND_PREFIX = "skill.";

/** P4: 为可信且允许用户调用的 Skill 动态生成 /<name> 命令。
 *
 * 规则（修订版文档 §8）：
 *   - 只生成 可信（trust_state=trusted）且 invocation ∈ {manual, both}
 *     的 Skill；未信任 Skill 不出现在可执行列表；
 *   - 执行：以任务文本启动 Agent Run 并携带 skill（input/send 的
 *     skill 字段 —— 后端确定性激活，不走模型猜测）；
 *   - Slash 调用不绕过 Trust/审批/Sandbox/幂等/HPC record/Artifact
 *     Validation（激活只注入上下文，工具调用仍走权限模式）。
 * catalog 变化时先 unregisterByPrefix(SKILL_COMMAND_PREFIX) 再重建。
 */
export function registerSkillSlashCommands(
  registry: CommandRegistry,
  skills: readonly {
    name: string;
    description: string;
    source: string;
    sha256: string;
    status: "available" | "loaded" | "unavailable";
    invocation?: "model" | "manual" | "both";
    trust_state?: "trusted" | "untrusted";
  }[],
): void {
  registry.unregisterByPrefix(SKILL_COMMAND_PREFIX);
  for (const skill of skills) {
    // 可信 + 可用户调用（manual / both）才生成命令。
    // isSkillTrusted：trust_state 是唯一信任依据，缺失一律视为不可信
    // （fail-closed），不再用 available/loaded 推断 trusted
    // （spec 2026-08-07 §P3 强制规则）。
    if (!isSkillTrusted(skill)) continue;
    const invocation = skill.invocation ?? "both";
    if (invocation === "model") continue;
    const name = skill.name.trim();
    if (!name) continue;
    const id = `${SKILL_COMMAND_PREFIX}${name}`;
    registry.register(
      agent({
        id,
        title: `调用 Skill：${name}`,
        description: skill.description || "加载 Skill 并作为本次任务上下文",
        category: "skills",
        slash: [name],
        usage: `/${name} <task>`,
        available: (ctx) => Boolean(ctx.store.getState().bridgeActive),
        execute: (ctx, args) => {
          const threadId = activeThreadId(ctx);
          if (!threadId) return { ok: false, error: "没有活动会话" };
          const text = String(args.text ?? "").trim();
          if (!text) {
            return { ok: false, error: `需要任务描述（/${name} <task>）` };
          }
          // 携带 skill 名 + 任务文本；后端确定性激活（不绕过权限模式）
          dispatch("electromind:user-input", {
            text,
            delivery: "auto",
            mode: "agent",
            skill: name,
          });
          return { ok: true, message: `已启动 ${name} 任务（Skill 激活注入上下文）` };
        },
      }),
    );
  }
}
