#!/usr/bin/env node
// 跨平台打包脚本：在 macOS / Windows / Linux 各自的机器上运行，
// 产出对应平台的桌面端安装包。CI 用矩阵在三种云主机上分别调用。
//
// 用法：
//   node scripts/package.js            # 打当前运行平台
//   node scripts/package.js --platform win32 --arch x64
//
// 产物统一落在 release/ 下，命名 electromind-Desktop-<version>-<platform>-<arch>.<ext>。

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
const productName = "electromind Desktop";
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

// electron-packager 产出的目录名，如 "electromind Desktop-darwin-arm64"。
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
    // F1: 生产包只含运行资源 —— 源码/脚本/开发产物/中间文件全部排除，
    // 否则 .venv 符号链接会导致 codesign --deep 失败、包体膨胀数倍。
    asar: true,
    ignore: [
      /\.venv($|\/)/, // 图标生成用的 Python venv（26M+，符号链接）
      /assets\/icon\.iconset($|\/)/, // 图标生成中间目录
      /assets\/generate_icons\.py/,
      /src($|\/)/, // TypeScript 源码不进包（dist 已编译）
      /scripts($|\/)/, // 打包/测试脚本
      /tests($|\/)/,
      /release($|\/)/,
      /\.git($|\/)/,
      /\.gitignore/,
      /README\.md/,
      /tsconfig\.json/,
      /esbuild\.js/,
      /package-lock\.json/,
    ],
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
  const stage = path.join(releaseDir, `electromind-Desktop-${version}-${arch}`);
  const zip = path.join(releaseDir, `electromind-Desktop-${version}-mac-${arch}.zip`);
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
  const zip = path.join(releaseDir, `electromind-Desktop-${version}-win-${arch}.zip`);
  fs.copyFileSync(
    path.join(root, "scripts", "win-open-hint.txt"),
    path.join(stage, "打开说明.txt"),
  );
  archive(stage, zip, "zip");
  return zip;
}

function stageLinux() {
  const stage = packagedDir();
  const tar = path.join(releaseDir, `electromind-Desktop-${version}-linux-${arch}.tar.gz`);
  archive(stage, tar, "tar.gz");
  return tar;
}

// D2/P5.1/P5.2: 嵌入内置 Agent（Standalone 模式，macOS）。
//
// P5.1: Agent 二进制必须显式指定（--agent-bin <path>，或自动发现
// ../../dist/ 下唯一产物）。缺失 / 版本不匹配 / 架构不匹配 → **构建失败**
// （非零退出），绝不带病产出。
// P5.2: 找不到 Agent 时默认**失败**，禁止静默降级为 Companion。
//       显式传 --allow-companion 才允许产出 Companion 包（开发用）。
function embedAgent(appDir, agentBin, allowCompanion, distDir = path.join(root, "..", "..", "dist")) {
  let src = agentBin;
  if (!src) {
    // dist/ 可能不存在（干净 checkout）——按空目录处理，走领域错误
    // （禁止静默降级），不让底层 ENOENT 越过产品语义。
    const candidates = fs.existsSync(distDir)
      ? fs
          .readdirSync(distDir)
          .filter(
            (f) =>
              f.startsWith("electromind-") &&
              !f.endsWith(".whl") &&
              !f.endsWith(".tar.gz") &&
              !f.endsWith(".txt"),
          )
          .map((f) => path.join(distDir, f))
      : [];
    if (candidates.length === 0) {
      if (allowCompanion) {
        console.warn("D2: 未找到 standalone agent，且 --allow-companion 已显式传入 —— 产出 Companion 包");
        return false;
      }
      throw new Error(
        "D2/P5.2: 未找到 standalone agent（dist/electromind-*）。" +
          "请先运行 scripts/build-standalone.sh。禁止静默降级为 Companion。",
      );
    }
    if (candidates.length > 1) {
      throw new Error(
        `D2/P5.1: dist/ 下有多个 agent 候选（${candidates.map((c) => path.basename(c)).join(", ")}）。` +
          "必须用 --agent-bin 显式指定要嵌入的那一个。",
      );
    }
    src = candidates[0];
  }
  if (!fs.existsSync(src)) {
    throw new Error(`D2/P5.1: --agent-bin 指定的 agent 不存在: ${src}`);
  }

  // P5.1: 架构校验 —— 打包架构必须与 agent 二进制一致（macOS arm64 vs x64）。
  const expectedArch = arch; // 打包时的 arch（arm64 | x64）
  const binArch = detectAgentArch(src);
  if (binArch && binArch !== expectedArch) {
    throw new Error(
      `D2/P5.1: agent 二进制架构 ${binArch} 与打包架构 ${expectedArch} 不匹配: ${src}`,
    );
  }

  // .app bundle 在 packagedDir()/<productName>.app/ 之下（packager 输出）。
  const appBundle = path.join(appDir, `${productName}.app`);
  const agentDir = path.join(appBundle, "Contents", "Resources", "agent");
  fs.mkdirSync(agentDir, { recursive: true });
  fs.copyFileSync(src, path.join(agentDir, "electromind"));
  fs.chmodSync(path.join(agentDir, "electromind"), 0o755);
  console.log(`D2: 已嵌入内置 Agent ${path.basename(src)} → Resources/agent/electromind`);
  return true;
}

