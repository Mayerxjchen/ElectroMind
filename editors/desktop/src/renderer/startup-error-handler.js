// 启动错误页（P4.5 之后为 textContent，不用 innerHTML——错误信息可能含
// 任意文本，拼接未转义内容有 XSS 风险）。独立成文件以满足严格 CSP
// （script-src 'self'，不允许 inline script）。
window.addEventListener("error", (event) => {
  const root = document.getElementById("app");
  if (!root || root.childElementCount > 0) return;
  const msg = event.error?.stack || event.message || "未知错误";
  const pre = document.createElement("pre");
  pre.style.padding = "16px";
  pre.style.color = "#f8fafc";
  pre.style.whiteSpace = "pre-wrap";
  pre.textContent = msg;
  root.textContent = "";
  root.appendChild(pre);
  document.documentElement.dataset.boot = "done";
  const splash = document.getElementById("boot-splash");
  if (splash) splash.hidden = true;
});
