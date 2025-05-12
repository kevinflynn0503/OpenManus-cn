"""
配置模块

这个模块定义了OpenManus项目的所有配置类和设置。它使用Pydantic模型来定义和验证配置项，
确保类型安全和配置的正确性。主要配置项包括：

1. 语言模型 (LLM) 设置 - 包括API密钥、模型选择和参数
2. 沙箱 (Sandbox) 设置 - 控制代码执行环境
3. 浏览器 (Browser) 设置 - 用于网页浏览和交互
4. 搜索 (Search) 设置 - 配置搜索引擎和参数
5. MCP（模型上下文协议）设置 - 用于与外部服务进行通信

模块实现了单例模式，确保整个应用程序使用一致的配置。配置可以从多种来源加载，
包括TOML文件、环境变量和默认值。
"""

import json
import threading
import tomllib
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


def get_project_root() -> Path:
    """获取项目的根目录路径
    
    这个函数通过当前文件的路径计算项目的根目录。它使用__file__变量找到
    配置模块的位置，然后通过resolve()获取绝对路径，再通过parent.parent
    访问上两级目录，即项目的根目录。
    
    返回:
        Path: 项目根目录的路径对象
    """
    return Path(__file__).resolve().parent.parent


# 项目根目录路径，用于定位项目的其他文件和目录
PROJECT_ROOT = get_project_root()
# 工作区根目录，用于存放用户数据和生成的文件
WORKSPACE_ROOT = PROJECT_ROOT / "workspace"


class LLMSettings(BaseModel):
    model: str = Field(..., description="Model name")
    base_url: str = Field(..., description="API base URL")
    api_key: str = Field(..., description="API key")
    max_tokens: int = Field(4096, description="Maximum number of tokens per request")
    max_input_tokens: Optional[int] = Field(
        None,
        description="Maximum input tokens to use across all requests (None for unlimited)",
    )
    temperature: float = Field(1.0, description="Sampling temperature")
    api_type: str = Field(..., description="Azure, Openai, or Ollama")
    api_version: str = Field(..., description="Azure Openai version if AzureOpenai")


class ProxySettings(BaseModel):
    server: str = Field(None, description="Proxy server address")
    username: Optional[str] = Field(None, description="Proxy username")
    password: Optional[str] = Field(None, description="Proxy password")


class SearchSettings(BaseModel):
    engine: str = Field(default="Google", description="Search engine the llm to use")
    fallback_engines: List[str] = Field(
        default_factory=lambda: ["DuckDuckGo", "Baidu", "Bing"],
        description="Fallback search engines to try if the primary engine fails",
    )
    retry_delay: int = Field(
        default=60,
        description="Seconds to wait before retrying all engines again after they all fail",
    )
    max_retries: int = Field(
        default=3,
        description="Maximum number of times to retry all engines when all fail",
    )
    lang: str = Field(
        default="en",
        description="Language code for search results (e.g., en, zh, fr)",
    )
    country: str = Field(
        default="us",
        description="Country code for search results (e.g., us, cn, uk)",
    )


class BrowserSettings(BaseModel):
    headless: bool = Field(False, description="Whether to run browser in headless mode")
    disable_security: bool = Field(
        True, description="Disable browser security features"
    )
    extra_chromium_args: List[str] = Field(
        default_factory=list, description="Extra arguments to pass to the browser"
    )
    chrome_instance_path: Optional[str] = Field(
        None, description="Path to a Chrome instance to use"
    )
    wss_url: Optional[str] = Field(
        None, description="Connect to a browser instance via WebSocket"
    )
    cdp_url: Optional[str] = Field(
        None, description="Connect to a browser instance via CDP"
    )
    proxy: Optional[ProxySettings] = Field(
        None, description="Proxy settings for the browser"
    )
    max_content_length: int = Field(
        2000, description="Maximum length for content retrieval operations"
    )


