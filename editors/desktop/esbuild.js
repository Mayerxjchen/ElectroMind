const esbuild = require("esbuild");
const fs = require("node:fs");
const path = require("node:path");

const root = __dirname;
const dist = path.join(root, "dist");

/** lucide 等包的 .map 过大/异常时，esbuild 合成 sourcemap 会炸；剥掉引用即可。 */
const ignoreVendorSourceMaps = {
  name: "ignore-vendor-sourcemaps",
  setup(build) {
    build.onLoad(
      { filter: /[/\\]node_modules[/\\].*\.[cm]?js$/ },
      async (args) => {
        const source = await fs.promises.readFile(args.path, "utf8");
        return {
          contents: source.replace(/\n\/\/[#@] sourceMappingURL=.*$/gm, "\n"),
          loader: "js",
        };
      },
    );
  },
};

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
  // 与 docs favicon 相同的 logo，给窗口 / 标签页用。
  fs.copyFileSync(
    path.join(root, "assets", "logo-icon.png"),
    path.join(dist, "logo-icon.png"),
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
  // renderer 复用 ../vscode/src/webview；裸 import 会从 vscode 目录向上找
  // node_modules，这里补上 desktop 自己的依赖目录。
  nodePaths: [path.join(root, "node_modules")],
  sourcemap: true,
  logLevel: "info",
  plugins: [ignoreVendorSourceMaps],
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
