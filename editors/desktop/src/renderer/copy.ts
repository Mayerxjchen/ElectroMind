/** Clipboard utilities and ToolCard renderer for actionable messages.
 *
 * - ``copyToClipboard(text)`` writes text to the system clipboard.
 * - ``installCopyButtons(container)`` adds copy buttons to every
 *   ``<pre><code>`` block inside *container*.
 * - ``renderToolCard(data)`` builds a DOM element for a tool call result.
 */

// ── Clipboard ────────────────────────────────────────────────────────

export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Fallback for older browsers / Electron without clipboard permission
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.left = "-9999px";
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand("copy");
      return true;
    } catch {
      return false;
    } finally {
      document.body.removeChild(ta);
    }
  }
}

// ── Code block copy buttons ──────────────────────────────────────────

export function installCopyButtons(container: HTMLElement): void {
  for (const pre of container.querySelectorAll("pre")) {
    if (pre.querySelector(".copy-btn")) continue; // already installed
    const code = pre.querySelector("code");
    if (!code) continue;

    const btn = document.createElement("button");
    btn.className = "copy-btn";
    btn.title = "复制代码";
    btn.innerHTML = "⎘";
    btn.addEventListener("click", async () => {
      const ok = await copyToClipboard(code.textContent ?? "");
      btn.innerHTML = ok ? "✓" : "✗";
      btn.classList.add(ok ? "copied" : "failed");
      setTimeout(() => {
        btn.innerHTML = "⎘";
        btn.classList.remove("copied", "failed");
      }, 1500);
    });
    pre.style.position = "relative";
    pre.appendChild(btn);
  }
}

// ── Assistant message action bar ─────────────────────────────────────

export function installMessageActions(container: HTMLElement): void {
  for (const msg of container.querySelectorAll(".assistant-message")) {
    if (msg.querySelector(".msg-actions")) continue;

    const bar = document.createElement("div");
    bar.className = "msg-actions";

    const copyBtn = document.createElement("button");
    copyBtn.className = "msg-action-btn";
    copyBtn.title = "复制";
    copyBtn.textContent = "复制";
    copyBtn.addEventListener("click", async () => {
      const ok = await copyToClipboard((msg as HTMLElement).innerText);
      copyBtn.textContent = ok ? "已复制" : "失败";
      setTimeout(() => { copyBtn.textContent = "复制"; }, 1500);
    });
    bar.appendChild(copyBtn);

    msg.appendChild(bar);
  }
}

// ── Tool card renderer ───────────────────────────────────────────────

export interface ToolCardData {
  tool: string;
  target?: string;     // e.g. "SSH · cpu-cluster"
  cwd?: string;        // working directory
  status: "ok" | "error" | "timeout" | "running";
  exitCode?: number;
  elapsedMs?: number;
  command?: string;
  stdout?: string;     // truncated preview
  fullLogAvailable?: boolean;
}

export function renderToolCard(data: ToolCardData): HTMLElement {
  const card = document.createElement("div");
  card.className = `tool-card tool-card-${data.status}`;

  // Header
  const header = document.createElement("div");
  header.className = "tool-card-header";

  const info = document.createElement("div");
  info.className = "tool-card-info";

  const toolName = document.createElement("span");
  toolName.className = "tool-card-name";
  toolName.textContent = data.tool;
  info.appendChild(toolName);

  if (data.target) {
    const target = document.createElement("span");
    target.className = "tool-card-target";
    target.textContent = data.target;
    info.appendChild(target);
  }
  if (data.cwd) {
    const cwd = document.createElement("span");
    cwd.className = "tool-card-cwd";
    cwd.textContent = data.cwd;
    info.appendChild(cwd);
  }

  header.appendChild(info);

  // Status badge
  const badge = document.createElement("span");
  badge.className = `tool-card-badge ${data.status}`;
  const parts: string[] = [];
  if (data.exitCode !== undefined) parts.push(`退出 ${data.exitCode}`);
  if (data.elapsedMs !== undefined) {
    parts.push(`${(data.elapsedMs / 1000).toFixed(1)}s`);
  }
  badge.textContent = parts.join(" · ") || data.status;
  header.appendChild(badge);

  card.appendChild(header);

  // Command
  if (data.command) {
    const cmd = document.createElement("pre");
    cmd.className = "tool-card-command";
    const code = document.createElement("code");
    code.textContent = data.command;
    cmd.appendChild(code);

    const copyCmd = document.createElement("button");
    copyCmd.className = "copy-btn tool-card-copy";
    copyCmd.title = "复制命令";
    copyCmd.innerHTML = "⎘";
    copyCmd.addEventListener("click", async () => {
      const ok = await copyToClipboard(data.command!);
      copyCmd.innerHTML = ok ? "✓" : "✗";
      setTimeout(() => { copyCmd.innerHTML = "⎘"; }, 1500);
    });
    cmd.appendChild(copyCmd);
    card.appendChild(cmd);
  }

  // Output
  if (data.stdout) {
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = data.fullLogAvailable ? "展开完整输出" : "展开输出";
    details.appendChild(summary);

    const out = document.createElement("pre");
    out.className = "tool-card-output";
    out.textContent = data.stdout;
    details.appendChild(out);

    card.appendChild(details);
  }

  return card;
}
