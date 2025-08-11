## Agents API

### BaseAgent (`app.agent.base.BaseAgent`)
- Fields: `name: str`, `description: str | None`, `system_prompt: str | None`, `next_step_prompt: str | None`, `llm: LLM`, `memory: Memory`, `state: AgentState`, `max_steps: int`, `current_step: int`
- Methods:
  - `async run(request: str | None = None) -> str`
  - `async step() -> str` (abstract)
  - `update_memory(role: ROLE_TYPE, content: str, base64_image: str | None = None, **kwargs) -> None`
  - `state_context(new_state: AgentState)` context manager
  - `is_stuck() -> bool`, `handle_stuck_state() -> None`
  - `messages -> list[Message]`

Example:
```python
from app.agent.base import BaseAgent
class EchoAgent(BaseAgent):
    name = "echo"
    async def step(self) -> str:
        return "done"
```

### ReActAgent (`app.agent.react.ReActAgent`)
- Abstract ReAct loop: `async think() -> bool` and `async act() -> str` must be implemented
- Provides `async step()` implementing think-then-act

### ToolCallAgent (`app.agent.toolcall.ToolCallAgent`)
- Extends ReAct with tool calling
- Fields: `available_tools: ToolCollection`, `tool_choices: ToolChoice`, `special_tool_names: list[str]`, `tool_calls: list[ToolCall]`
- Methods:
  - `async think() -> bool`: sends messages + tools to LLM, parses `tool_calls`
  - Handles `TokenLimitExceeded` and special tool behavior

### Manus (`app.agent.manus.Manus`)
- A general-purpose agent with local tools and MCP support
- Fields: `available_tools` includes `PythonExecute`, `BrowserUseTool`, `StrReplaceEditor`, `AskHuman`, `Terminate`
- Classmethod: `async create(**kwargs) -> Manus` (initializes MCP connections)
- Methods:
  - `async connect_mcp_server(server_url: str, server_id: str = "", use_stdio: bool = False, stdio_args: list[str] | None = None) -> None`
  - `async disconnect_mcp_server(server_id: str = "") -> None`
  - `async cleanup() -> None`
  - `async think() -> bool` (adds browser context when browser used)

Example:
```python
from app.agent.manus import Manus
agent = await Manus.create()
await agent.run("Build a simple HTML page and save it to /workspace/index.html")
await agent.cleanup()
```

### MCPAgent (`app.agent.mcp.MCPAgent`)
- Connects to MCP server and exposes its tools
- Methods:
  - `async initialize(connection_type: str | None = None, server_url: str | None = None, command: str | None = None, args: list[str] | None = None) -> None`
  - `async think() -> bool` (refreshes tools periodically)

Example:
```python
from app.agent.mcp import MCPAgent
agent = MCPAgent()
await agent.initialize(connection_type="stdio", command="python", args=["-m","app.mcp.server"])
await agent.run("List available tools")
await agent.cleanup()
```