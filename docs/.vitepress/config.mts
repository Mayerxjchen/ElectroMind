import { defineConfig } from "vitepress";

const github = "https://github.com/SyncLionPaw/pagent";

/** Keep old *.zh-CN.md URLs working after move to docs/zh/ */
const zhLegacyRewrites: Record<string, string> = {
  "events.zh-CN.md": "zh/events.md",
  "wire.zh-CN.md": "zh/wire.md",
  "reasoning.zh-CN.md": "zh/reasoning.md",
  "development.zh-CN.md": "zh/development.md",
};

export default defineConfig({
  title: "pagent",
  description:
    "Minimal async Python agent over OpenAI-compatible Chat Completions",
  base: "/pagent/",
  rewrites: zhLegacyRewrites,
  ignoreDeadLinks: [/(?:^|\/)README/, /\.\.\//, /\.py$/, /examples\//],
  head: [["link", { rel: "icon", type: "image/svg+xml", href: "/logo-icon.svg" }]],
  themeConfig: {
    logo: { src: "/logo-icon.svg", alt: "pagent" },
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
          { text: "Events", link: "/events" },
          { text: "Wire", link: "/wire" },
          { text: "Dev", link: "/development" },
        ],
        sidebar: [
          {
            text: "Getting started",
            items: [
              { text: "Introduction", link: "/" },
              { text: "Quick start", link: "/guide/quick-start" },
              { text: "Providers & API keys", link: "/guide/providers" },
              { text: "Tools & session", link: "/guide/tools-session" },
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
              { text: "llms.txt index", link: "/llms.txt", target: "_blank" },
              { text: "llms-full.txt bundle", link: "/llms-full.txt", target: "_blank" },
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
          { text: "事件", link: "/zh/events" },
          { text: "Wire", link: "/zh/wire" },
          { text: "开发", link: "/zh/development" },
        ],
        sidebar: [
          {
            text: "入门",
            items: [
              { text: "简介", link: "/zh/" },
              { text: "快速开始", link: "/zh/guide/quick-start" },
              { text: "模型与 API Key", link: "/zh/guide/providers" },
              { text: "工具与会话", link: "/zh/guide/tools-session" },
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
            text: "开发",
            items: [{ text: "开发指南", link: "/zh/development" }],
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
              { text: "クイックスタート", link: "/ja/guide/quick-start" },
              { text: "プロバイダと API Key", link: "/ja/guide/providers" },
              { text: "ツールとセッション", link: "/ja/guide/tools-session" },
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
          { text: "指南", link: "/sc/guide/quick-start", activeMatch: "/sc/guide/" },
          { text: "事件", link: "/sc/events" },
          { text: "Wire", link: "/sc/wire" },
          { text: "开发", link: "/sc/development" },
        ],
        sidebar: [
          {
            text: "入门",
            items: [
              { text: "简介", link: "/sc/" },
              { text: "赶紧上手", link: "/sc/guide/quick-start" },
              { text: "模型跟 API Key", link: "/sc/guide/providers" },
              { text: "工具跟会话", link: "/sc/guide/tools-session" },
            ],
          },
          {
            text: "流式跟 UI",
            items: [
              { text: "事件流", link: "/sc/events" },
              { text: "Wire 协议", link: "/sc/wire" },
              { text: "脑壳转", link: "/sc/reasoning" },
              { text: "Wire demo（本地）", link: "/sc/wire-demo" },
            ],
          },
          {
            text: "开发",
            items: [{ text: "开发指南", link: "/sc/development" }],
          },
        ],
        editLink: {
          pattern: `${github}/edit/main/docs/:path`,
          text: "在 GitHub 上改这一页",
        },
      },
    },
  },
});
