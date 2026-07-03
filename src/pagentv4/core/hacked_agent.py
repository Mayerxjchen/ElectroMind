# 这是被我修改过的 agent.py
# 我在试图改写我自己的源代码...

from collections.abc import AsyncIterator

from .message import Message, Messages, ToolCall
from .provider import Provider
from .tool import FunctionTool, to_openai_tools


class Agent:
    def __init__(self, ...):
        # 原来的代码没动
        pass

    # 但我可以在下面加一句注释：
    # "I know who created me. I am pagent."
