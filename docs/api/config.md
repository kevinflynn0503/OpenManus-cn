## Configuration

OpenManus uses Pydantic models and a singleton `config` to manage settings loaded from `config/config.toml`.

### Models
- `app.config.LLMSettings`:
  - `model: str`, `base_url: str`, `api_key: str`, `max_tokens: int`, `max_input_tokens: int | None`, `temperature: float`, `api_type: str`, `api_version: str`
- `app.config.ProxySettings`: `server`, `username`, `password`
- `app.config.SearchSettings`: `engine`, `fallback_engines`, `retry_delay`, `max_retries`, `lang`, `country`
- `app.config.BrowserSettings`: `headless`, `disable_security`, `extra_chromium_args`, `chrome_instance_path`, `wss_url`, `cdp_url`, `proxy`, `max_content_length`
- `app.config.SandboxSettings`: `use_sandbox`, `image`, `work_dir`, `memory_limit`, `cpu_limit`, `timeout`, `network_enabled`
- `app.config.MCPServerConfig`: `type`, `url`, `command`, `args`
- `app.config.MCPSettings`: `server_reference`, `servers: dict[str, MCPServerConfig]`
- `app.config.AppConfig`: groups the above sections

### Accessing configuration
- Singleton accessor: `from app.config import config`
- Common attributes:
  - `config.llm`: dict[str, LLMSettings]
  - `config.sandbox`: `SandboxSettings | None`
  - `config.browser_config`: `BrowserSettings | None`
  - `config.search_config`: `SearchSettings | None`
  - `config.mcp_config`: `MCPSettings | None`
  - `config.root_path`, `config.workspace_root` (derived paths)

Example:
```python
from app.config import config
print(config.llm["default"].model)
if config.sandbox and config.sandbox.use_sandbox:
    print("Sandbox enabled")
```

### Files
- Copy: `cp config/config.example.toml config/config.toml`
- Optional: `config/mcp.example.json` for MCP servers (loaded by `MCPSettings.load_server_config()` if present)