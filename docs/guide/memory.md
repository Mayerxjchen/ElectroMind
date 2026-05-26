# Memory

Language: [简体中文](/zh/guide/memory) | [日本語](/ja/guide/memory) | [四川话](/sc/guide/memory) | English

Not chat history — a simple note list you paste into the prompt yourself (`pagent.memory`, experimental).

```python
from pagent.memory import Memory
from pagent import Session

notes = Memory()
notes.add("User prefers metric units.")

session = Session(f"You are helpful.\n\nNotes:\n{notes.as_text()}")
```

Not wired into `Agent` automatically. Save/load: `notes.save_to_file("notes.json")`, `Memory.load_from_file(...)`.

## See also

- [Prompt](./prompt) · [Tools](./tools)
