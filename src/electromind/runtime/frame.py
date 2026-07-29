"""RunFrame —— 帧栈上的一层运行上下文。

Runner 是执行机，子 agent 委派是函数调用，帧栈就是调用栈。切到子 agent 时压入一
帧、换掉当前上下文指针，子任务跑完弹帧、指针还原到父上下文。当前上下文永远是栈顶帧。

一帧打包了"这一层运行"用到的全部本地状态：

- ``agent`` / ``messages`` / ``conversation_id``：这一层的对话主体与落盘 id。
- ``run_state``：这一层的运行状态（turn 计数、phase），与父层隔离。
- ``sandbox`` / ``store`` / ``skills``：这一层持有的资源与能力，可能借自父帧。
- ``slots``：本帧对上述资源的归属记录。弹帧时只 `release` 掉 ``owned=True`` 的槽位，
  借用自父帧的资源留给父帧继续用。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..conversation import ConversationStore
from ..core.agent import Agent
from ..core.message import Messages
from ..sandbox import Sandbox
from ..skills import SkillRegistry
from .resource import ResourceSlot
from .run_state import RunState


@dataclass
class RunFrame:
    """帧栈上的一层运行上下文；当前上下文 = 栈顶帧。"""

    agent: Agent
    messages: Messages
    conversation_id: str | None = None
    run_state: RunState = field(default_factory=RunState)
    sandbox: Sandbox | None = None
    store: ConversationStore | None = None
    skills: SkillRegistry = field(default_factory=SkillRegistry)
    slots: list[ResourceSlot] = field(default_factory=list)

    async def release(self) -> None:
        """弹帧时调用：关掉本帧拥有的资源，借用的留给父帧。"""
        for slot in self.slots:
            await slot.release()
