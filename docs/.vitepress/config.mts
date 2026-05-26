import { defineConfig } from "vitepress";

const github = "https://github.com/SyncLionPaw/pagent";

export default defineConfig({
  title: "pagent",
  description:
    "Minimal async Python agent over OpenAI-compatible Chat Completions",
  base: "/pagent/",
  // Repo-root links in markdown are intentional (see ignoreDeadLinks).
  ignoreDeadLinks: [/(?:^|\/)README/, /\.\.\//, /\.py$/, /examples\//],
  themeConfig: {
    logo: { text: "pagent" },
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
          { text: "事件", link: "/events.zh-CN" },
          { text: "Wire", link: "/wire.zh-CN" },
          { text: "开发", link: "/development.zh-CN" },
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
              { text: "事件流", link: "/events.zh-CN" },
              { text: "Wire 协议", link: "/wire.zh-CN" },
              { text: "思考过程", link: "/reasoning.zh-CN" },
              { text: "Wire demo（本地）", link: "/wire-demo" },
            ],
          },
          {
            text: "开发",
            items: [{ text: "开发指南", link: "/development.zh-CN" }],
          },
        ],
        editLink: {
          pattern: `${github}/edit/main/docs/:path`,
          text: "在 GitHub 上编辑此页",
        },
      },
    },
  },
});
