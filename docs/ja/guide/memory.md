# メモリ

言語: [日本語](/ja/guide/memory) | [English](/guide/memory) | [简体中文](/zh/guide/memory) | [四川话](/sc/guide/memory)

会話履歴ではなく、自分で持つメモをプロンプトに貼るだけ（`pagent.memory`、実験的）。

```python
from pagent.memory import Memory
from pagent import Session

notes = Memory()
notes.add("ユーザーはメートル法を好む。")

session = Session(f"助手。\n\nメモ:\n{notes.as_text()}")
```

Agent には自動接続されません。保存: `notes.save_to_file("notes.json")`、`Memory.load_from_file(...)`。

## 関連

- [プロンプト](./prompt) · [ツール](./tools)
