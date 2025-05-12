"""
Manus 代理模块

这个文件实现了 OpenManus 的核心 Manus 代理。Manus 是一个多功能通用代理，支持本地工具和 MCP(模型上下文协议)工具，
能够处理各种复杂任务。它集成了浏览器自动化、Python 执行、文本编辑等多种功能。
"""

from typing import Dict, List, Optional

from pydantic import Field, model_validator

from app.agent.browser import BrowserContextHelper
from app.agent.toolcall import ToolCallAgent
from app.config import config
from app.logger import logger
from app.prompt.manus import NEXT_STEP_PROMPT, SYSTEM_PROMPT
from app.tool import Terminate, ToolCollection
from app.tool.ask_human import AskHuman
from app.tool.browser_use_tool import BrowserUseTool
from app.tool.mcp import MCPClients, MCPClientTool
from app.tool.python_execute import PythonExecute
from app.tool.str_replace_editor import StrReplaceEditor


class Manus(ToolCallAgent):
    """一个多功能通用代理，支持本地和 MCP 工具。"""

    name: str = "Manus"  # 代理名称
    description: str = "一个多功能代理，可以使用多种工具（包括 MCP 工具）解决各种任务"

    # 从配置文件加载系统提示词和下一步提示词
    system_prompt: str = SYSTEM_PROMPT.format(directory=config.workspace_root)
    next_step_prompt: str = NEXT_STEP_PROMPT

    max_observe: int = 10000  # 最大观察结果长度
    max_steps: int = 20      # 最大执行步骤数

    # MCP 客户端用于远程工具访问
    mcp_clients: MCPClients = Field(default_factory=MCPClients)

    # 添加通用工具到工具集合
    available_tools: ToolCollection = Field(
        default_factory=lambda: ToolCollection(
            PythonExecute(),     # Python 代码执行工具
            BrowserUseTool(),    # 浏览器操作工具
            StrReplaceEditor(),  # 文本替换编辑器
            AskHuman(),          # 询问人类工具
            Terminate(),         # 终止操作工具
        )
    )

    # 特殊工具名称列表，这些工具有特殊处理逻辑
    special_tool_names: list[str] = Field(default_factory=lambda: [Terminate().name])
    browser_context_helper: Optional[BrowserContextHelper] = None  # 浏览器上下文助手

    # 跟踪连接的 MCP 服务器
    connected_servers: Dict[str, str] = Field(
        default_factory=dict
    )  # server_id -> url/command
    _initialized: bool = False  # 初始化状态标志

    @model_validator(mode="after")
    def initialize_helper(self) -> "Manus":
        """即时初始化基本组件。"""
        # 初始化浏览器上下文助手
        self.browser_context_helper = BrowserContextHelper(self)
        return self

    @classmethod
    async def create(cls, **kwargs) -> "Manus":
        """工厂方法，创建并正确初始化 Manus 实例。"""
        # 创建实例
        instance = cls(**kwargs)
        # 初始化 MCP 服务器连接
        await instance.initialize_mcp_servers()
        instance._initialized = True
        return instance

    async def initialize_mcp_servers(self) -> None:
        """初始化与配置的 MCP 服务器的连接。"""
        # 遍历配置文件中的所有 MCP 服务器
        for server_id, server_config in config.mcp_config.servers.items():
            try:
                # 处理 SSE 类型连接（Server-Sent Events）
                if server_config.type == "sse":
                    if server_config.url:
                        await self.connect_mcp_server(server_config.url, server_id)
                        logger.info(
                            f"Connected to MCP server {server_id} at {server_config.url}"
                        )
                # 处理标准输入输出类型连接
                elif server_config.type == "stdio":
                    if server_config.command:
                        await self.connect_mcp_server(
                            server_config.command,
                            server_id,
                            use_stdio=True,
                            stdio_args=server_config.args,
                        )
                        logger.info(
                            f"Connected to MCP server {server_id} using command {server_config.command}"
                        )
            except Exception as e:
                # 记录连接失败的错误
                logger.error(f"Failed to connect to MCP server {server_id}: {e}")

    async def connect_mcp_server(
        self,
        server_url: str,
        server_id: str = "",
        use_stdio: bool = False,
        stdio_args: List[str] = None,
    ) -> None:
        """连接到 MCP 服务器并添加其工具。
        
        参数:
            server_url: 服务器 URL 或命令
            server_id: 服务器标识
            use_stdio: 是否使用标准输入输出连接
            stdio_args: 当使用 stdio 时的命令参数
        """
        # 基于连接类型创建连接
        if use_stdio:
            # 使用标准输入输出连接
            await self.mcp_clients.connect_stdio(
                server_url, stdio_args or [], server_id
            )
            self.connected_servers[server_id or server_url] = server_url
        else:
            # 使用 SSE 连接
            await self.mcp_clients.connect_sse(server_url, server_id)
            self.connected_servers[server_id or server_url] = server_url

        # 只更新该服务器提供的新工具
        new_tools = [
            tool for tool in self.mcp_clients.tools if tool.server_id == server_id
        ]
        self.available_tools.add_tools(*new_tools)

    async def disconnect_mcp_server(self, server_id: str = "") -> None:
        """从 MCP 服务器断开连接并移除其工具。
        
        参数:
            server_id: 要断开连接的服务器标识，空字符串表示断开所有服务器
        """
        # 断开指定服务器连接
        await self.mcp_clients.disconnect(server_id)
        if server_id:
            # 移除特定服务器
            self.connected_servers.pop(server_id, None)
        else:
            # 清除所有服务器
            self.connected_servers.clear()

        # 重建可用工具集合，不包含已断开连接的服务器工具
        base_tools = [
            tool
            for tool in self.available_tools.tools
            if not isinstance(tool, MCPClientTool)
        ]
        self.available_tools = ToolCollection(*base_tools)
        self.available_tools.add_tools(*self.mcp_clients.tools)

    async def cleanup(self):
        """清理 Manus 代理资源。"""
        # 清理浏览器相关资源
        if self.browser_context_helper:
            await self.browser_context_helper.cleanup_browser()
        # 只有在初始化后才断开所有 MCP 服务器连接
        if self._initialized:
            await self.disconnect_mcp_server()
            self._initialized = False

    async def think(self) -> bool:
        """处理当前状态并决定下一步操作，提供适当的上下文。"""
        # 确保代理已初始化
        if not self._initialized:
            await self.initialize_mcp_servers()
            self._initialized = True

        # 保存原始提示词，以便后续恢复
        original_prompt = self.next_step_prompt
        # 获取最近的消息记录
        recent_messages = self.memory.messages[-3:] if self.memory.messages else []
        # 检查是否正在使用浏览器工具
        browser_in_use = any(
            tc.function.name == BrowserUseTool().name
            for msg in recent_messages
            if msg.tool_calls
            for tc in msg.tool_calls
        )

        # 如果正在使用浏览器，更新提示词以包含浏览器上下文
        if browser_in_use:
            self.next_step_prompt = (
                await self.browser_context_helper.format_next_step_prompt()
            )

        # 调用父类方法处理思考过程
        result = await super().think()

        # 恢复原始提示词
        self.next_step_prompt = original_prompt

        return result
