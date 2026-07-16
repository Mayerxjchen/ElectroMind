const esbuild = require("esbuild");
const fs = require("node:fs");
const path = require("node:path");

const root = __dirname;
const dist = path.join(root, "dist");

function copyRendererAssets() {
  fs.mkdirSync(dist, { recursive: true });
  for (const file of ["index.html", "style.css"]) {
    fs.copyFileSync(
      path.join(root, "src", "renderer", file),
      path.join(dist, file),
    );
  }
  fs.copyFileSync(
    path.join(root, "..", "vscode", "media", "style.css"),
    path.join(dist, "chat.css"),
  );
}

function copyCodicons() {
  const src = path.join(root, "node_modules", "@vscode", "codicons", "dist");
  fs.mkdirSync(dist, { recursive: true });
  for (const file of ["codicon.css", "codicon.ttf"]) {
    fs.copyFileSync(path.join(src, file), path.join(dist, file));
  }
}

const mainOptions = {
  entryPoints: ["src/main/index.ts"],
  bundle: true,
  outfile: "dist/main.js",
  platform: "node",
  format: "cjs",
  target: "node20",
  external: ["electron"],
  sourcemap: true,
  logLevel: "info",
};

const preloadOptions = {
  entryPoints: ["src/preload/index.ts"],
  bundle: true,
  outfile: "dist/preload.js",
  platform: "node",
  format: "cjs",
  target: "node20",
  external: ["electron"],
  sourcemap: true,
  logLevel: "info",
};

const rendererOptions = {
  entryPoints: ["src/renderer/main.ts"],
  bundle: true,
  outfile: "dist/renderer.js",
  platform: "browser",
  format: "iife",
  target: "chrome128",
  sourcemap: true,
  logLevel: "info",
};

async function build() {
  copyRendererAssets();
  copyCodicons();
  await Promise.all([
    esbuild.build(mainOptions),
    esbuild.build(preloadOptions),
    esbuild.build(rendererOptions),
  ]);
}

build().catch((error) => {
  console.error(error);
  process.exit(1);
});
