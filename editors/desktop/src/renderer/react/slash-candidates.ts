/** Slash 候选与参数映射 —— P2 纯逻辑（可单测）。
 *
 * 候选规则（Claude Code 语义）：别名前缀匹配（/sk → /skills /skill-info）；
 * 只列出 availability 通过的命令。Tab 补全 = 把当前输入的命令名替换为
 * 选中命令的第一个别名。
 */

import type { CommandSpec, ParsedArgs } from "./command-registry";

/** 按输入的命令名前缀过滤可用的 slash 命令。 */
export function slashCandidates(
  commands: readonly CommandSpec[],
  namePart: string,
  isAvailable: (spec: CommandSpec) => boolean,
): CommandSpec[] {
  const q = namePart.toLowerCase();
  return commands
    .filter((c) => (c.slash?.length ?? 0) > 0)
    .filter((c) => !q || c.slash!.some((alias) => alias.toLowerCase().startsWith(q)))
    .filter(isAvailable);
}

/** Tab 补全：返回 "/" + 选中命令的第一个别名。 */
export function completeSlash(spec: CommandSpec): string {
  const alias = spec.slash?.[0] ?? spec.id;
  return `/${alias}`;
}

/**
 * Slash 参数 tokens → 命令 args（按命令各自的约定）。
 * 未知命令 id 给默认 { text: joined }。
 */
export function tokensToArgs(commandId: string, tokens: string[]): ParsedArgs {
  const joined = tokens.join(" ");
  switch (commandId) {
    case "permissions.set":
      return { level: tokens[0] ?? "" };
    case "model.set":
      return { model: tokens[0] ?? "" };
    case "skills.info":
      return { name: tokens[0] ?? "" };
    case "artifact.validate":
      return { artifact_id: tokens[0] ?? "", parser: tokens[1] ?? "" };
    case "thread.new":
    case "thread.rename":
      return { title: joined };
    case "reconcile":
    case "collect":
      return { job_id: tokens[0] ?? "" };
    case "target.show":
      return { target: tokens[0] ?? "" };
    case "thread.compact":
      return { focus: tokens[0] ?? "" };
    default:
      return { text: joined, tokens };
  }
}
