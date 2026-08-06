/** AppShell — React 作为桌面 Shell 的唯一布局所有者。
 *
 * 渲染整个外壳骨架（TitleBar / WarningBar / Workspace / InspectorDrawer /
 * OverlayLayer），vanilla renderer 只把面板内容填进槽位：
 * MessageRenderer 成为 Timeline 槽位的适配器（挂到 [data-chat-log]）。
 *
 * 槽位约定（与 vanilla renderShell 的 findRequired 选择器一一对应）：
 *   [data-slot="titlebar"]          标题栏按钮（macOS 独占，CSS 控制显示）
 *   [data-slot="left-pane-expanded"] 左栏展开内容（会话列表 / Skills / 页脚）
 *   [data-slot="left-pane-collapsed"] 左栏折叠 rail
 *   [data-slot="center-topbar"]      主列顶部（任务标题 / 项目 / 沙箱 pill）
 *   [data-composer-dock]             主列最后一行（正常文档流，React Composer
 *                                    挂到 [data-composer-react]）
 *   [data-slot="right-pane"]         Inspector 抽屉内容（vanilla 填充）
 *   [data-overlay-layer]             模态 / 右键菜单等 fixed 浮层
 *
 * 若 React 外壳缺失（bundle 加载失败等），renderShell 回退到完整 vanilla
 * 模板（legacy 路径），此时本组件不会被渲染。
 */

import React from "react";

/** 与 vanilla platformClass(appInfo) 相同的结果（darwin → macos）。 */
function platformClass(): string {
  try {
    return navigator.platform.toLowerCase().includes("mac") ? "macos" : "default";
  } catch {
    return "default";
  }
}

export const AppShell: React.FC = () => (
  <div className="desktop-root">
    <div className={`desktop-shell ${platformClass()}`} data-shell>
      {/* WarningBar —— 执行风险提示条（vanilla 通过 data-execution-risk-text 更新） */}
      <div className="execution-risk-bar" data-execution-risk-bar hidden>
        <span className="execution-risk-icon" aria-hidden="true">⚠</span>
        <span className="execution-risk-text" data-execution-risk-text>
          本地执行：命令直接以当前用户权限运行，无隔离。
        </span>
      </div>

      {/* TitleBar —— vanilla 填充按钮（CSS 控制 macOS 独占显示） */}
      <div className="desktop-titlebar" data-slot="titlebar" />

      {/* Workspace —— 三栏网格 */}
      <div className="desktop-workbench" data-workbench>
        <aside className="pane pane-left" data-left-pane>
          <div className="pane-expanded" data-slot="left-pane-expanded" />
          <div className="pane-collapsed" data-slot="left-pane-collapsed" />
        </aside>

        <div className="pane-resizer" data-resizer="left" />

        <section className="pane pane-center">
          <div className="pane-topbar center-topbar" data-slot="center-topbar" />
          {/* Timeline —— MessageRenderer / VirtualList 直接挂到该容器 */}
          <div className="chat-log" data-chat-log />
          {/* Composer —— 主列正常文档流的最后一行（非 fixed / 非 absolute）。
              React Composer 挂到 [data-composer-react]；vanilla composer 作为
              ready 之前的兜底由 renderShell 追加到 dock 内。 */}
          <div className="composer-dock" data-composer-dock>
            <div className="composer-react" data-composer-react />
          </div>
        </section>

        <div className="pane-resizer" data-resizer="right" aria-hidden="true" />

        {/* InspectorDrawer —— 默认关闭；窄窗口 (<1280px) 为覆盖抽屉，
            宽窗口为 push 模式，均由 InspectorController 控制 */}
        <aside className="pane pane-right" data-right-pane>
          <div className="pane-expanded" data-slot="right-pane" />
        </aside>
      </div>
    </div>

    {/* OverlayLayer —— 模态 / 右键菜单等 fixed 浮层。position:fixed 不参与
        布局，因此 DOM 位置无关紧要；不设置 z-index 以保持原有层级
        （子元素 z-index 继续参与根上下文，与旧 DOM 树一致）。 */}
    <div className="desktop-overlay-layer" data-overlay-layer />
  </div>
);
