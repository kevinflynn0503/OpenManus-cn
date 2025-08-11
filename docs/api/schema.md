## Schema

### Enums
- `Role`: `SYSTEM`, `USER`, `ASSISTANT`, `TOOL`
- `ToolChoice`: `NONE`, `AUTO`, `REQUIRED`
- `AgentState`: `IDLE`, `RUNNING`, `FINISHED`, `ERROR`

### Message (`app.schema.Message`)
- Fields: `role`, `content: str | None`, `tool_calls: list[ToolCall] | None`, `name: str | None`, `tool_call_id: str | None`, `base64_image: str | None`
- Methods:
  - `to_dict() -> dict`
  - `user_message(content: str, base64_image: str | None = None) -> Message`
  - `system_message(content: str) -> Message`
  - `assistant_message(content: str | None = None, base64_image: str | None = None) -> Message`
  - `tool_message(content: str, name, tool_call_id: str, base64_image: str | None = None) -> Message`
  - `from_tool_calls(tool_calls, content: str | list[str] = "", base64_image: str | None = None, **kwargs) -> Message`

### ToolCall (`app.schema.ToolCall`), Function, and literals
- `ToolCall`: `{ id: str, type: "function", function: { name: str, arguments: str } }`

### Memory (`app.schema.Memory`)
- Fields: `messages: list[Message]`, `max_messages: int = 100`
- Methods: `add_message`, `add_messages`, `clear`, `get_recent_messages(n)`, `to_dict_list()`

Example:
```python
from app.schema import Message, Memory
mem = Memory()
mem.add_message(Message.user_message("hello"))
print(mem.to_dict_list())
```