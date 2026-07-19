import { defineConfig } from "vitepress";
import { withMermaid } from "vitepress-plugin-mermaid";

const github = "https://github.com/SyncLionPaw/pagent";
const site = "https://synclionpaw.github.io/pagent";
const base = "/pagent/";

/** Keep old *.zh-CN.md URLs working after move to docs/zh/ */
const zhLegacyRewrites: Record<string, string> = {
  "events.zh-CN.md": "zh/events.md",
  "wire.zh-CN.md": "zh/wire.md",
  "reasoning.zh-CN.md": "zh/reasoning.md",
  "development.zh-CN.md": "zh/development.md",
  "guide/tools-session.md": "guide/concepts.md",
  "zh/guide/tools-session.md": "zh/guide/concepts.md",
  "ja/guide/tools-session.md": "ja/guide/concepts.md",
  "sc/guide/tools-session.md": "sc/guide/concepts.md",
  "pagentv2/index.md": "pagentv4/index.md",
  "pagentv2/quick-start.md": "pagentv4/quick-start.md",
  "pagentv2/core-types.md": "pagentv4/core-types.md",
  "pagentv2/messages.md": "pagentv4/messages.md",
  "pagentv2/tools.md": "pagentv4/tools.md",
  "pagentv2/events.md": "pagentv4/events.md",
  "pagentv2/provider.md": "pagentv4/sandbox.md",
};

