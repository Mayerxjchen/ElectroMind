# 记忆

语言： [中文](/zh/guide/memory) | [English](/guide/memory) | [日本語](/ja/guide/memory) | [四川话](/sc/guide/memory)

不是对话历史，是你自己维护的备注列表，需要时拼进 prompt（`pagent.memory`，实验性）。

```python
from pagent.memory import Memory
from pagent import Session

notes = Memory()
notes.add("用户偏好公制单位。")

session = Session(f"你是助手。\n\n备注：\n{notes.as_text()}")
```

不会自动挂进 `Agent`。存盘：`notes.save_to_file("notes.json")`，`Memory.load_from_file(...)`。

## 相关

- [提示词](./prompt) · [工具](./tools)
