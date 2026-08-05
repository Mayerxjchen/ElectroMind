# Codex Desktop — 交互原则参考（D3.0 逆向分析）

- 日期：2026-08-05
- 用途：ElectroMind Desktop V2 的**交互模型参考**。只记录交互原则，不复制品牌资源或专有实现。
- 来源：OpenAI Codex App 官方介绍与 Help Center（见文末链接）、产品观察。
- 参考约束：本文档不决定产品结构——产品结构以本参考为目标，领域语义按
  `docs/design/electromind-desktop-v2.md` 映射为科学计算。

## 1. 核心原则：任务优先，不是工具优先

Codex 不是传统 IDE（文件树 + 编辑器 + 终端 + 调试器），而是**多 Agent 的 command
center**：

```text
项目 → Thread → 用户目标 → Agent 执行过程 → 结果审查
```

- 任务按 **Project** 组织；每个 Agent 在**独立 Thread** 中工作。
- 用户可在多个长期任务之间切换，并直接在线程中检查变更、评论 Diff 或转到编辑器。
- 文件、终端、资源监控**不与聊天区域争夺同等视觉优先级**。

## 2. 信息结构：Projects → Threads

左侧导航以 Project 为第一组织维度（而非时间/日期）：

```text
Projects
└── Threads
```

- 多任务可并行运行，每个任务保持独立上下文。
- 任务状态在列表中持续可见（Running / Waiting approval / Waiting external job /
  Completed / Failed / Interrupted / Needs input）。

## 3. 中央区域：完整 Agent Thread

Thread 是绝对视觉中心，承载任务的全生命周期：

```text
用户目标
Agent 响应
操作活动（Activity）
审批
后台任务状态
变更 / 结果审查
恢复事件
最终总结
```

Agent 的多次工具操作**聚合为内联 Activity**（如 "Worked for 1m 31s"），
运行完成默认折叠、失败自动展开。

## 4. 简洁任务头部

头部只保留任务身份与关键上下文：

```text
CP2K initial labeling
Water MLIP · SSH · Running
```

右侧仅保留必要动作（Open workspace / More）。CPU、内存、路径、模型等细节
不放主头部。

## 5. Composer 是任务控制中心

入门界面围绕一个大输入框，下方/行内只提供关键上下文：

```text
Ask ElectroMind to run or analyze something
＋  Local ▾   Plan mode ▾    Model ▾      ↑
```

- `＋` 菜单承载上下文附件（引用文件、结构、Artifact、Skill、图片等）。
- 运行时发送按钮变成 Stop。
- 权限用明确文本（Permissions: Ask / Auto），不用符号表达。

## 6. Review 工作流

在线程中完成"Agent 做了什么 → 改了什么 → 结果如何 → 用户是否接受"的审查：

- 变更以 Diff 呈现，可评论。
- 右侧 Inspector 按需打开（默认关闭），内容随上下文切换
  （Plan / Changes / Artifacts / Jobs / Environment）。

## 7. 视觉基调

克制、安静、精确、响应、一致：

- 系统字体优先；小字号体系（12/13/14/16/20）。
- 4/8/12/16/24 间距；6/8/12 圆角。
- 主界面基本无阴影；Drawer / Popover / Modal 才使用阴影。
- 无装饰性渐变、无大面积玻璃模糊、无营销型 Landing 风格。
- Hover 120–160ms；Drawer 180–220ms；支持 reduced motion。

## 参考链接

- OpenAI：Introducing the Codex app — https://openai.com/index/introducing-the-codex-app/
- OpenAI：Get started with Codex — https://openai.com/codex/get-started/
- OpenAI Help Center：Moving to the new ChatGPT desktop app —
  https://help.openai.com/en/articles/20001276/
