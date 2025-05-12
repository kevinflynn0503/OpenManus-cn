"""MCP（模型上下文协议）工具模块，用于连接和管理外部MCP服务器及其工具。

MCP（Model Context Protocol，模型上下文协议）是一个标准化协议，用于使大型语言模型（LLM）能够与外部工具和服务进行通信。
此模块提供了连接到MCP服务器，并使用这些服务器提供的工具的功能。

主要组件：
- MCPClientTool：表示MCP服务器上可调用工具的代理类
- MCPClients：管理多个MCP服务器连接和工具集合的类

支持两种传输协议：
- SSE (Server-Sent Events)：基于HTTP的单向通信协议
- STDIO：基于标准输入/输出的通信协议
"""

from contextlib import AsyncExitStack
from typing import Dict, List, Optional

from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.types import ListToolsResult, TextContent

from app.logger import logger
from app.tool.base import BaseTool, ToolResult
from app.tool.tool_collection import ToolCollection
from mcp import ClientSession, StdioServerParameters


class MCPClientTool(BaseTool):
    """表示MCP服务器上可调用工具的客户端代理类。
    
    此类作为客户端与MCP服务器上实际工具之间的代理，允许OpenManus通过统一的接口调用外部MCP服务器上的工具。
    每个MCPClientTool实例对应一个远程MCP服务器上的特定工具。
    """

    session: Optional[ClientSession] = None  # MCP客户端会话，用于与服务器通信
    server_id: str = ""  # 服务器标识符，用于区分不同的MCP服务器
    original_name: str = ""  # 工具在MCP服务器上的原始名称

    async def execute(self, **kwargs) -> ToolResult:
        """执行工具，通过向MCP服务器发送远程调用请求。
        
        将参数传递给MCP服务器上的实际工具，并返回执行结果。
        
        参数:
            **kwargs: 传递给远程工具的参数
            
        返回:
            ToolResult: 包含工具执行结果或错误信息的对象
        """
        # 检查是否已连接到MCP服务器
        if not self.session:
            return ToolResult(error="Not connected to MCP server")

        try:
            # 记录工具执行信息
            logger.info(f"Executing tool: {self.original_name}")
            # 调用MCP服务器上的工具
            result = await self.session.call_tool(self.original_name, kwargs)
            # 处理返回的文本内容
            content_str = ", ".join(
                item.text for item in result.content if isinstance(item, TextContent)
            )
            return ToolResult(output=content_str or "No output returned.")
        except Exception as e:
            return ToolResult(error=f"Error executing tool: {str(e)}")


