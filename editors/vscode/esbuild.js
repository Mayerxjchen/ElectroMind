// esbuild 构建脚本。
//
// 插件有两个独立的运行环境，必须分别打包：
//   1) 宿主 (extension.js)：跑在 Node 里，能用 vscode API 和 child_process，
//      所以 external 掉 "vscode"（由 VS Code 运行时注入，不能打进 bundle）。
//   2) 视图 (webview.js)：跑在浏览器式的 Webview 沙箱里，没有 Node，也没有 vscode，
//      只能通过 acquireVsCodeApi() 拿到受限的 postMessage 通道。
//
// 第 1 课只有宿主 bundle；视图 bundle 从第 2 课起启用。

const esbuild = require("esbuild");
const fs = require("node:fs");
const path = require("node:path");

const watch = process.argv.includes("--watch");

// Codicons：VS Code 官方图标字体。webview 不能直接读 node_modules，
// 把字体分发文件（css + ttf）拷进 dist，供 renderHtml 以受限 URI 引用。
// css 里 @font-face 用相对路径 ./codicon.ttf，故两者必须同目录。
function copyCodicons() {
  const src = path.join(__dirname, "node_modules/@vscode/codicons/dist");
  const dest = path.join(__dirname, "dist");
  fs.mkdirSync(dest, { recursive: true });
  for (const file of ["codicon.css", "codicon.ttf"]) {
    fs.copyFileSync(path.join(src, file), path.join(dest, file));
  }
}

/** 宿主：CommonJS，Node 平台，external vscode。 */
const hostOptions = {
  entryPoints: ["src/extension.ts"],
  bundle: true,
  outfile: "dist/extension.js",
  platform: "node",
  format: "cjs",
  target: "node18",
  external: ["vscode"],
  sourcemap: true,
  logLevel: "info",
};

/** 视图：IIFE，浏览器平台，没有 Node/vscode，只跑在 Webview 沙箱里。 */
const webviewOptions = {
  entryPoints: ["src/webview/main.ts"],
  bundle: true,
  outfile: "dist/webview.js",
  platform: "browser",
  format: "iife",
  target: "es2022",
  sourcemap: true,
  logLevel: "info",
};

async function build() {
  copyCodicons();
  if (watch) {
    const hostCtx = await esbuild.context(hostOptions);
    const webviewCtx = await esbuild.context(webviewOptions);
    await Promise.all([hostCtx.watch(), webviewCtx.watch()]);
    console.log("[esbuild] watching host + webview bundles...");
    return;
  }
  await Promise.all([
    esbuild.build(hostOptions),
    esbuild.build(webviewOptions),
  ]);
}

build().catch((err) => {
  console.error(err);
  process.exit(1);
});
