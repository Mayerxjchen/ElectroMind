/** 统一 Command Registry —— P1（修订版文档 §5）。
 *
 * 所有命令入口（Slash Menu / Command Palette / 快捷键 / 菜单 / 右键菜单 /
 * 帮助页面）调用**同一个** Registry，保证状态一致：快捷键切的模式就是
 * Slash 切的模式，不会出现"快捷键能切模式但下拉框状态没更新"。
 *
 * 三类命令：
 *   - ui:           不经过 LLM、不创建 Run（/help /status /model …）
 *   - deterministic:调用后端结构化接口，不让模型猜测（/doctor /reconcile …）
 *   - agent:        启动或排队 Agent Run（/ask /plan /agent …）
 *
 * 纯模块（无 DOM / React 依赖；仅 type-only 导入）—— 单元测试可直接跑。
 * 单例经 window.__electromindCommandRegistry 暴露，vanilla keydown 与
 * React 面板共用同一实例。
 */

import type { ThreadStore } from "../store/ThreadStore";

// ── 类型 ────────────────────────────────────────────────────────────

export type CommandKind = "ui" | "deterministic" | "agent";

/** 分类（Palette 分组；文档：Thread/Mode/Permissions/Execution/Skills/
 *  View/Diagnostics/Developer）。 */
export type CommandCategory =
  | "thread"
  | "mode"
  | "permissions"
  | "execution"
  | "skills"
  | "view"
  | "diagnostics"
  | "developer";

export type ParsedArgs = Record<string, unknown>;

export type CommandResult =
  | { ok: true; message?: string }
  | { ok: false; error: string };

/** 命令执行上下文 —— 两个 bundle 共用：store 单例 + SessionManager。
 *  命令实现内部通过 window / window.desktop / 事件桥访问其余能力。 */
export interface CommandContext {
  store: ThreadStore;
  sessionManager?: unknown;
}

export interface CommandSpec {
  id: string;
  title: string;
  description: string;
  category: CommandCategory;
  kind: CommandKind;
  /** Slash 别名（不含前导 /；同一命令可多个别名）。 */
  slash?: string[];
  /** 快捷键串（"meta+k" / "meta+shift+enter" / "escape"）。 */
  shortcut?: string;
  /** 用法说明（如 "/model auto|fast|balanced|best|<model-id>"）。 */
  usage?: string;
  /** 是否可用 —— 取决于当前状态与环境（无后端 / 无活动 Thread 等）。 */
  available: (ctx: CommandContext) => boolean;
  execute: (
    ctx: CommandContext,
    args: ParsedArgs,
  ) => Promise<CommandResult> | CommandResult;
}

export interface ShortcutBinding {
  id: string;
  spec: CommandSpec;
}

// ── Registry ────────────────────────────────────────────────────────

export class CommandRegistry {
  private readonly commands = new Map<string, CommandSpec>();
  private readonly slashIndex = new Map<string, string>();
  private readonly shortcutIndex = new Map<string, string>();

  /** 注册命令。id / slash / shortcut 重复即抛错 —— 注册期冲突是编程错误。 */
  register(spec: CommandSpec): void {
    if (this.commands.has(spec.id)) {
      throw new Error(`命令重复注册: ${spec.id}`);
    }
    for (const alias of spec.slash ?? []) {
      const aliasKey = alias.toLowerCase();
      if (this.slashIndex.has(aliasKey)) {
        throw new Error(
          `Slash 别名冲突: /${alias} 已被 ${this.slashIndex.get(aliasKey)} 占用`,
        );
      }
    }
    if (spec.shortcut) {
      const key = spec.shortcut.toLowerCase();
      if (this.shortcutIndex.has(key)) {
        throw new Error(
          `快捷键冲突: ${spec.shortcut} 已被 ${this.shortcutIndex.get(key)} 占用`,
        );
      }
      this.shortcutIndex.set(key, spec.id);
    }
    for (const alias of spec.slash ?? []) {
      this.slashIndex.set(alias.toLowerCase(), spec.id);
    }
    this.commands.set(spec.id, spec);
  }