class MCPClients(ToolCollection):
    """
    通过模型上下文协议(MCP)连接到多个MCP服务器并管理可用工具的集合。
    
    此类负责：
    1. 管理与多个MCP服务器的连接
    2. 自动发现和注册MCP服务器提供的工具
    3. 维护工具的生命周期和会话状态
    4. 提供统一的接口来访问和调用这些工具
    """

    sessions: Dict[str, ClientSession] = {}  # 存储与各MCP服务器的会话连接，按服务器ID索引
    exit_stacks: Dict[str, AsyncExitStack] = {}  # 异步上下文管理器，用于清理资源
    description: str = "MCP client tools for server interaction"  # 工具集合的描述

    def __init__(self):
        super().__init__()  # 使用空工具列表初始化
        self.name = "mcp"  # 保持名称以向后兼容

    async def connect_sse(self, server_url: str, server_id: str = "") -> None:
        """使用SSE传输协议连接到MCP服务器。
        
        通过Server-Sent Events(SSE)协议建立与MCP服务器的连接，SSE是一种基于HTTP的单向通信协议，
        允许服务器向客户端推送数据。
        
        参数:
            server_url: MCP服务器的URL地址
            server_id: 可选的服务器标识符，如未提供则使用URL作为标识符
            
        异常:
            ValueError: 当未提供服务器URL时抛出
        """
        # 验证服务器URL
        if not server_url:
            raise ValueError("Server URL is required.")

        # 如果未提供服务器ID，则使用URL作为ID
        server_id = server_id or server_url

        # 在建立新连接前确保断开旧连接
        if server_id in self.sessions:
            await self.disconnect(server_id)

        # 创建异步上下文管理器
        exit_stack = AsyncExitStack()
        self.exit_stacks[server_id] = exit_stack

        # 建立SSE客户端连接
        streams_context = sse_client(url=server_url)
        streams = await exit_stack.enter_async_context(streams_context)
        # 创建MCP客户端会话
        session = await exit_stack.enter_async_context(ClientSession(*streams))
        self.sessions[server_id] = session

        # 初始化会话并获取可用工具
        await self._initialize_and_list_tools(server_id)

    async def connect_stdio(
        self, command: str, args: List[str], server_id: str = ""
    ) -> None:
        """使用标准输入/输出(stdio)传输协议连接到MCP服务器。
        
        通过启动外部进程并使用标准输入/输出流与之通信来建立MCP连接。
        这种方式适用于本地运行的MCP服务器程序。
        
        参数:
            command: 启动MCP服务器的命令
            args: 传递给命令的参数列表
            server_id: 可选的服务器标识符，如未提供则使用命令作为标识符
            
        异常:
            ValueError: 当未提供服务器命令时抛出
        """
        # 验证服务器命令
        if not command:
            raise ValueError("Server command is required.")

        # 如果未提供服务器ID，则使用命令作为ID
        server_id = server_id or command

        # 在建立新连接前确保断开旧连接
        if server_id in self.sessions:
            await self.disconnect(server_id)

        # 创建异步上下文管理器
        exit_stack = AsyncExitStack()
        self.exit_stacks[server_id] = exit_stack

        # 设置STDIO服务器参数并创建传输
        server_params = StdioServerParameters(command=command, args=args)
        stdio_transport = await exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        # 获取读写流
        read, write = stdio_transport
        # 创建MCP客户端会话
        session = await exit_stack.enter_async_context(ClientSession(read, write))
        self.sessions[server_id] = session

        # 初始化会话并获取可用工具
        await self._initialize_and_list_tools(server_id)

    async def _initialize_and_list_tools(self, server_id: str) -> None:
        """初始化会话并填充工具映射表。
        
        在成功连接到MCP服务器后，此方法负责：
        1. 初始化MCP客户端会话
        2. 获取服务器提供的所有可用工具
        3. 为每个工具创建本地代理对象
        4. 将这些工具添加到工具集合中
        
        参数:
            server_id: MCP服务器的标识符
            
        异常:
            RuntimeError: 当未找到指定服务器ID的会话时抛出
        """
        # 获取服务器会话
        session = self.sessions.get(server_id)
        if not session:
            raise RuntimeError(f"Session not initialized for server {server_id}")

        # 初始化会话
        await session.initialize()
        # 获取服务器提供的工具列表
        response = await session.list_tools()

        # 为每个服务器工具创建适当的工具对象
        for tool in response.tools:
            original_name = tool.name
            # 总是使用服务器ID作为前缀以确保唯一性
            tool_name = f"mcp_{server_id}_{original_name}"

            # 创建MCP客户端工具代理
            server_tool = MCPClientTool(
                name=tool_name,
                description=tool.description,
                parameters=tool.inputSchema,
                session=session,
                server_id=server_id,
                original_name=original_name,
            )
            # 将工具添加到映射表中
            self.tool_map[tool_name] = server_tool

        # 更新工具元组
        self.tools = tuple(self.tool_map.values())
        # 记录连接信息
        logger.info(
            f"Connected to server {server_id} with tools: {[tool.name for tool in response.tools]}"
        )

    async def list_tools(self) -> ListToolsResult:
        """列出所有可用的工具。
        
        从所有已连接的MCP服务器获取工具列表，并将它们合并为一个完整的工具列表。
        
        返回:
            ListToolsResult: 包含所有MCP服务器上可用工具的对象
        """
        # 创建结果对象
        tools_result = ListToolsResult(tools=[])
        # 遍历所有会话获取工具
        for session in self.sessions.values():
            response = await session.list_tools()
            # 将工具添加到结果列表中
            tools_result.tools += response.tools
        return tools_result

    async def disconnect(self, server_id: str = "") -> None:
        """断开与指定MCP服务器的连接，如果未提供server_id则断开所有服务器。
        
        此方法负责：
        1. 关闭与MCP服务器的连接
        2. 清理相关的资源和引用
        3. 从工具集合中移除相关的工具
        
        参数:
            server_id: 要断开连接的MCP服务器的标识符，如为空则断开所有连接
        """
        if server_id:
            # 断开与特定服务器的连接
            if server_id in self.sessions:
                try:
                    # 获取退出栈
                    exit_stack = self.exit_stacks.get(server_id)

                    # 关闭退出栈，这将处理会话清理
                    if exit_stack:
                        try:
                            await exit_stack.aclose()
                        except RuntimeError as e:
                            # 处理取消作用域错误，这是一个已知的异步清理问题
                            if "cancel scope" in str(e).lower():
                                logger.warning(
                                    f"Cancel scope error during disconnect from {server_id}, continuing with cleanup: {e}"
                                )
                            else:
                                raise

                    # 清理引用
                    self.sessions.pop(server_id, None)
                    self.exit_stacks.pop(server_id, None)

                    # 移除与此服务器关联的工具
                    self.tool_map = {
                        k: v
                        for k, v in self.tool_map.items()
                        if v.server_id != server_id
                    }
                    # 更新工具元组
                    self.tools = tuple(self.tool_map.values())
                    logger.info(f"Disconnected from MCP server {server_id}")
                except Exception as e:
                    logger.error(f"Error disconnecting from server {server_id}: {e}")
        else:
            # 按确定的顺序断开所有服务器
            for sid in sorted(list(self.sessions.keys())):
                await self.disconnect(sid)
            # 清空工具映射和工具列表
            self.tool_map = {}
            self.tools = tuple()
            logger.info("Disconnected from all MCP servers")