/** P5.1: 从 ELF/Mach-O 头探测 agent 二进制架构；无法识别返回 null。 */
function detectAgentArch(bin) {
  const fd = fs.openSync(bin, "r");
  try {
    const buf = Buffer.alloc(8);
    fs.readSync(fd, buf, 0, 8, 0);
    const magicBE = buf.readUInt32BE(0);
    const magicLE = buf.readUInt32LE(0);
    // Mach-O (macOS) 同时接受 BE/CIGAM：
    //   MH_MAGIC_64 0xfeedfacf / MH_CIGAM_64 0xcffaedfe
    //   MH_MAGIC    0xfeedface / MH_CIGAM    0xcefaedfe
    const macho64 = magicBE === 0xfeedfacf || magicLE === 0xfeedfacf || magicBE === 0xcffaedfe || magicLE === 0xcffaedfe;
    const macho32 = magicBE === 0xfeedface || magicLE === 0xfeedface || magicBE === 0xcefaedfe || magicLE === 0xcefaedfe;
    if (macho64 || macho32) {
      // CPU_TYPE 字段按文件字节序存储；同时读 LE/BE 覆盖两种编码。
      const cputypeLE = buf.readInt32LE(4);
      const cputypeBE = buf.readInt32BE(4);
      const isArm = [0x0100000c, 0x0c000100].includes(cputypeLE) || [0x0100000c, 0x0c000100].includes(cputypeBE);
      const isX64 = [0x01000007, 0x07000001].includes(cputypeLE) || [0x01000007, 0x07000001].includes(cputypeBE);
      if (isArm) return "arm64";
      if (isX64) return "x64";
      return "unknown";
    }
    // ELF: e_ident starts \x7fELF; e_machine at offset 18 (2 bytes).
    if (buf[0] === 0x7f && buf[1] === 0x45 && buf[2] === 0x4c && buf[3] === 0x46) {
      const machine = Buffer.alloc(2);
      fs.readSync(fd, machine, 0, 2, 18);
      const val = machine.readUInt16LE(0);
      if (val === 0x3e) return "x64"; // EM_X86_64
      if (val === 0xb7) return "arm64"; // EM_AARCH64
      return "unknown";
    }
    return null;
  } finally {
    fs.closeSync(fd);
  }
}

async function main() {
  fs.mkdirSync(releaseDir, { recursive: true });
  const agentBin = arg("agent-bin", "") || process.env.ELECTROMIND_AGENT_BIN || "";
  const allowCompanion = process.argv.includes("--allow-companion");
  await pack();
  if (platform === "darwin") {
    embedAgent(packagedDir(), agentBin, allowCompanion);
  } else {
    // P5.1: 非 macOS 平台暂不嵌入内置 Agent（Windows/Linux 待后续验证）。
    // 同样禁止静默降级：非 macOS 打包就是 Companion 语义，属预期，不算降级。
    console.warn(`D2: ${platform} 平台暂不嵌入内置 Agent（仅 macOS 已验证）`);
  }
  const out =
    platform === "darwin"
      ? stageMac()
      : platform === "win32"
        ? stageWindows()
        : stageLinux();
  process.stdout.write(`wrote ${out}\n`);
}

// P5.1: 允许测试导入模块（不触发打包）。CI 或打包时直接 node scripts/package.js。
if (require.main === module) {
  main().catch((error) => {
    console.error(error);
    process.exit(1);
  });
}

module.exports = { detectAgentArch, embedAgent };
