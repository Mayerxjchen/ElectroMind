import json


class Session:
    def __init__(self, system_prompt: str = "You are a helpful assistant.") -> None:
        self.system_prompt = system_prompt
        self.messages: list[dict] = []
        if system_prompt:
            self.add_system(system_prompt)

    def get_messages(self) -> list[dict]:
        return self.messages

    def append(self, message: dict) -> None:
        self.messages.append(message)

    def add_messages(self, messages: list[dict]) -> None:
        self.messages.extend(messages)

    def add_system(self, content: str) -> None:
        self.messages.append({"role": "system", "content": content})

    def add_user(self, content: str) -> None:
        self.messages.append({"role": "user", "content": content})

    def add_assistant(self, content: str, tool_calls: list[dict] | None = None) -> None:
        message: dict = {"role": "assistant"}
        if tool_calls:
            message["tool_calls"] = tool_calls
            message["content"] = content if content else None
        else:
            message["content"] = content
        self.messages.append(message)

    def add_tool(self, content: str, tool_call_id: str | None = None) -> None:
        message = {"role": "tool", "content": content}
        if tool_call_id is not None:
            message["tool_call_id"] = tool_call_id
        self.messages.append(message)

    def reset(self, system_prompt: str | None = None) -> None:
        self.messages.clear()
        if system_prompt is not None:
            self.system_prompt = system_prompt
        system_prompt = self.system_prompt
        if system_prompt:
            self.add_system(system_prompt)

    def to_dict_list(self) -> list[dict]:
        return self.messages.copy()

    def save_to_file(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.messages, f, ensure_ascii=False, indent=2)
