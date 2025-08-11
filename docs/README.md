## OpenManus Documentation

Welcome to the OpenManus documentation. This site covers all public APIs: agents, tools, flows, LLM interface, configuration, schema, sandbox, MCP integration, and CLI usage.

### Contents
- [Quickstart](../README.md)
- [CLI](./cli.md)
- [Agents API](./api/agents.md)
- [Tools API](./api/tools.md)
- [Flows API](./api/flows.md)
- [LLM API](./api/llm.md)
- [Config](./api/config.md)
- [Schema](./api/schema.md)
- [Sandbox](./api/sandbox.md)
- [MCP](./api/mcp.md)
- [Logger](./api/logger.md)
- [Examples](./examples.md)

### Installation and Configuration
See the root README for setup, configuration, and quick start.

- Installation: see `README.md` Installation section
- Configuration: copy `config/config.example.toml` to `config/config.toml` and set your keys

### Quick Usage
- Start main agent interactively:
```bash
python main.py
```
- Run MCP agent (stdio by default):
```bash
python run_mcp.py --connection stdio
```
- Run planning flow (multi-agent framework):
```bash
python run_flow.py
```