class SandboxSettings(BaseModel):
    """Configuration for the execution sandbox"""

    use_sandbox: bool = Field(False, description="Whether to use the sandbox")
    image: str = Field("python:3.12-slim", description="Base image")
    work_dir: str = Field("/workspace", description="Container working directory")
    memory_limit: str = Field("512m", description="Memory limit")
    cpu_limit: float = Field(1.0, description="CPU limit")
    timeout: int = Field(300, description="Default command timeout (seconds)")
    network_enabled: bool = Field(
        False, description="Whether network access is allowed"
    )


class MCPServerConfig(BaseModel):
    """Configuration for a single MCP server"""

    type: str = Field(..., description="Server connection type (sse or stdio)")
    url: Optional[str] = Field(None, description="Server URL for SSE connections")
    command: Optional[str] = Field(None, description="Command for stdio connections")
    args: List[str] = Field(
        default_factory=list, description="Arguments for stdio command"
    )


class MCPSettings(BaseModel):
    """Configuration for MCP (Model Context Protocol)"""

    server_reference: str = Field(
        "app.mcp.server", description="Module reference for the MCP server"
    )
    servers: Dict[str, MCPServerConfig] = Field(
        default_factory=dict, description="MCP server configurations"
    )

    @classmethod
    def load_server_config(cls) -> Dict[str, MCPServerConfig]:
        """Load MCP server configuration from JSON file"""
        config_path = PROJECT_ROOT / "config" / "mcp.json"

        try:
            config_file = config_path if config_path.exists() else None
            if not config_file:
                return {}

            with config_file.open() as f:
                data = json.load(f)
                servers = {}

                for server_id, server_config in data.get("mcpServers", {}).items():
                    servers[server_id] = MCPServerConfig(
                        type=server_config["type"],
                        url=server_config.get("url"),
                        command=server_config.get("command"),
                        args=server_config.get("args", []),
                    )
                return servers
        except Exception as e:
            raise ValueError(f"Failed to load MCP server config: {e}")


class AppConfig(BaseModel):
    llm: Dict[str, LLMSettings]
    sandbox: Optional[SandboxSettings] = Field(
        None, description="Sandbox configuration"
    )
    browser_config: Optional[BrowserSettings] = Field(
        None, description="Browser configuration"
    )
    search_config: Optional[SearchSettings] = Field(
        None, description="Search configuration"
    )
    mcp_config: Optional[MCPSettings] = Field(None, description="MCP configuration")

    class Config:
        arbitrary_types_allowed = True


