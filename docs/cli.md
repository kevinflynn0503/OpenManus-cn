## CLI Usage

### `python main.py`
Runs the default `Manus` agent interactively.

- Prompts for input and runs the agent
- Cleans up resources on exit

Example:
```bash
python main.py
```

### `python run_mcp.py`
Runs the `MCPAgent` that connects to an MCP server via stdio or SSE.

Options:
- `--connection {stdio|sse}`: transport (default: stdio)
- `--server-url URL`: SSE server URL (default: http://127.0.0.1:8000/sse)
- `--interactive` / `-i`: interactive loop
- `--prompt` / `-p`: run a single prompt and exit

Examples:
```bash
# stdio: spawn MCP server from module reference in config
python run_mcp.py --connection stdio

# SSE: connect to remote MCP server
python run_mcp.py --connection sse --server-url http://localhost:8000/sse

# Single prompt
python run_mcp.py -p "Summarize the latest OpenAI post"
```

### `python run_flow.py`
Runs the planning flow with a `Manus` agent.

- Builds a `PlanningFlow` using `FlowFactory`
- Waits up to 1 hour for completion

Example:
```bash
python run_flow.py
```