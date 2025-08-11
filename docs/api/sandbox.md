## Sandbox

The sandbox provides a Docker-based isolated execution environment and helpers.

Public exports (`app.sandbox.__all__`):
- `DockerSandbox`, `SandboxManager`, `BaseSandboxClient`, `LocalSandboxClient`, `create_sandbox_client`, `SandboxError`, `SandboxTimeoutError`, `SandboxResourceError`

### LocalSandboxClient (`app.sandbox.client.LocalSandboxClient`)
- Methods:
  - `async create(image: str, work_dir: str, memory_limit: str, cpu_limit: float, network_enabled: bool) -> str`
  - `async run_command(command: str, timeout: int | None = None) -> str`
  - `async read_file(path: str) -> str`
  - `async write_file(path: str, content: str) -> None`
  - `async copy_from(container_path: str, local_path: str) -> None`
  - `async copy_to(local_path: str, container_path: str) -> None`
  - `async cleanup() -> None`

### DockerSandbox (`app.sandbox.core.sandbox.DockerSandbox`)
- Create with `await DockerSandbox(...).create()`; supports `run_command`, file copy, context management (`async with`).

### SandboxManager
- Ensures image, manages lifecycle, cleans up idle sandboxes.

Example:
```python
from app.sandbox import create_sandbox_client
client = create_sandbox_client()
# Use config.sandbox to enable sandbox in tools like StrReplaceEditor
```