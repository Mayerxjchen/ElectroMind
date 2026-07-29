"""Experimental module, not part of the stable top-level public API.

Avoid ``from pagent import Memory`` (it is intentionally not exported there).
Use ``from electromind_legacy.memory import Memory`` when needed.
The interface may change or be removed in future versions.
"""

import json


class Memory:
    """Append-only list of text snippets; join for prompts or save as JSON array."""

    def __init__(self, lines=None):
        self.lines = [str(x) for x in lines] if lines else []

    def add(self, text):
        self.lines.append(str(text))

    def clear(self):
        self.lines.clear()

    def __len__(self):
        return len(self.lines)

    def as_text(self, sep="\n"):
        return sep.join(self.lines)

    def save_to_file(self, path, *, indent=2):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.lines, f, ensure_ascii=False, indent=indent)

    @classmethod
    def load_from_file(cls, path):
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, list):
            raise ValueError("memory file must be a JSON array")
        return cls(raw)
