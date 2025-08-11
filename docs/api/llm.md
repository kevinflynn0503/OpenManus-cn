## LLM API

### `app.llm.LLM`
- Singleton per `config_name`
- Constructor: `LLM(config_name: str = "default", llm_config: LLMSettings | None = None)`
- Key methods:
  - `async ask(messages, system_msgs: list | None = None, stream: bool = True, temperature: float | None = None) -> str`
  - `async ask_with_images(messages, images: list, system_msgs: list | None = None, stream: bool = False, temperature: float | None = None) -> str`
  - `async ask_tool(messages, system_msgs: list | None = None, timeout: int = 300, tools: list[dict] | None = None, tool_choice: ToolChoice = ToolChoice.AUTO, temperature: float | None = None, **kwargs) -> ChatCompletionMessage | None`
- Token management: `total_input_tokens`, `total_completion_tokens`

Example (text):
```python
from app.llm import LLM
from app.schema import Message
llm = LLM()
resp = await llm.ask(
    messages=[Message.user_message("Say hi").to_dict()],
    system_msgs=[Message.system_message("Be concise").to_dict()],
    stream=False,
)
print(resp)
```

Example (tool calls):
```python
from app.llm import LLM
from app.schema import Message, ToolChoice
llm = LLM()
resp = await llm.ask_tool(
    messages=[Message.user_message("Search for OpenManus repo")],
    tools=[{"type":"function","function":{"name":"web_search","description":"","parameters":{"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}}}],
    tool_choice=ToolChoice.AUTO,
)
if resp and resp.tool_calls:
    print(resp.tool_calls)
```

### TokenCounter (`app.llm.TokenCounter`)
- Utilities for calculating tokens of text, images, messages, and tool calls