## MCP

### MCP Server (`app.mcp.server.MCPServer`)
- Registers built-in tools: `bash`, `browser`, `editor`, `terminate`
- Methods:
  - `register_tool(tool: BaseTool, method_name: str | None = None) -> None`
  - Internally builds signature and docstrings for MCP tooling

Run a local server (via stdio) through the MCP runner:
```bash
python run_mcp.py --connection stdio
```

### MCP Clients (`app.tool.mcp.MCPClients`)
- `async connect_sse(server_url: str, server_id: str = "")`
- `async connect_stdio(command: str, args: list[str], server_id: str = "")`
- `async list_tools() -> ListToolsResult`
- `async disconnect(server_id: str = "")`

### MCP Agent (`app.agent.mcp.MCPAgent`)
- `async initialize(connection_type: str | None = None, server_url: str | None = None, command: str | None = None, args: list[str] | None = None)`
- Refreshes tools periodically in `think()`

Example:
```python
from app.agent.mcp import MCPAgent
agent = MCPAgent()
await agent.initialize(connection_type="sse", server_url="http://127.0.0.1:8000/sse")
await agent.run("Use a remote tool to perform a task")
```