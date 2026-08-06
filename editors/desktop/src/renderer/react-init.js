// React shell 初始化（P4.6 混合架构）：vanilla renderer 挂载后，把活的
// SessionManager 交给 React 侧，使 Thread 操作不是 no-op。轮询直到 bundle
// 定义了入口——慢加载 / reload 时求值可能延迟，错过一次调用会让 React UI
// 永远不挂载。独立成文件以满足严格 CSP。
(function initReactShell() {
  if (typeof window.__initReactShell__ === "function") {
    window.__initReactShell__(window.__electromindSM);
    return;
  }
  setTimeout(initReactShell, 100);
})();
