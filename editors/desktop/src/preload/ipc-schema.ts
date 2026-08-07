/** 验收六：IPC 参数运行时 Schema 校验（纯逻辑模块，无 electron 依赖，
 *  可被 node --test 直接 bundle 测试）。
 *
 * 每个带参通道声明位置参数的类型 shape；不匹配直接拒绝（TypeError），
 * 不让脏参数进主进程。
 * 类型 token："string" | "boolean" | "object" | "any"（不校验深结构），
 * 尾部 "?" 表示可选（缺省或该类型均可）。
 */

export type ParamShape = Array<
  | "string"
  | "boolean"
  | "object"
  | "any"
  | "string?"
  | "boolean?"
  | "object?"
>;

export const IPC_PARAM_SHAPES: Record<string, ParamShape> = {
  "desktop:set-yolo-mode": ["boolean"],
  "desktop:get-features": [],
  "desktop:get-thread-meta": ["string"],
  "desktop:open-artifact": ["string"],
  "desktop:read-artifact": ["string"],
  "desktop:pick-directory": ["string?"],
  "desktop:save-provider-setup": ["object"],
  "desktop:complete-onboarding": ["object"],
  "desktop:resume-thread": ["string"],
  "desktop:delete-thread": ["string"],
  "desktop:send-user-input": ["string", "string?", "string?", "string?", "string?", "string?"],
  "desktop:reset-session": ["object?"],
  "desktop:send-wire-command": ["object"],
  "desktop:permit-tool-call": ["object"],
  "desktop:deny-tool-call": ["object"],
  "desktop:get-file-metadata": ["object"],
  "desktop:preview-file": ["object"],
  "desktop:copy-file-path": ["object", "string"],
  "desktop:export-file": ["object", "string?"],
  "desktop:reveal-in-finder": ["object"],
};

export function validateIpcParams(channel: string, args: unknown[]): void {
  const shape = IPC_PARAM_SHAPES[channel];
  if (!shape) {
    // 未声明 shape 的通道视为无参通道；有实参 → 拒绝
    if (args.length > 0) {
      throw new TypeError(`IPC ${channel}: 未声明参数 shape，禁止传参`);
    }
    return;
  }
  if (args.length > shape.length) {
    throw new TypeError(`IPC ${channel}: 参数过多（${args.length} > ${shape.length}）`);
  }
  for (let i = 0; i < shape.length; i++) {
    const expected = shape[i];
    const actual = args[i];
    if (expected === "any") {
      continue;
    }
    const optional = expected.endsWith("?");
    const base = optional ? expected.slice(0, -1) : expected;
    if (actual === undefined) {
      if (!optional) {
        throw new TypeError(`IPC ${channel} 参数 ${i} 应为 ${base}，实际缺省`);
      }
      continue;
    }
    if (typeof actual !== base) {
      throw new TypeError(`IPC ${channel} 参数 ${i} 应为 ${base}，实际 ${typeof actual}`);
    }
  }
}
