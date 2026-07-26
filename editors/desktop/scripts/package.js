#!/usr/bin/env node
// 跨平台打包脚本：在 macOS / Windows / Linux 各自的机器上运行，
// 产出对应平台的桌面端安装包。CI 用矩阵在三种云主机上分别调用。
//
// 用法：
//   node scripts/package.js            # 打当前运行平台
//   node scripts/package.js --platform win32 --arch x64
//
// 产物统一落在 release/ 下，命名 pagent-Desktop-<version>-<platform>-<arch>.<ext>。

const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const { packager } = require("@electron/packager");

const root = path.resolve(__dirname, "..");
process.chdir(root);

function arg(name, fallback) {
  const idx = process.argv.indexOf(`--${name}`);
  return idx >= 0 && process.argv[idx + 1] ? process.argv[idx + 1] : fallback;
}

const platform = arg("platform", process.platform); // darwin | win32 | linux
const arch = arg("arch", process.arch); // arm64 | x64
const version = require(path.join(root, "package.json")).version;
const productName = "pagent Desktop";
const releaseDir = path.join(root, "release");

// 每个平台的图标与最终分发格式。
const iconByPlatform = {
  darwin: path.join(root, "assets", "icon.icns"),
  win32: path.join(root, "assets", "icon.ico"),
  linux: path.join(root, "assets", "app-icon.png"),
};

function run(cmd, args, opts = {}) {
  execFileSync(cmd, args, { stdio: "inherit", ...opts });
}

function rmrf(target) {
  fs.rmSync(target, { recursive: true, force: true });
}

// electron-packager 产出的目录名，如 "pagent Desktop-darwin-arm64"。
function packagedDir() {
  return path.join(releaseDir, `${productName}-${platform}-${arch}`);
}

function pack() {
  run("node", ["esbuild.js"]);
  return packager({
    dir: ".",
    name: productName,
    platform,
    arch,
    out: "release",
    overwrite: true,
    icon: iconByPlatform[platform],
    appVersion: version,
  });
}

// 把目录压成分发包。zip 用于 mac/win，tar.gz 用于 linux。
function archive(stageDir, outFile, kind) {
  rmrf(outFile);
  if (kind === "tar.gz") {
    run("tar", ["-czf", outFile, "-C", releaseDir, path.basename(stageDir)]);
    return;
  }
  // zip：mac 用 ditto 保留资源分叉与符号链接，其它平台用 zip / powershell。
  if (process.platform === "darwin") {
    run("ditto", ["-c", "-k", "--sequesterRsrc", "--keepParent", stageDir, outFile]);
  } else if (process.platform === "win32") {
    run("powershell", [
      "-NoProfile",
      "-Command",
      `Compress-Archive -Path '${stageDir}\\*' -DestinationPath '${outFile}' -Force`,
    ]);
  } else {
    run("zip", ["-r", "-q", outFile, path.basename(stageDir)], { cwd: releaseDir });
  }
}

function stageMac() {
  const app = path.join(packagedDir(), `${productName}.app`);
  const stage = path.join(releaseDir, `pagent-Desktop-${version}-${arch}`);
  const zip = path.join(releaseDir, `pagent-Desktop-${version}-mac-${arch}.zip`);
  rmrf(stage);
  fs.mkdirSync(stage, { recursive: true });
  run("cp", ["-R", app, stage]);
  fs.copyFileSync(
    path.join(root, "scripts", "mac-open-hint.txt"),
    path.join(stage, "打开说明.txt"),
  );
  // 无 Apple 开发者证书时只能 ad-hoc 签名；用户下载后仍可能需要 xattr -cr 去隔离标记。
  run("codesign", ["--force", "--deep", "--sign", "-", path.join(stage, `${productName}.app`)]);
  archive(stage, zip, "zip");
  return zip;
}

function stageWindows() {
  const stage = packagedDir(); // 直接压 electron-packager 的输出目录
  const zip = path.join(releaseDir, `pagent-Desktop-${version}-win-${arch}.zip`);
  fs.copyFileSync(
    path.join(root, "scripts", "win-open-hint.txt"),
    path.join(stage, "打开说明.txt"),
  );
  archive(stage, zip, "zip");
  return zip;
}

function stageLinux() {
  const stage = packagedDir();
  const tar = path.join(releaseDir, `pagent-Desktop-${version}-linux-${arch}.tar.gz`);
  archive(stage, tar, "tar.gz");
  return tar;
}

async function main() {
  fs.mkdirSync(releaseDir, { recursive: true });
  await pack();
  const out =
    platform === "darwin"
      ? stageMac()
      : platform === "win32"
        ? stageWindows()
        : stageLinux();
  process.stdout.write(`wrote ${out}\n`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
