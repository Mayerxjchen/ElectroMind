import json


class Session:
    """Conversation buffer: Chat Completions-shaped message dicts in ``messages``.

    Append: ``session += {"role": "user", "content": "..."}`` or ``session += [msg, ...]``.
    """

    def __init__(self, system_prompt="You are a helpful assistant."):
        self.system_prompt = system_prompt
        self.messages = []
        if not system_prompt:
            return
        self.messages.append({"role": "system", "content": system_prompt})

    def __iadd__(self, other):
        if isinstance(other, (str, bytes, bytearray)):
            raise TypeError("session += expects message dict(s), not str/bytes")
        if isinstance(other, dict):
            self.messages.append(dict(other))
            return self

        self.messages.extend(dict(m) for m in other)
        return self

    def reset(self):
        self.messages.clear()
        if not self.system_prompt:
            return
        self.messages.append({"role": "system", "content": self.system_prompt})

    def save_to_file(self, path, *, indent=2):
        """Write ``messages`` as UTF-8 JSON (API-shaped list of dicts)."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.messages, f, ensure_ascii=False, indent=indent)
