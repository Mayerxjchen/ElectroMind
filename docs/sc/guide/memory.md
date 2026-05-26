# 记忆

语言：四川话 | [English](/guide/memory) | [普通话](/zh/guide/memory) | [日本語](/ja/guide/memory)

不是对话历史，是自己攒的备注，要得就拼进 prompt（`pagent.memory`，实验性）。

```python
from pagent.memory import Memory
from pagent import Session

notes = Memory()
notes.add("用户偏好公制。")

session = Session(f"你是助手。\n\n备注：\n{notes.as_text()}")
```

莫得自动挂 Agent。存盘：`notes.save_to_file("notes.json")`，`Memory.load_from_file(...)`。

## 相关

- [提示词](./prompt) · [工具](./tools)
