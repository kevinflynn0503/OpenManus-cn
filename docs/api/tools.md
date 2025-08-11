## Tools API

This section documents the tool framework and built-in tools.

### Base types
- `app.tool.base.BaseTool`
  - Fields: `name: str`, `description: str`, `parameters: dict | None`
  - Methods:
    - `async __call__(**kwargs) -> Any`: calls `execute`
    - `async execute(**kwargs) -> Any`: implement in subclasses
    - `to_param() -> dict`: OpenAI-style tool/function schema

- `app.tool.base.ToolResult`
  - Fields: `output: Any`, `error: str | None`, `base64_image: str | None`, `system: str | None`
  - Truthy when any field populated; `__add__` combines results

- `app.tool.base.CLIResult(ToolResult)` and `ToolFailure(ToolResult)`

- `app.tool.tool_collection.ToolCollection`
  - `to_params() -> list[dict]`
  - `async execute(name: str, tool_input: dict | None = None) -> ToolResult`
  - `async execute_all() -> list[ToolResult]`
  - `get_tool(name: str) -> BaseTool | None`
  - `add_tool(tool: BaseTool)`, `add_tools(*tools: BaseTool)`

### Bash
- Class: `app.tool.bash.Bash`
- Name: `bash`
- Execute: `async execute(command: str | None = None, restart: bool = False) -> CLIResult`
- Parameters schema: `{ command: string(required) }`

Example:
```python
from app.tool.bash import Bash
bash = Bash()
rst = await bash.execute("ls -la")
print(rst.output)
```

### PythonExecute
- Class: `app.tool.python_execute.PythonExecute`
- Name: `python_execute`
- Execute: `async execute(code: str, timeout: int = 5) -> dict`

Example:
```python
from app.tool.python_execute import PythonExecute
py = PythonExecute()
res = await py.execute(code='print(2 + 2)')
# res => {"observation": "4\n", "success": True}
```

### WebSearch
- Class: `app.tool.web_search.WebSearch`
- Name: `web_search`
- Execute:
  ```python
  async execute(
      query: str,
      num_results: int = 5,
      lang: str | None = None,
      country: str | None = None,
      fetch_content: bool = False,
  ) -> SearchResponse
  ```
- Returns `SearchResponse` with `results: list[SearchResult]` and `metadata`

Example:
```python
from app.tool.web_search import WebSearch
search = WebSearch()
resp = await search.execute(query="OpenAI o3-mini")
print(resp.output)
```

### StrReplaceEditor
- Class: `app.tool.str_replace_editor.StrReplaceEditor`
- Name: `str_replace_editor`
- Commands: `view`, `create`, `str_replace`, `insert`, `undo_edit`
- Execute:
  ```python
  async execute(
      *,
      command: Literal["view","create","str_replace","insert","undo_edit"],
      path: str,
      file_text: str | None = None,
      view_range: list[int] | None = None,
      old_str: str | None = None,
      new_str: str | None = None,
      insert_line: int | None = None,
      **kwargs,
  ) -> str | ToolResult
  ```

Examples:
```python
from app.tool.str_replace_editor import StrReplaceEditor
ed = StrReplaceEditor()
# View a file
await ed.execute(command="view", path="/workspace/README.md")
# Create a file
await ed.execute(command="create", path="/workspace/tmp.txt", file_text="hello")
# Replace text
await ed.execute(command="str_replace", path="/workspace/tmp.txt", old_str="hello", new_str="hi")
# Insert after line
await ed.execute(command="insert", path="/workspace/tmp.txt", insert_line=1, new_str="\nbye\n")
```

### CreateChatCompletion
- Class: `app.tool.create_chat_completion.CreateChatCompletion`
- Name: `create_chat_completion`
- Constructor: `CreateChatCompletion(response_type: type | None = str)`
- Execute: `async execute(required: list | None = None, **kwargs) -> Any`

Example:
```python
from app.tool.create_chat_completion import CreateChatCompletion
cc = CreateChatCompletion(str)
text = await cc.execute(response="This is the answer")
```

### PlanningTool
- Class: `app.tool.planning.PlanningTool`
- Name: `planning`
- Commands: `create, update, list, get, set_active, mark_step, delete`
- Execute signature mirrors the schema in `app/tool/planning.py`

Example:
```python
from app.tool.planning import PlanningTool
pt = PlanningTool()
await pt.execute(command="create", plan_id="p1", title="Demo", steps=["Do A","Do B"]) 
await pt.execute(command="mark_step", plan_id="p1", step_index=0, step_status="completed")
```

### BrowserUseTool
- Class: `app.tool.browser_use_tool.BrowserUseTool`
- Name: `browser_use_tool`
- Execute common actions:
  - `go_to_url`, `go_back`, `refresh`
  - `web_search`, `click_element`, `input_text`
  - `scroll_down`, `scroll_up`, `scroll_to_text`
  - `send_keys`, `get_dropdown_options`, `select_dropdown_option`
  - `extract_content`, `switch_tab`, `open_tab`, `close_tab`, `wait`

Example:
```python
from app.tool.browser_use_tool import BrowserUseTool
browser = BrowserUseTool()
await browser.execute(action="go_to_url", url="https://example.com")
res = await browser.execute(action="extract_content", goal="main content")
print(res.output)
```

### MCP clients and tools
- `app.tool.mcp.MCPClients` manages connections and exposes remote tools
  - `async connect_sse(server_url: str, server_id: str = "")`
  - `async connect_stdio(command: str, args: list[str], server_id: str = "")`
  - `async list_tools() -> ListToolsResult`
  - `async disconnect(server_id: str = "")`
- `app.tool.mcp.MCPClientTool` represents a remote tool; `async execute(**kwargs) -> ToolResult`

Example:
```python
from app.tool.mcp import MCPClients
clients = MCPClients()
await clients.connect_stdio(command="python", args=["-m","app.mcp.server"], server_id="local")
print(list(clients.tool_map))
```