class Config:
    """配置管理类，实现单例模式管理应用程序的所有配置。
    
    这个类使用单例模式，确保在整个应用程序中只有一个配置实例。
    它会从配置文件中加载设置，并提供访问各种配置（LLM、沙箱、浏览器等）的方法。
    所有的配置访问都是线程安全的，使用锁来确保配置只被初始化一次。
    """
    # 单例实例引用
    _instance = None
    # 线程锁，用于确保线程安全的单例创建和初始化
    _lock = threading.Lock()
    # 标记是否已初始化
    _initialized = False

    def __new__(cls):
        """实现单例模式，确保只创建一个Config实例。
        
        这个方法重写了__new__，使用线程锁来确保即使在多线程环境下
        也只创建一个实例。
        """
        if cls._instance is None:
            with cls._lock:  # 使用线程锁确保线程安全
                if cls._instance is None:  # 再次检查，防止线程竹争
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """初始化配置实例。
        
        这个方法确保配置只被初始化一次。它使用线程锁来保护
        初始化过程，并调用_load_initial_config方法加载配置。
        """
        if not self._initialized:  # 如果尚未初始化
            with self._lock:  # 使用线程锁保护初始化过程
                if not self._initialized:  # 再次检查初始化状态
                    self._config = None  # 初始化配置对象
                    self._load_initial_config()  # 加载配置
                    self._initialized = True  # 标记为已初始化

    @staticmethod
    def _get_config_path() -> Path:
        """获取配置文件路径。
        
        首先尝试查找config.toml文件，如果不存在，则尝试使用config.example.toml文件。
        如果两个文件都不存在，则抛出异常。
        
        返回:
            Path: 配置文件的路径对象
            
        异常:
            FileNotFoundError: 如果找不到配置文件
        """
        root = PROJECT_ROOT  # 项目根目录
        # 尝试查找主配置文件
        config_path = root / "config" / "config.toml"
        if config_path.exists():
            return config_path
        # 如果主配置文件不存在，尝试使用示例配置文件
        example_path = root / "config" / "config.example.toml"
        if example_path.exists():
            return example_path
        # 如果两个文件都不存在，抛出异常
        raise FileNotFoundError("No configuration file found in config directory")

    def _load_config(self) -> dict:
        """加载配置文件并解析为字典。
        
        使用tomllib库来解析TOML格式的配置文件。
        
        返回:
            dict: 包含配置项的字典
        """
        # 获取配置文件路径
        config_path = self._get_config_path()
        # 以二进制模式打开文件并使用tomllib解析TOML文件
        with config_path.open("rb") as f:
            return tomllib.load(f)

    def _load_initial_config(self):
        """加载并初始化所有配置项。
        
        这个方法从配置文件中加载并处理各种配置，包括LLM、浏览器、搜索、沙箱和MCP等设置。
        它处理配置的继承和覆盖，允许不同配置配置文件中定义特定的参数变体。
        """
        # 加载原始配置字典
        raw_config = self._load_config()
        # 获取LLM相关配置
        base_llm = raw_config.get("llm", {})
        # 提取LLM的覆盖配置（即子字典，如特定模型的配置）
        llm_overrides = {
            k: v for k, v in raw_config.get("llm", {}).items() if isinstance(v, dict)
        }

        # 创建LLM的默认设置
        default_settings = {
            "model": base_llm.get("model"),  # 语言模型名称
            "base_url": base_llm.get("base_url"),  # API基础URL
            "api_key": base_llm.get("api_key"),  # API密钥
            "max_tokens": base_llm.get("max_tokens", 4096),  # 每次请求的最大令牌数，默认为4096
            "max_input_tokens": base_llm.get("max_input_tokens"),  # 输入令牌数限制
            "temperature": base_llm.get("temperature", 1.0),  # 采样温度，默认为1.0
            "api_type": base_llm.get("api_type", ""),  # API类型（OpenAI、Azure、AWS等）
            "api_version": base_llm.get("api_version", ""),  # API版本（如果适用）
        }

        # handle browser config.
        browser_config = raw_config.get("browser", {})
        browser_settings = None

        if browser_config:
            # handle proxy settings.
            proxy_config = browser_config.get("proxy", {})
            proxy_settings = None

            if proxy_config and proxy_config.get("server"):
                proxy_settings = ProxySettings(
                    **{
                        k: v
                        for k, v in proxy_config.items()
                        if k in ["server", "username", "password"] and v
                    }
                )

            # filter valid browser config parameters.
            valid_browser_params = {
                k: v
                for k, v in browser_config.items()
                if k in BrowserSettings.__annotations__ and v is not None
            }

            # if there is proxy settings, add it to the parameters.
            if proxy_settings:
                valid_browser_params["proxy"] = proxy_settings

            # only create BrowserSettings when there are valid parameters.
            if valid_browser_params:
                browser_settings = BrowserSettings(**valid_browser_params)

        # 加载搜索引擎配置
        search_config = raw_config.get("search", {})  # 从原始配置中获取搜索配置部分
        search_settings = None
        if search_config:
            # 如果有搜索配置，创建SearchSettings对象
            search_settings = SearchSettings(**search_config)
            
        # 加载沙箱环境配置
        sandbox_config = raw_config.get("sandbox", {})  # 从原始配置中获取沙箱配置部分
        if sandbox_config:
            # 如果有沙箱配置，用它创建SandboxSettings对象
            sandbox_settings = SandboxSettings(**sandbox_config)
        else:
            # 如果没有沙箱配置，使用默认配置
            sandbox_settings = SandboxSettings()

        # 加载MCP（模型上下文协议）配置
        mcp_config = raw_config.get("mcp", {})  # 从原始配置中获取MCP配置部分
        mcp_settings = None
        if mcp_config:
            # 从外部JSON文件加载MCP服务器配置
            mcp_config["servers"] = MCPSettings.load_server_config()
            # 创建MCPSettings对象
            mcp_settings = MCPSettings(**mcp_config)
        else:
            # 如果没有MCP配置，只使用从外部JSON文件加载的服务器配置
            mcp_settings = MCPSettings(servers=MCPSettings.load_server_config())

        # 构建完整的配置字典，包含所有组件的配置
        config_dict = {
            # LLM配置包含默认设置和不同模型的特定覆盖设置
            "llm": {
                # 默认配置
                "default": default_settings,
                # 合并其他模型的配置，每个模型配置继承默认设置并应用特定覆盖
                **{
                    name: {**default_settings, **override_config}  # 合并默认设置和覆盖设置
                    for name, override_config in llm_overrides.items()
                },
            },
            # 沙箱环境配置
            "sandbox": sandbox_settings,
            # 浏览器配置
            "browser_config": browser_settings,
            # 搜索引擎配置
            "search_config": search_settings,
            # MCP配置
            "mcp_config": mcp_settings,
        }

        # 使用配置字典创建AppConfig对象，存储在实例的_config属性中
        self._config = AppConfig(**config_dict)

    @property
    def llm(self) -> Dict[str, LLMSettings]:
        """获取语言模型配置。
        
        返回一个字典，包含默认和专用的语言模型配置。
        每个配置都包含模型名称、API密钥、并发映射等设置。
        
        返回:
            Dict[str, LLMSettings]: 语言模型配置字典
        """
        return self._config.llm

    @property
    def sandbox(self) -> SandboxSettings:
        """获取沙箱环境配置。
        
        返回沙箱环境的配置，包括是否使用沙箱、资源限制、
        基础镜像和网络设置等。
        
        返回:
            SandboxSettings: 沙箱配置对象
        """
        return self._config.sandbox

    @property
    def browser_config(self) -> Optional[BrowserSettings]:
        """获取浏览器配置。
        
        返回浏览器相关的配置，如是否使用无头模式、代理设置、
        其他浏览器参数等。如果没有配置，则返回None。
        
        返回:
            Optional[BrowserSettings]: 浏览器配置对象，或None
        """
        return self._config.browser_config

    @property
    def search_config(self) -> Optional[SearchSettings]:
        """获取搜索引擎配置。
        
        返回搜索引擎的配置，包括首选搜索引擎、备用引擎列表、
        语言和国家设置等。如果没有配置，则返回None。
        
        返回:
            Optional[SearchSettings]: 搜索配置对象，或None
        """
        return self._config.search_config

    @property
    def mcp_config(self) -> MCPSettings:
        """获取MCP（模型上下文协议）配置。
        
        返回与模型上下文协议相关的配置，用于与外部服务器通信。
        
        返回:
            MCPSettings: MCP配置对象
        """
        return self._config.mcp_config

    @property
    def workspace_root(self) -> Path:
        """获取工作区根目录路径。
        
        工作区目录用于存放用户数据和临时文件。
        
        返回:
            Path: 工作区根目录的路径对象
        """
        return WORKSPACE_ROOT

    @property
    def root_path(self) -> Path:
        """获取应用程序的根路径。
        
        应用程序的根路径用于定位应用程序的各个组件和配置文件。
        
        返回:
            Path: 应用程序根目录的路径对象
        """
        return PROJECT_ROOT


# 创建全局配置实例，用于在应用程序的其他部分访问配置
# 由于 Config 类实现了单例模式，这个实例将是应用程序中唯一的配置对象
config = Config()
