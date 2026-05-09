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
        if isinstance(other, dict):
            self.messages.append(dict(other))
        elif isinstance(other, (str, bytes, bytearray)):
            raise TypeError("session += expects message dict(s), not str/bytes")
        else:
            self.messages.extend(dict(m) for m in other)
        return self

    def reset(self):
        self.messages.clear()
        if not self.system_prompt:
            return
        self.messages.append({"role": "system", "content": self.system_prompt})
