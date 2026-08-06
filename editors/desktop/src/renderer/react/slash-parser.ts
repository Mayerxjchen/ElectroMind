/** Slash 解析 —— P2（Claude Code 语义，修订版文档 §6）。
 *
 * 只有**消息开头**的 `/` 才识别为命令：
 *   /plan 检查当前 CP2K 输入   → 命令（name=plan）
 *   请解释 /plan 的作用         → 普通消息
 *
 * 参数引号感知（支持双/单引号与反斜杠转义）：
 *   /rename "我的 任务" → tokens = ["我的 任务"]
 *   /validate out.out auto → tokens = ["out.out", "auto"]
 */

export type SlashParseResult =
  | { kind: "message" }
  | { kind: "command"; name: string; rawArgs: string; tokens: string[] };

/** 解析输入框文本：不以 / 开头 → 普通消息；以 / 开头 → 命令。 */
export function parseSlashInput(text: string): SlashParseResult {
  if (!text.startsWith("/")) {
    return { kind: "message" };
  }
  const rest = text.slice(1);
  const nameMatch = rest.match(/^\S*/);
  const name = nameMatch ? nameMatch[0] : "";
  const rawArgs = rest.slice(name.length).trim();
  return { kind: "command", name, rawArgs, tokens: tokenizeArgs(rawArgs) };
}

/** 引号感知分词："" / '' / 反斜杠转义；未闭合引号按原样并入末尾 token。 */
export function tokenizeArgs(raw: string): string[] {
  const tokens: string[] = [];
  let current = "";
  let quote: "'" | '"' | null = null;
  let i = 0;
  while (i < raw.length) {
    const ch = raw[i];
    if (quote !== null) {
      if (ch === "\\" && i + 1 < raw.length && (raw[i + 1] === quote || raw[i + 1] === "\\")) {
        current += raw[i + 1];
        i += 2;
        continue;
      }
      if (ch === quote) {
        quote = null;
        i += 1;
        continue;
      }
      current += ch;
      i += 1;
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      i += 1;
      continue;
    }
    if (ch === "\\" && i + 1 < raw.length) {
      current += raw[i + 1];
      i += 2;
      continue;
    }
    if (/\s/.test(ch)) {
      if (current) {
        tokens.push(current);
        current = "";
      }
      i += 1;
      continue;
    }
    current += ch;
    i += 1;
  }
  // 未闭合引号：引号后的内容已在 current 中累积，原样并入即可
  if (current) {
    tokens.push(current);
  }
  return tokens;
}
