#!/usr/bin/env node
/**
 * Concatenate English docs into llms-full.txt for LLM/agent consumption.
 * Output: docs/public/llms-full.txt (Pages) and repo-root llms-full.txt (raw GitHub).
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const docsDir = path.resolve(__dirname, "..");
const repoRoot = path.resolve(docsDir, "..");

const SOURCES = [
  "agent-reference.md",
  "guide/quick-start.md",
  "guide/providers.md",
  "guide/prompt.md",
  "guide/tools.md",
  "guide/defaults.md",
  "guide/memory.md",
  "events.md",
  "wire.md",
  "reasoning.md",
  "wire-demo.md",
  "development.md",
];

function stripLanguageLine(text) {
  return text.replace(/^(Language:|语言：|言語:).*\n\n?/m, "");
}

const header = `# pagent — full documentation (English)

> Auto-generated for LLM and coding agents. Do not edit by hand.
> Regenerate: \`cd docs && npm run build:llms\`
> Index: https://github.com/SyncLionPaw/pagent/blob/main/llms.txt
> Site: https://synclionpaw.github.io/pagent/

`;

let body = "";
for (const rel of SOURCES) {
  const filePath = path.join(docsDir, rel);
  if (!fs.existsSync(filePath)) {
    console.error(`missing: ${rel}`);
    process.exit(1);
  }
  const raw = fs.readFileSync(filePath, "utf8");
  const content = stripLanguageLine(raw).trim();
  body += `\n\n---\n\n<!-- source: docs/${rel} -->\n\n${content}\n`;
}

const out = header + body;
const publicPath = path.join(docsDir, "public", "llms-full.txt");
const rootPath = path.join(repoRoot, "llms-full.txt");

fs.mkdirSync(path.dirname(publicPath), { recursive: true });
fs.writeFileSync(publicPath, out);
fs.writeFileSync(rootPath, out);
console.log(`wrote ${publicPath}`);
console.log(`wrote ${rootPath}`);
