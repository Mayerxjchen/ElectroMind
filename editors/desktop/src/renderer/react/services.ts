/** Command Services —— P2（spec 2026-08-07 §P2）。
 *
 * 把命令里散落的 `window.dispatchEvent(...)` / `window.desktop.sendWireCommand(...)`
 * 等低级访问器收拢为明确服务：ui / threads / runs / skills / models /
 * inspector / diagnostics。命令只依赖本模块，不直接摸 window。
 *
 * 所有方法在调用时惰性读取 window / ctx.store（测试可先换 globalThis.window
 * 再执行命令，与既有断言模式一致）。
 */

import type { CommandContext } from "./command-registry.ts";
import type { InspectorTab } from "../store/types.ts";
import type { PermitRequest } from "../store/types.ts";
import type { WireCommand } from "../../shared/protocol.ts";

function dispatch(name: string, detail?: unknown): void {
  window.dispatchEvent(new CustomEvent(name, { detail }));
}

function sendWire(payload: WireCommand): boolean {
  if (!window.desktop?.sendWireCommand) return false;
  void window.desktop.sendWireCommand(payload);
  return true;
}

export type CommandServices = {
  /** 纯 UI 打开（Palette / Composer 聚焦 / 快捷键 / Threads 折叠等）。 */
  ui: {
    open(eventName: string): void;
  };
  /** Thread 状态写入（经 store，不绕过单例）。 */
  threads: {
    update(ctx: CommandContext, id: string, patch: Record<string, unknown>): void;
  };
  /** Run 生命周期：发送输入、停止、审批。 */
  runs: {
    send(detail: { text: string; mode?: string; skill?: string }): void;
    stop(): void;
    permit(permit: PermitRequest): void;
    deny(permit: PermitRequest, reason?: string): void;
  };
  /** Skills 领域：面板 / Picker / 管理命令。 */
  skills: {
    openPanel(): void;
    openPicker(): void;
    /** 发送 allowlisted skills wire 命令（sendWireCommand 不可用返回 false）。 */
    wire(payload: WireCommand): boolean;
  };
  /** 通用 allowlisted wire 命令（hpc/submissions、artifact/validate 等）。 */
  wire: {
    send(payload: WireCommand): boolean;
  };
  models: {
    openPicker(): void;
  };
  inspector: {
    open(ctx: CommandContext, tab: InspectorTab): void;
    toggle(ctx: CommandContext): void;
  };
  diagnostics: {
    openLogDir(): boolean;
  };
};

export const commandServices: CommandServices = {
  ui: {
    open(eventName) {
      dispatch(eventName);
    },
  },

  threads: {
    update(ctx, id, patch) {
      ctx.store.updateThread(id, patch as never);
    },
  },

  runs: {
    send(detail) {
      dispatch("electromind:user-input", detail);
    },
    stop() {
      dispatch("electromind:stop");
    },
    permit(permit) {
      void window.desktop.permitToolCall(
        permit.toolCallId,
        permit.approvalId,
        permit.threadId,
        permit.runId,
      );
    },
    deny(permit, reason) {
      void window.desktop.denyToolCall(
        permit.toolCallId,
        reason,
        permit.approvalId,
        permit.threadId,
        permit.runId,
      );
    },
  },

  skills: {
    openPanel() {
      dispatch("electromind:skills-open");
    },
    openPicker() {
      dispatch("electromind:skill-picker-toggle");
    },
    wire(payload) {
      return sendWire(payload);
    },
  },

  wire: {
    send(payload) {
      return sendWire(payload);
    },
  },

  models: {
    openPicker() {
      dispatch("electromind:model-picker-toggle");
    },
  },

  inspector: {
    open(ctx, tab) {
      ctx.store.setInspector({ open: true, activeTab: tab });
    },
    toggle(ctx) {
      const open = ctx.store.getState().inspector.open;
      ctx.store.setInspector({ open: !open });
    },
  },

  diagnostics: {
    openLogDir() {
      if (!window.desktop?.openLogDir) return false;
      void window.desktop.openLogDir();
      return true;
    },
  },
};
