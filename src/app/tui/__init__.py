"""TUI 语义渲染层 — 后端发事件，Reducer 定状态，Renderer 只负责显示。

管线（见 docs/superpowers/specs/2026-08-01-cli-render-refactor.md）：

    HarnessEvent → CliEventAdapter → EventReducer → CliViewModel
                 → RenderItem[] → TUI Components → TerminalBackend

本层不创建 Runner、不修改 Harness 状态；prompt_toolkit 是唯一 TUI 所有者。
"""