  get(id: string): CommandSpec | undefined {
    return this.commands.get(id);
  }

  /** 注销命令（动态命令集刷新用 —— P4 Skill 命令按 catalog 重建）。
   *  同步清理 slash / shortcut 索引。 */
  unregister(id: string): void {
    const spec = this.commands.get(id);
    if (!spec) return;
    for (const alias of spec.slash ?? []) {
      if (this.slashIndex.get(alias.toLowerCase()) === id) {
        this.slashIndex.delete(alias.toLowerCase());
      }
    }
    if (spec.shortcut) {
      const key = spec.shortcut.toLowerCase();
      if (this.shortcutIndex.get(key) === id) {
        this.shortcutIndex.delete(key);
      }
    }
    this.commands.delete(id);
  }

  /** 按 id 前缀注销（如 "skill."）。 */
  unregisterByPrefix(prefix: string): void {
    for (const id of [...this.commands.keys()]) {
      if (id.startsWith(prefix)) {
        this.unregister(id);
      }
    }
  }

  all(): CommandSpec[] {
    return [...this.commands.values()];
  }

  byCategory(): Map<CommandCategory, CommandSpec[]> {
    const map = new Map<CommandCategory, CommandSpec[]>();
    for (const spec of this.commands.values()) {
      const list = map.get(spec.category) ?? [];
      list.push(spec);
      map.set(spec.category, list);
    }
    return map;
  }

  /** 按 id / 标题 / 描述 / slash / usage 过滤。 */
  search(query: string): CommandSpec[] {
    const q = query.trim().toLowerCase();
    if (!q) return this.all();
    return this.all().filter((spec) =>
      [spec.id, spec.title, spec.description, spec.usage ?? "", ...(spec.slash ?? []).map((s) => `/${s}`)]
        .join(" ")
        .toLowerCase()
        .includes(q),
    );
  }

  /** 查快捷键 → 命令（keydown 处理用）。 */
  shortcutBinding(shortcut: string): ShortcutBinding | undefined {
    const id = this.shortcutIndex.get(shortcut.toLowerCase());
    if (!id) return undefined;
    const spec = this.commands.get(id);
    return spec ? { id, spec } : undefined;
  }

  /** Slash 别名 → 命令（P2 Slash 菜单用）。 */
  commandForSlash(alias: string): CommandSpec | undefined {
    const id = this.slashIndex.get(alias.toLowerCase());
    return id ? this.commands.get(id) : undefined;
  }

  isAvailable(id: string, ctx: CommandContext): boolean {
    const spec = this.commands.get(id);
    if (!spec) return false;
    try {
      return spec.available(ctx);
    } catch {
      return false;
    }
  }

  async execute(
    id: string,
    ctx: CommandContext,
    args: ParsedArgs = {},
  ): Promise<CommandResult> {
    const spec = this.commands.get(id);
    if (!spec) {
      return { ok: false, error: `未知命令: ${id}` };
    }
    if (!this.isAvailable(id, ctx)) {
      return { ok: false, error: `命令当前不可用: ${id}` };
    }
    try {
      return await spec.execute(ctx, args);
    } catch (e) {
      return {
        ok: false,
        error: `命令执行失败: ${e instanceof Error ? e.message : String(e)}`,
      };
    }
  }

  get size(): number {
    return this.commands.size;
  }
}

// ── 单例（跨 bundle 共享：entry.tsx 暴露到 window） ─────────────────

let instance: CommandRegistry | null = null;

/** 进程内单例 —— 与 ThreadStore 相同的模式。测试用 reset 重建。 */
export function getCommandRegistry(): CommandRegistry {
  if (!instance) {
    instance = new CommandRegistry();
  }
  return instance;
}

export function resetCommandRegistry(): void {
  instance = null;
}
