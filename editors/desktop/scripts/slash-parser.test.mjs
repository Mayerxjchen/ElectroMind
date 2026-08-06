/** P2 Slash 解析测试 —— Claude Code 语义（修订版文档 §6 + 测试计划）。
 *
 *  验收：
 *   - 只有消息开头的 / 是命令；"/plan 检查当前 CP2K 输入" 是命令，
 *     "请解释 /plan 的作用" 是普通消息
 *   - 引号、转义与参数解析（测试计划：Slash Parser 的引号、转义和参数）
 *   - 候选前缀过滤（/sk → /skills /skill-info）
 *   - Tab 补全
 *   - tokens → args 映射
 */

import { test } from "node:test";
import assert from "node:assert/strict";

const parser = await import(
  new URL("../src/renderer/react/slash-parser.ts", import.meta.url)
);
const candidates = await import(
  new URL("../src/renderer/react/slash-candidates.ts", import.meta.url)
);

test("parser: only a leading slash is a command", () => {
  assert.deepEqual(parser.parseSlashInput("/plan 检查当前 CP2K 输入"), {
    kind: "command",
    name: "plan",
    rawArgs: "检查当前 CP2K 输入",
    tokens: ["检查当前", "CP2K", "输入"],
  });
  assert.deepEqual(parser.parseSlashInput("请解释 /plan 的作用"), {
    kind: "message",
  });
  assert.deepEqual(parser.parseSlashInput("普通消息 /permissions"), {
    kind: "message",
  });
  assert.deepEqual(parser.parseSlashInput(""), { kind: "message" });
});

test("parser: bare slash and empty name", () => {
  assert.deepEqual(parser.parseSlashInput("/"), {
    kind: "command",
    name: "",
    rawArgs: "",
    tokens: [],
  });
  assert.deepEqual(parser.parseSlashInput("/ "), {
    kind: "command",
    name: "",
    rawArgs: "",
    tokens: [],
  });
});

test("parser: quoted args keep spaces", () => {
  assert.deepEqual(parser.tokenizeArgs('"我的 任务"'), ["我的 任务"]);
  assert.deepEqual(parser.tokenizeArgs("'a b' c"), ["a b", "c"]);
});

test("parser: backslash escapes quote inside quoted token", () => {
  assert.deepEqual(parser.tokenizeArgs('"say \\"hi\\""'), ['say "hi"']);
  assert.deepEqual(parser.tokenizeArgs("a\\ b"), ["a b"]);
});

test("parser: unclosed quote keeps the rest as one token", () => {
  assert.deepEqual(parser.tokenizeArgs('"my title'), ["my title"]);
});

test("parser: full slash parse with quoted arg", () => {
  assert.deepEqual(parser.parseSlashInput('/rename "我的 任务"'), {
    kind: "command",
    name: "rename",
    rawArgs: '"我的 任务"',
    tokens: ["我的 任务"],
  });
});

test("candidates: prefix filter matches slash aliases", () => {
  const commands = [
    { id: "a", slash: ["skills"], title: "Skills" },
    { id: "b", slash: ["skill-info"], title: "Skill Info" },
    { id: "c", slash: ["plan"], title: "Plan" },
    { id: "d", slash: [], title: "no slash" },
  ];
  const avail = () => true;
  const hit = (q) =>
    candidates.slashCandidates(commands, q, avail).map((c) => c.id);
  assert.deepEqual(hit("sk"), ["a", "b"], "/sk → /skills /skill-info");
  assert.deepEqual(hit("s"), ["a", "b"], "部分前缀");
  assert.deepEqual(hit(""), ["a", "b", "c"], "空前缀列出全部 slash 命令");
  assert.deepEqual(hit("x"), [], "无匹配");
});

test("candidates: availability filters", () => {
  const commands = [
    { id: "a", slash: ["doctor"], title: "Doctor" },
    { id: "b", slash: ["status"], title: "Status" },
  ];
  const hit = candidates.slashCandidates(commands, "", (spec) => spec.id === "b");
  assert.deepEqual(hit.map((c) => c.id), ["b"]);
});

test("candidates: Tab completion returns /<first alias>", () => {
  const spec = { id: "x", slash: ["skill-info", "si"], title: "X" };
  assert.equal(candidates.completeSlash(spec), "/skill-info");
});

test("candidates: tokensToArgs maps per command convention", () => {
  assert.deepEqual(candidates.tokensToArgs("permissions.set", ["safe"]), {
    level: "safe",
  });
  assert.deepEqual(candidates.tokensToArgs("model.set", ["auto"]), {
    model: "auto",
  });
  assert.deepEqual(candidates.tokensToArgs("agent.ask", ["跑", "CP2K"]), {
    text: "跑 CP2K",
    tokens: ["跑", "CP2K"],
  });
  assert.deepEqual(candidates.tokensToArgs("artifact.validate", ["a1", "cp2k"]), {
    artifact_id: "a1",
    parser: "cp2k",
  });
  assert.deepEqual(candidates.tokensToArgs("thread.new", ["我的", "任务"]), {
    title: "我的 任务",
  });
  assert.deepEqual(candidates.tokensToArgs("reconcile", ["3521223"]), {
    job_id: "3521223",
  });
});