export default withMermaid(
  defineConfig({
  title: "pagent",
  description:
    "Minimal async Python agent over OpenAI-compatible Chat Completions",
  base,
  mermaid: {
    fontSize: 15,
    flowchart: {
      useMaxWidth: false,
      htmlLabels: false,
      padding: 24,
      nodeSpacing: 72,
      rankSpacing: 80,
      curve: "basis",
      wrappingWidth: 140,
    },
    sequence: {
      diagramMarginX: 48,
      diagramMarginY: 24,
      actorMargin: 88,
      messageMargin: 48,
      boxMargin: 12,
      noteMargin: 14,
      width: 180,
    },
  },
  rewrites: zhLegacyRewrites,
  ignoreDeadLinks: [/(?:^|\/)README/, /\.\.\//, /\.py$/, /examples\//],
  head: [
    ["link", { rel: "icon", type: "image/png", href: `${base}logo-icon.png` }],
    ["link", { rel: "apple-touch-icon", href: `${base}logo-icon.png` }],
  ],
  themeConfig: {
    logo: { src: "/logo-icon.png", alt: "pagent" },
    socialLinks: [{ icon: "github", link: github }],
    search: { provider: "local" },
    editLink: {
      pattern: `${github}/edit/main/docs/:path`,
      text: "Edit this page on GitHub",
    },
    footer: {
      message: "Released under the MIT License.",
      copyright: "Copyright © pagent contributors",
    },
  },
  locales: {
    root: {
      label: "English",
      lang: "en-US",
      themeConfig: {
        nav: [
          { text: "Guide", link: "/guide/quick-start", activeMatch: "/guide/" },
          { text: "pagentv4", link: "/pagentv4/" },
          { text: "Desktop", link: "/desktop" },
          { text: "VS Code", link: "/vscode" },
          { text: "Wire", link: "/wire" },
          { text: "Dev", link: "/development" },
        ],
        sidebar: [
          {
            text: "Getting started",
            items: [
              { text: "Introduction", link: "/" },
              { text: "Install", link: "/guide/install" },
              { text: "Quick start", link: "/guide/quick-start" },
              { text: "Desktop app", link: "/desktop" },
            ],
          },
          {
            text: "pagentv4",
            items: [
              { text: "Overview", link: "/pagentv4/" },
              { text: "Quick start", link: "/pagentv4/quick-start" },
              { text: "Core types", link: "/pagentv4/core-types" },
              { text: "Messages", link: "/pagentv4/messages" },
              { text: "Tools", link: "/pagentv4/tools" },
              { text: "Desktop app", link: "/desktop" },
              { text: "VS Code extension", link: "/vscode" },
              { text: "Sandbox", link: "/pagentv4/sandbox" },
            ],
          },
          {
            text: "Core concepts",
            items: [
              { text: "Prompt", link: "/guide/prompt" },
              { text: "Tools", link: "/guide/tools" },
              { text: "Memory", link: "/guide/memory" },
            ],
          },
          {
            text: "Built-in tools",
            items: [
              { text: "Overview", link: "/guide/defaults" },
              { text: "clock", link: "/guide/defaults#clock" },
              { text: "region", link: "/guide/defaults#region" },
              { text: "readfile", link: "/guide/defaults#readfile" },
              { text: "web_search", link: "/guide/defaults#web-search" },
            ],
          },
          {
            text: "Streaming & UI",
            items: [
              { text: "Events", link: "/events" },
              { text: "Wire protocol", link: "/wire" },
              { text: "Reasoning streams", link: "/reasoning" },
              { text: "Wire demo (local)", link: "/wire-demo" },
            ],
          },
          {
            text: "Development",
            items: [{ text: "Developer guide", link: "/development" }],
          },
          {
            text: "For agents",
            items: [
              { text: "Agent reference", link: "/agent-reference" },
              { text: "llms.txt index", link: `${site}/llms.txt`, target: "_blank" },
              { text: "llms-full.txt bundle", link: `${site}/llms-full.txt`, target: "_blank" },
            ],
          },
          {
            text: "Compatibility",
            items: [
              { text: "Providers & API keys", link: "/guide/providers" },
            ],
          },
        ],
      },
    },
    zh: {
      label: "简体中文",
      lang: "zh-CN",
      link: "/zh/",
      themeConfig: {
        nav: [
          { text: "指南", link: "/zh/guide/quick-start", activeMatch: "/zh/guide/" },
          { text: "pagentv4", link: "/zh/pagentv4/" },
          { text: "桌面端", link: "/zh/desktop" },
          { text: "插件", link: "/zh/vscode" },
          { text: "Wire", link: "/zh/wire" },
          { text: "开发", link: "/zh/development" },
        ],
        sidebar: [
          {
            text: "入门",
            items: [
              { text: "简介", link: "/zh/" },
              { text: "安装", link: "/zh/guide/install" },
              { text: "快速开始", link: "/zh/guide/quick-start" },
              { text: "桌面端", link: "/zh/desktop" },
            ],
          },
          {
            text: "pagentv4",
            items: [
              { text: "概览", link: "/zh/pagentv4/" },
              { text: "快速开始", link: "/zh/pagentv4/quick-start" },
              { text: "核心类型", link: "/zh/pagentv4/core-types" },
              { text: "消息", link: "/zh/pagentv4/messages" },
              { text: "工具", link: "/zh/pagentv4/tools" },
              { text: "桌面端", link: "/zh/desktop" },
              { text: "VS Code 插件", link: "/zh/vscode" },
              { text: "Sandbox", link: "/zh/pagentv4/sandbox" },
            ],
          },
          {
            text: "核心概念",
            items: [
              { text: "提示词", link: "/zh/guide/prompt" },
              { text: "工具", link: "/zh/guide/tools" },
              { text: "记忆", link: "/zh/guide/memory" },
            ],
          },
          {
            text: "流式与 UI",
            items: [
              { text: "事件流", link: "/zh/events" },
              { text: "Wire 协议", link: "/zh/wire" },
              { text: "思考过程", link: "/zh/reasoning" },
              { text: "Wire demo（本地）", link: "/zh/wire-demo" },
            ],
          },
          {
            text: "内置工具",
            items: [
              { text: "概览", link: "/zh/guide/defaults" },
              { text: "clock", link: "/zh/guide/defaults#clock" },
              { text: "region", link: "/zh/guide/defaults#region" },
              { text: "readfile", link: "/zh/guide/defaults#readfile" },
              { text: "web_search", link: "/zh/guide/defaults#web-search" },
            ],
          },
          {
            text: "开发",
            items: [{ text: "开发指南", link: "/zh/development" }],
          },
          {
            text: "兼容性",
            items: [
              { text: "模型与 API Key", link: "/zh/guide/providers" },
            ],
          },
        ],
        editLink: {
          pattern: `${github}/edit/main/docs/:path`,
          text: "在 GitHub 上编辑此页",
        },
      },
    },
    ja: {
      label: "日本語",
      lang: "ja-JP",
      link: "/ja/",
      themeConfig: {
        nav: [
          { text: "ガイド", link: "/ja/guide/quick-start", activeMatch: "/ja/guide/" },
          { text: "イベント", link: "/ja/events" },
          { text: "Wire", link: "/ja/wire" },
          { text: "開発", link: "/ja/development" },
        ],
        sidebar: [
          {
            text: "はじめに",
            items: [
              { text: "概要", link: "/ja/" },
              { text: "インストール", link: "/ja/guide/install" },
              { text: "クイックスタート", link: "/ja/guide/quick-start" },
            ],
          },
          {
            text: "基本概念",
            items: [
              { text: "プロンプト", link: "/ja/guide/prompt" },
              { text: "ツール", link: "/ja/guide/tools" },
              { text: "メモリ", link: "/ja/guide/memory" },
            ],
          },
          {
            text: "組み込みツール",
            items: [
              { text: "概要", link: "/ja/guide/defaults" },
              { text: "clock", link: "/ja/guide/defaults#clock" },
              { text: "region", link: "/ja/guide/defaults#region" },
              { text: "readfile", link: "/ja/guide/defaults#readfile" },
              { text: "web_search", link: "/ja/guide/defaults#web-search" },
            ],
          },
          {
            text: "ストリーミングと UI",
            items: [
              { text: "イベント", link: "/ja/events" },
              { text: "Wire プロトコル", link: "/ja/wire" },
              { text: "推論ストリーム", link: "/ja/reasoning" },
              { text: "Wire demo（ローカル）", link: "/ja/wire-demo" },
            ],
          },
          {
            text: "開発",
            items: [{ text: "開発者ガイド", link: "/ja/development" }],
          },
          {
            text: "互換性",
            items: [
              { text: "プロバイダと API Key", link: "/ja/guide/providers" },
            ],
          },
        ],
        editLink: {
          pattern: `${github}/edit/main/docs/:path`,
          text: "GitHub でこのページを編集",
        },
      },
    },
    sc: {
      label: "四川话",
      lang: "zh-SC",
      link: "/sc/",
      themeConfig: {
        nav: [
          { text: "咋个用", link: "/sc/guide/quick-start", activeMatch: "/sc/guide/" },
          { text: "事件", link: "/sc/events" },
          { text: "Wire", link: "/sc/wire" },
          { text: "改代码", link: "/sc/development" },
        ],
        sidebar: [
          {
            text: "先晓得",
            items: [
              { text: "简介", link: "/sc/" },
              { text: "安装", link: "/sc/guide/install" },
              { text: "架势搞起", link: "/sc/guide/quick-start" },
            ],
          },
          {
            text: "核心概念",
            items: [
              { text: "提示词", link: "/sc/guide/prompt" },
              { text: "工具", link: "/sc/guide/tools" },
              { text: "记忆", link: "/sc/guide/memory" },
            ],
          },
          {
            text: "内置工具🔋",
            items: [
              { text: "概览", link: "/sc/guide/defaults" },
              { text: "clock", link: "/sc/guide/defaults#clock" },
              { text: "region", link: "/sc/guide/defaults#region" },
              { text: "readfile", link: "/sc/guide/defaults#readfile" },
              { text: "web_search", link: "/sc/guide/defaults#web-search" },
            ],
          },
          {
            text: "流式跟界面",
            items: [
              { text: "事件流", link: "/sc/events" },
              { text: "Wire 协议", link: "/sc/wire" },
              { text: "脑壳转", link: "/sc/reasoning" },
              { text: "Wire demo（本地耍）", link: "/sc/wire-demo" },
            ],
          },
          {
            text: "改代码",
            items: [{ text: "开发指南", link: "/sc/development" }],
          },
          {
            text: "兼容性",
            items: [
              { text: "模型跟 Key", link: "/sc/guide/providers" },
            ],
          },
        ],
        editLink: {
          pattern: `${github}/edit/main/docs/:path`,
          text: "到 GitHub 上改这一页哈",
        },
      },
    },
  },
  }),
);
