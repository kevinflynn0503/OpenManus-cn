## Logger

`app.logger` exposes a configured Loguru logger and a helper.

- Function: `define_log_level(print_level="INFO", logfile_level="DEBUG", name: str | None = None) -> loguru.Logger`
- Instance: `logger = define_log_level()`

Example:
```python
from app.logger import logger, define_log_level
logger.info("Started")
# Reconfigure levels and filename prefix
_ = define_log_level(print_level="DEBUG", logfile_level="INFO", name="session")
logger.debug("Debug enabled")
```