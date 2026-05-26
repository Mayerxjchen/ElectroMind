import { defineConfig } from "vitepress";

export default defineConfig({
  title: "pagent",
  description:
    "Minimal async Python agent over OpenAI-compatible Chat Completions",
  base: "/pagent/",
  lang: "en-US",
  // Links to repo root (README, src/, examples/) are intentional.
  ignoreDeadLinks: [/(?:^|\/)README/, /\.\.\//, /\.py$/, /examples\//],
  head: [["link", { rel: "icon", href: "/pagent/favicon.ico" }]],
  themeConfig: {
    logo: { text: "pagent" },
    nav: [
      { text: "Guide", link: "/events", activeMatch: "/events|/wire|/reasoning|/wire-demo" },
      { text: "指南", link: "/events.zh-CN", activeMatch: "\\.zh-CN" },
      { text: "Dev", link: "/development" },
      {
        text: "GitHub",
        link: "https://github.com/SyncLionPaw/pagent",
      },
    ],
    sidebar: [
      {
        text: "Introduction",
        items: [{ text: "Home", link: "/" }],
      },
      {
        text: "User guide",
        items: [
          { text: "Events", link: "/events" },
          { text: "Wire protocol", link: "/wire" },
          { text: "Reasoning streams", link: "/reasoning" },
          { text: "Wire demo", link: "/wire-demo" },
        ],
      },
      {
        text: "用户指南",
        items: [
          { text: "事件流", link: "/events.zh-CN" },
          { text: "Wire 协议", link: "/wire.zh-CN" },
          { text: "思考过程", link: "/reasoning.zh-CN" },
        ],
      },
      {
        text: "Development",
        items: [
          { text: "Developer guide", link: "/development" },
          { text: "开发指南", link: "/development.zh-CN" },
        ],
      },
    ],
    socialLinks: [
      { icon: "github", link: "https://github.com/SyncLionPaw/pagent" },
    ],
    search: { provider: "local" },
    footer: {
      message: "Released under the MIT License.",
      copyright: "Copyright © pagent contributors",
    },
  },
});
