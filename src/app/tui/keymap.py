"""键盘契约（渲染改造计划）：

Enter        发送 / 运行中 steer          Alt+Enter  换行
Tab          运行中将消息 enqueue          Esc        取消生成 / 关闭 Overlay
Ctrl+C       取消 Run；空闲清空输入；再按退出
Ctrl+D       退出                          Ctrl+R     搜索输入历史
Ctrl+O       复制最近 Assistant 回复       PageUp / PageDown  滚动 Transcript
/            Slash Popup                  @          项目文件补全
!            当前 Execution Target 的 Shell 命令
Approval:    Enter（空输入）批准一次 / Esc 取消 Run（无裸字母键）

注：Shift+Enter 依赖终端 CSI-u 序列（本 prompt_toolkit 版本未解析），换行请用 Alt+Enter。
"""

from __future__ import annotations

from prompt_toolkit.filters import Condition, has_focus
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys


def _approval_pending(app) -> Condition:
    return Condition(lambda: app.pending_approval is not None)


def _approval_enter_enabled(app) -> bool:
    """复验 P0-2：审批只能通过显式动作（Enter 批准 / Esc 取消 Run）。

    不再绑定裸 y/n/d——逐键输入 `yes...` 的第一个字符绝不触发审批。
    Enter 仅在 Composer 为空时作为“批准”键；有输入时 Enter 是 steer。
    """
    return app.pending_approval is not None and not app.composer_buffer.text.strip()


def approval_enter_enabled(app) -> Condition:
    return Condition(lambda: _approval_enter_enabled(app))


def _running(app) -> Condition:
    return Condition(lambda: app.state == "running")


def _idle(app) -> Condition:
    return Condition(lambda: app.state == "idle")


def build_key_bindings(app) -> KeyBindings:
    kb = KeyBindings()
    composer = app.composer_buffer
    on_composer = has_focus(composer)

    # ---- 发送 / steer / enqueue（经 Harness 客户端） -----------------------

    @kb.add("enter", filter=on_composer & _idle(app))
    def send(event) -> None:
        text = composer.text
        composer.reset()
        app.send_turn(text, delivery="auto")
        event.app.invalidate()

    @kb.add("enter", filter=on_composer & _running(app))
    def steer(event) -> None:
        text = composer.text
        composer.reset()
        app.send_turn(text, delivery="immediate")
        event.app.invalidate()

    @kb.add("enter", filter=on_composer & _approval_pending(app))
    def steer_while_approval(event) -> None:
        text = composer.text
        composer.reset()
        app.send_turn(text, delivery="immediate")
        event.app.invalidate()

    @kb.add("tab", filter=on_composer & _running(app))
    def enqueue(event) -> None:
        text = composer.text
        composer.reset()
        app.send_turn(text, delivery="enqueue")
        event.app.invalidate()

    # ---- 换行 --------------------------------------------------------------

    @kb.add("escape", "enter", filter=on_composer)  # Alt+Enter 换行
    def newline(event) -> None:
        composer.insert_text("\n")
        event.app.invalidate()

    # ---- 取消 / 退出 --------------------------------------------------------

    @kb.add("escape", filter=on_composer)
    def escape(event) -> None:
        if app.overlay is not None:
            app.close_overlay()
        elif app.pending_approval is not None:
            app.cancel_run()
        elif app.state == "running":
            app.cancel_run()
        event.app.invalidate()

    @kb.add("c-c", filter=on_composer)
    def ctrl_c(event) -> None:
        if app.state == "running" or app.pending_approval is not None:
            app.cancel_run()
        elif composer.text:
            composer.reset()
            app.notice("输入已清空（再次 Ctrl+C 退出）")
        else:
            app.send_line(None)
        event.app.invalidate()

    @kb.add("c-d", filter=on_composer)
    def ctrl_d(event) -> None:
        app.send_line(None)
        event.app.exit()

    # ---- 历史 / 复制 / 滚动 -------------------------------------------------

    @kb.add("c-r", filter=on_composer)
    def search_history(event) -> None:
        composer.start_reverse_incremental_search()
        event.app.invalidate()

    @kb.add("c-o", filter=on_composer)
    def copy_reply(event) -> None:
        app.copy_last_reply()
        event.app.invalidate()

    @kb.add("o", filter=on_composer & _idle(app))
    def open_tool_output(event) -> None:
        app.open_last_tool_output()
        event.app.invalidate()

    @kb.add(Keys.PageUp, filter=~has_focus(app.slash_buffer))
    def scroll_up(event) -> None:
        app.scroll(-1)
        event.app.invalidate()

    @kb.add(Keys.PageDown, filter=~has_focus(app.slash_buffer))
    def scroll_down(event) -> None:
        app.scroll(1)
        event.app.invalidate()

    # ---- Approval（复验 P0-2：无裸字母键；Enter 空输入=批准，Esc=取消 Run） --

    @kb.add("enter", filter=on_composer & approval_enter_enabled(app))
    def approve_enter(event) -> None:
        composer.reset()
        app.resolve_approval(approved=True)
        event.app.invalidate()

    # ---- Slash Popup ---------------------------------------------------------

    @kb.add("/", filter=on_composer)
    def open_slash(event) -> None:
        composer.insert_text("/")
        app.open_slash_popup()
        event.app.invalidate()

    @kb.add("down", filter=has_focus(app.slash_buffer))
    def popup_down(event) -> None:
        app.popup_select(1)
        event.app.invalidate()

    @kb.add("up", filter=has_focus(app.slash_buffer))
    def popup_up(event) -> None:
        app.popup_select(-1)
        event.app.invalidate()

    @kb.add("enter", filter=has_focus(app.slash_buffer))
    def popup_confirm(event) -> None:
        app.popup_confirm()
        event.app.invalidate()

    @kb.add("escape", filter=has_focus(app.slash_buffer))
    def popup_close(event) -> None:
        app.close_overlay()
        event.app.invalidate()

    return kb
