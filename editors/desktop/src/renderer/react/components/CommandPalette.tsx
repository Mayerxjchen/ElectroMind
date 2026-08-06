/** Command Palette —— P1：所有操作的统一入口（Cmd+K）。
 *
 * 从同一个 CommandRegistry 读取命令（可用性过滤 + 分类分组 + 搜索），
 * 执行也走同一个 Registry —— 与快捷键 / Slash 共享同一份命令定义。
 *
 * 打开方式：registry 的 palette.open 命令（dispatch electromind:palette-toggle）
 * 或本组件自监听该事件。Esc 关闭；Enter 执行选中项。
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  getCommandRegistry,
  type CommandCategory,
  type CommandSpec,
} from "../command-registry";
import { sharedThreadStore } from "../useStore";

const CATEGORY_LABELS: Record<CommandCategory, string> = {
  thread: "Thread",
  mode: "Mode",
  permissions: "Permissions",
  execution: "Execution",
  skills: "Skills",
  view: "View",
  diagnostics: "Diagnostics",
  developer: "Developer",
};

const CATEGORY_ORDER: CommandCategory[] = [
  "thread",
  "mode",
  "permissions",
  "execution",
  "skills",
  "view",
  "diagnostics",
  "developer",
];

/** 展示快捷键串 → 键位符号。 */
function shortcutLabel(shortcut: string): string {
  const parts = shortcut.split("+").map((p) => {
    switch (p) {
      case "meta":
        return "⌘";
      case "shift":
        return "⇧";
      case "escape":
        return "Esc";
      case "enter":
        return "Enter";
      case "space":
        return "Space";
      default:
        return p.toUpperCase();
    }
  });
  return parts.join(" ");
}

export const CommandPalette: React.FC = () => {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onToggle = () => setOpen((v) => !v);
    window.addEventListener("electromind:palette-toggle", onToggle);
    return () => window.removeEventListener("electromind:palette-toggle", onToggle);
  }, []);

  // 打开时清空查询并聚焦
  useEffect(() => {
    if (open) {
      setQuery("");
      setSelected(0);
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  // 可用命令（可用性由 registry 统一判断）+ 搜索过滤
  const results = useMemo(() => {
    const ctx = {
      store: sharedThreadStore(),
      sessionManager: (window as unknown as Record<string, unknown>).__electromindSM,
    };
    const registry = getCommandRegistry();
    const candidates = registry
      .search(query)
      .filter((spec) => registry.isAvailable(spec.id, ctx));
    // 按分类排序（保持分类内注册顺序）
    const byCat = new Map<CommandCategory, CommandSpec[]>();
    for (const spec of candidates) {
      const list = byCat.get(spec.category) ?? [];
      list.push(spec);
      byCat.set(spec.category, list);
    }
    return CATEGORY_ORDER.filter((c) => byCat.has(c)).map((c) => ({
      category: c,
      commands: byCat.get(c)!,
    }));
  }, [query, open]);

  // 展平列表用于键盘导航
  const flat = useMemo(
    () => results.flatMap((g) => g.commands),
    [results],
  );

  useEffect(() => {
    setSelected((s) => Math.min(s, Math.max(0, flat.length - 1)));
  }, [flat.length]);

  // 选中项滚入视口
  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>(".command-palette-item.active");
    el?.scrollIntoView({ block: "nearest" });
  }, [selected]);

  const runCommand = useCallback(
    (spec: CommandSpec) => {
      const ctx = {
        store: sharedThreadStore(),
        sessionManager: (window as unknown as Record<string, unknown>).__electromindSM,
      };
      void getCommandRegistry().execute(spec.id, ctx, {});
      setOpen(false);
    },
    [],
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        setOpen(false);
        return;
      }
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelected((s) => Math.min(s + 1, Math.max(0, flat.length - 1)));
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelected((s) => Math.max(s - 1, 0));
        return;
      }
      if (e.key === "Enter") {
        e.preventDefault();
        const spec = flat[selected];
        if (spec) runCommand(spec);
        return;
      }
    },
    [flat, selected, runCommand],
  );

  if (!open) return null;

  return (
    <div className="command-palette" role="dialog" aria-modal="true" aria-label="Command Palette">
      <div className="command-palette-backdrop" onClick={() => setOpen(false)} />
      <div className="command-palette-card">
        <div className="command-palette-input-row">
          <span className="command-palette-prefix" aria-hidden="true">›</span>
          <input
            ref={inputRef}
            className="command-palette-input"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSelected(0);
            }}
            onKeyDown={handleKeyDown}
            placeholder="搜索所有操作…"
            spellCheck={false}
          />
        </div>
        <div className="command-palette-results" ref={listRef}>
          {flat.length === 0 && (
            <div className="command-palette-empty">没有匹配的操作</div>
          )}
          {results.map((group) => (
            <div key={group.category} className="command-palette-group">
              <div className="command-palette-group-label">
                {CATEGORY_LABELS[group.category]}
              </div>
              {group.commands.map((spec) => {
                const idx = flat.indexOf(spec);
                return (
                  <button
                    key={spec.id}
                    type="button"
                    className={`command-palette-item ${idx === selected ? "active" : ""}`}
                    onMouseEnter={() => setSelected(idx)}
                    onClick={() => runCommand(spec)}
                  >
                    <span className="command-palette-item-title">{spec.title}</span>
                    <span className="command-palette-item-desc">{spec.description}</span>
                    {spec.shortcut ? (
                      <span className="command-palette-item-keys">
                        {shortcutLabel(spec.shortcut)}
                      </span>
                    ) : null}
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
