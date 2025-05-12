# -*- coding: utf-8 -*-
"""
MCP代理模块

该模块实现了用于与MCP（Model Context Protocol）服务器交互的代理。
MCP代理可以使用stdio或SSE传输方式连接到MCP服务器，并使用服务器提供的工具。
"""

from typing import Any, Dict, List, Optional, Tuple  # 类型注解

from pydantic import Field  # 数据验证工具

from app.agent.toolcall import ToolCallAgent  # 工具调用代理基类
from app.logger import logger  # 日志记录器
from app.prompt.mcp import MULTIMEDIA_RESPONSE_PROMPT, NEXT_STEP_PROMPT, SYSTEM_PROMPT  # MCP提示模板
from app.schema import AgentState, Message  # 代理状态和消息模型
from app.tool.base import ToolResult  # 工具结果基类
from app.tool.mcp import MCPClients  # MCP客户端工具


class MCPAgent(ToolCallAgent):
    """用于与MCP（Model Context Protocol）服务器交互的代理。

    该代理使用SSE或stdio传输方式连接到MCP服务器，
    并通过代理的工具接口使服务器的工具可用。
    """

    name: str = "mcp_agent"  # 代理名称
    description: str = "连接到MCP服务器并使用其工具的代理"  # 代理描述

    system_prompt: str = SYSTEM_PROMPT  # 系统提示
    next_step_prompt: str = NEXT_STEP_PROMPT  # 下一步提示

    # 初始化MCP工具集合
    mcp_clients: MCPClients = Field(default_factory=MCPClients)  # MCP客户端集合
    available_tools: MCPClients = None  # 可用工具，将在initialize()中设置

    max_steps: int = 20  # 最大步骤数
    connection_type: str = "stdio"  # 连接类型："stdio"或"sse"

    # 跟踪工具模式以检测变化
    tool_schemas: Dict[str, Dict[str, Any]] = Field(default_factory=dict)  # 工具模式字典
    _refresh_tools_interval: int = 5  # 每几步刷新工具

    # 应触发终止的特殊工具名称
    special_tool_names: List[str] = Field(default_factory=lambda: ["terminate"])

    async def initialize(
        self,
        connection_type: Optional[str] = None,
        server_url: Optional[str] = None,
        command: Optional[str] = None,
        args: Optional[List[str]] = None,
    ) -> None:
        """初始化MCP连接。

        根据指定的连接类型初始化与MCP服务器的连接，并设置可用工具。

        Args:
            connection_type: 使用的连接类型（"stdio"或"sse"）
            server_url: MCP服务器的URL（用于SSE连接）
            command: 要运行的命令（用于stdio连接）
            args: 命令的参数（用于stdio连接）
        """
        # 如果提供了连接类型，则更新实例的连接类型
        if connection_type:
            self.connection_type = connection_type

        # 根据连接类型连接到MCP服务器
        if self.connection_type == "sse":
            # 使用SSE连接
            if not server_url:
                raise ValueError("Server URL is required for SSE connection")
            await self.mcp_clients.connect_sse(server_url=server_url)
        elif self.connection_type == "stdio":
            # 使用stdio连接
            if not command:
                raise ValueError("Command is required for stdio connection")
            await self.mcp_clients.connect_stdio(command=command, args=args or [])
        else:
            # 不支持的连接类型
            raise ValueError(f"Unsupported connection type: {self.connection_type}")

        # 将可用工具设置为我们的MCP实例
        self.available_tools = self.mcp_clients

        # 存储初始工具模式
        await self._refresh_tools()

        # 添加有关可用工具的系统消息
        tool_names = list(self.mcp_clients.tool_map.keys())
        tools_info = ", ".join(tool_names)

        # 添加系统提示和可用工具信息
        self.memory.add_message(
            Message.system_message(
                f"{self.system_prompt}\n\nAvailable MCP tools: {tools_info}"
            )
        )

    async def _refresh_tools(self) -> Tuple[List[str], List[str]]:
        """从 MCP 服务器刷新可用工具列表。

        查询MCP服务器以获取最新的工具列表，并跟踪添加、移除和更改的工具。

        Returns:
            包含（添加的工具，移除的工具）的元组
        """
        # 如果没有活跃的MCP会话，返回空列表
        if not self.mcp_clients.sessions:
            return [], []

        # 直接从服务器获取当前工具模式
        response = await self.mcp_clients.list_tools()
        current_tools = {tool.name: tool.inputSchema for tool in response.tools}

        # 确定添加、移除和更改的工具
        current_names = set(current_tools.keys())  # 当前工具名称集合
        previous_names = set(self.tool_schemas.keys())  # 先前工具名称集合

        # 计算添加和移除的工具
        added_tools = list(current_names - previous_names)  # 新添加的工具
        removed_tools = list(previous_names - current_names)  # 移除的工具

        # 检查现有工具的模式变化
        changed_tools = []
        for name in current_names.intersection(previous_names):  # 遍历同时存在于当前和先前集合中的工具
            if current_tools[name] != self.tool_schemas.get(name):  # 如果模式不同
                changed_tools.append(name)  # 添加到变化工具列表

        # 更新存储的模式
        self.tool_schemas = current_tools

        # 记录并通知变化
        if added_tools:  # 如果有添加的工具
            logger.info(f"Added MCP tools: {added_tools}")
            # 将新工具信息添加到代理内存中
            self.memory.add_message(
                Message.system_message(f"New tools available: {', '.join(added_tools)}")
            )
        if removed_tools:  # 如果有移除的工具
            logger.info(f"Removed MCP tools: {removed_tools}")
            # 将移除的工具信息添加到代理内存中
            self.memory.add_message(
                Message.system_message(
                    f"Tools no longer available: {', '.join(removed_tools)}"
                )
            )
        if changed_tools:  # 如果有变化的工具
            logger.info(f"Changed MCP tools: {changed_tools}")

        # 返回添加和移除的工具列表
        return added_tools, removed_tools

    async def think(self) -> bool:
        """处理当前状态并决定下一步操作。
        
        首先检查MCP会话和工具可用性，定期刷新工具列表，
        然后调用父类的think方法执行实际的思考过程。
        
        Returns:
            如果思考成功则为True，如果因为服务不可用等原因终止则为False
        """
        # 检查MCP会话和工具可用性
        if not self.mcp_clients.sessions or not self.mcp_clients.tool_map:
            logger.info("MCP service is no longer available, ending interaction")
            self.state = AgentState.FINISHED  # 将代理状态设置为完成
            return False  # 返回False表示思考过程终止

        # 定期刷新工具
        if self.current_step % self._refresh_tools_interval == 0:  # 每隔几步刷新一次工具
            await self._refresh_tools()  # 刷新工具列表
            # 所有工具均被移除表示服务器已关闭
            if not self.mcp_clients.tool_map:
                logger.info("MCP service has shut down, ending interaction")
                self.state = AgentState.FINISHED  # 将代理状态设置为完成
                return False  # 终止交互

        # 使用父类的think方法完成实际的思考过程
        return await super().think()

    async def _handle_special_tool(self, name: str, result: Any, **kwargs) -> None:
        """处理特殊工具执行和状态变化
        
        先调用父类的处理方法，然后处理多媒体响应（如图像）。
        
        Args:
            name: 工具名称
            result: 工具执行结果
            **kwargs: 其他参数
        """
        # 首先使用父类处理程序处理
        await super()._handle_special_tool(name, result, **kwargs)

        # 处理多媒体响应（包含图像的结果）
        if isinstance(result, ToolResult) and result.base64_image:  # 如果结果包含图像
            # 将多媒体响应提示添加到代理内存中
            self.memory.add_message(
                Message.system_message(
                    MULTIMEDIA_RESPONSE_PROMPT.format(tool_name=name)  # 使用工具名称格式化多媒体响应提示
                )
            )

    def _should_finish_execution(self, name: str, **kwargs) -> bool:
        """决定工具执行是否应该结束代理
        
        检查工具名称是否为'terminate'，如果是则结束代理执行。
        
        Args:
            name: 工具名称
            **kwargs: 其他参数
            
        Returns:
            如果应该结束执行则返回True，否则返回False
        """
        # 如果工具名称是'terminate'，则终止执行
        return name.lower() == "terminate"

    async def cleanup(self) -> None:
        """完成后清理MCP连接。
        
        检查是否有活跃的MCP会话，如果有则断开连接并记录日志。
        """
        # 如果有活跃的MCP会话
        if self.mcp_clients.sessions:
            # 断开MCP连接
            await self.mcp_clients.disconnect()
            logger.info("MCP connection closed")  # 记录关闭连接的日志

    async def run(self, request: Optional[str] = None) -> str:
        """运行代理并在完成后清理资源。
        
        使用try-finally结构确保无论是否发生错误，都会执行清理操作。
        
        Args:
            request: 可选的请求文本
            
        Returns:
            代理执行的结果文本
        """
        try:
            # 调用父类的run方法执行代理
            result = await super().run(request)
            return result
        finally:
            # 确保即使发生错误也执行清理操作
            await self.cleanup()
