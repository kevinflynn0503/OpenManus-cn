# -*- coding: utf-8 -*-
"""
MCP服务器实现模块

该模块提供了MCP（Model Context Protocol）服务器的实现，
负责注册和管理各种工具，使AI能够通过标准化的接口访问这些工具。
"""

import logging
import sys

# 配置基本日志记录，输出到标准错误流
logging.basicConfig(level=logging.INFO, handlers=[logging.StreamHandler(sys.stderr)])

import argparse            # 用于解析命令行参数
import asyncio             # 用于异步操作
import atexit              # 用于注册退出时的清理函数
import json                # 用于JSON数据处理
from inspect import Parameter, Signature  # 用于动态构建函数签名
from typing import Any, Dict, Optional    # 类型注解

# 导入FastMCP服务器实现
from mcp.server.fastmcp import FastMCP

# 导入应用程序相关模块
from app.logger import logger            # 日志记录器
from app.tool.base import BaseTool       # 工具基类
from app.tool.bash import Bash           # Bash命令工具
from app.tool.browser_use_tool import BrowserUseTool  # 浏览器自动化工具
from app.tool.str_replace_editor import StrReplaceEditor  # 文本替换编辑器
from app.tool.terminate import Terminate  # 终止工具


class MCPServer:
    """MCP服务器实现，包含工具注册和管理功能。
    
    该类实现了一个MCP（Model Context Protocol）服务器，负责：
    1. 注册各种工具并将其暴露给AI模型
    2. 管理工具的执行流程和参数验证
    3. 处理工具的清理和资源释放
    """

    def __init__(self, name: str = "openmanus"):
        """初始化MCP服务器实例
        
        Args:
            name: 服务器名称，默认为"openmanus"
        """
        # 创建FastMCP服务器实例
        self.server = FastMCP(name)
        # 初始化工具字典，用于存储已注册的工具
        self.tools: Dict[str, BaseTool] = {}

        # 初始化标准工具
        self.tools["bash"] = Bash()                    # Bash命令行工具
        self.tools["browser"] = BrowserUseTool()      # 浏览器自动化工具
        self.tools["editor"] = StrReplaceEditor()     # 文本编辑工具
        self.tools["terminate"] = Terminate()         # 终止工具

    def register_tool(self, tool: BaseTool, method_name: Optional[str] = None) -> None:
        """注册工具，包括参数验证和文档生成。
        
        该方法将工具注册到MCP服务器，使AI能够通过标准接口调用该工具。
        注册过程包括：创建异步函数封装、构建文档字符串、设置函数签名和参数架构。
        
        Args:
            tool: 要注册的工具实例，必须是BaseTool的子类
            method_name: 可选的方法名称，如果未提供则使用工具的默认名称
        """
        # 获取工具名称（使用提供的方法名或工具默认名称）
        tool_name = method_name or tool.name
        # 获取工具参数定义
        tool_param = tool.to_param()
        tool_function = tool_param["function"]

        # 定义将要注册的异步函数
        async def tool_method(**kwargs):
            # 记录工具执行信息
            logger.info(f"Executing {tool_name}: {kwargs}")
            # 执行工具并获取结果
            result = await tool.execute(**kwargs)

            logger.info(f"Result of {tool_name}: {result}")

            # 处理不同类型的结果
            if hasattr(result, "model_dump"):
                # 如果结果有model_dump方法（Pydantic模型），转换为JSON
                return json.dumps(result.model_dump())
            elif isinstance(result, dict):
                # 如果结果是字典，转换为JSON
                return json.dumps(result)
            # 其他类型直接返回
            return result

        # 设置方法元数据
        tool_method.__name__ = tool_name  # 设置函数名
        tool_method.__doc__ = self._build_docstring(tool_function)  # 设置文档字符串
        tool_method.__signature__ = self._build_signature(tool_function)  # 设置函数签名

        # 存储参数架构（对于以编程方式访问参数的工具很重要）
        param_props = tool_function.get("parameters", {}).get("properties", {})
        required_params = tool_function.get("parameters", {}).get("required", [])
        tool_method._parameter_schema = {
            param_name: {
                "description": param_details.get("description", ""),  # 参数描述
                "type": param_details.get("type", "any"),  # 参数类型
                "required": param_name in required_params,  # 是否必需
            }
            for param_name, param_details in param_props.items()
        }

        # 向服务器注册工具
        self.server.tool()(tool_method)
        logger.info(f"Registered tool: {tool_name}")

    def _build_docstring(self, tool_function: dict) -> str:
        """从工具函数元数据构建格式化的文档字符串。
        
        根据工具的描述和参数信息，生成标准格式的文档字符串，用于工具的自文档化。
        
        Args:
            tool_function: 包含工具描述和参数定义的字典
            
        Returns:
            格式化的文档字符串
        """
        # 获取工具描述
        description = tool_function.get("description", "")
        # 获取参数属性
        param_props = tool_function.get("parameters", {}).get("properties", {})
        # 获取必需参数列表
        required_params = tool_function.get("parameters", {}).get("required", [])

        # 构建文档字符串（匹配原始格式）
        docstring = description
        if param_props:  # 如果有参数
            docstring += "\n\nParameters:\n"  # 添加参数部分标题
            for param_name, param_details in param_props.items():
                # 确定参数是必需的还是可选的
                required_str = (
                    "(required)" if param_name in required_params else "(optional)"
                )
                # 获取参数类型和描述
                param_type = param_details.get("type", "any")
                param_desc = param_details.get("description", "")
                # 添加格式化的参数信息
                docstring += (
                    f"    {param_name} ({param_type}) {required_str}: {param_desc}\n"
                )

        return docstring

    def _build_signature(self, tool_function: dict) -> Signature:
        """从工具函数元数据构建函数签名。
        
        根据工具的参数定义，创建Python函数签名对象，用于参数类型检查和自动文档生成。
        
        Args:
            tool_function: 包含工具参数定义的字典
            
        Returns:
            函数签名对象
        """
        # 获取参数属性和必需参数列表
        param_props = tool_function.get("parameters", {}).get("properties", {})
        required_params = tool_function.get("parameters", {}).get("required", [])

        # 初始化参数列表
        parameters = []

        # 按照原始类型映射处理每个参数
        for param_name, param_details in param_props.items():
            # 获取参数类型
            param_type = param_details.get("type", "")
            # 如果是必需参数，则默认值为Parameter.empty，否则为None
            default = Parameter.empty if param_name in required_params else None

            # 将JSON Schema类型映射到Python类型
            annotation = Any  # 默认类型为Any
            if param_type == "string":
                annotation = str
            elif param_type == "integer":
                annotation = int
            elif param_type == "number":
                annotation = float
            elif param_type == "boolean":
                annotation = bool
            elif param_type == "object":
                annotation = dict
            elif param_type == "array":
                annotation = list

            # 创建与原始结构相同的参数
            param = Parameter(
                name=param_name,                # 参数名
                kind=Parameter.KEYWORD_ONLY,    # 只能作为关键字参数
                default=default,                # 默认值
                annotation=annotation,          # 类型注解
            )
            parameters.append(param)

        # 返回构建好的函数签名
        return Signature(parameters=parameters)

    async def cleanup(self) -> None:
        """清理服务器资源。
        
        在服务器关闭时调用，负责清理所有工具使用的资源，尤其是浏览器工具可能占用的资源。
        """
        logger.info("Cleaning up resources")
        # 遵循原始清理逻辑 - 只清理浏览器工具
        if "browser" in self.tools and hasattr(self.tools["browser"], "cleanup"):
            # 如果存在浏览器工具并且它有cleanup方法，则调用它
            await self.tools["browser"].cleanup()

    def register_all_tools(self) -> None:
        """向服务器注册所有工具。
        
        迭代工具字典中的所有工具，并将它们注册到服务器。
        """
        # 遍历所有工具并注册
        for tool in self.tools.values():
            self.register_tool(tool)

    def run(self, transport: str = "stdio") -> None:
        """运行MCP服务器。
        
        注册所有工具，设置清理函数，并启动服务器。
        
        Args:
            transport: 通信方式，默认为"stdio"（标准输入/输出）
        """
        # 注册所有工具
        self.register_all_tools()

        # 注册清理函数（在程序退出时执行）
        atexit.register(lambda: asyncio.run(self.cleanup()))

        # 启动服务器（使用相同的日志记录）
        logger.info(f"Starting OpenManus server ({transport} mode)")
        self.server.run(transport=transport)


def parse_args() -> argparse.Namespace:
    """解析命令行参数。
    
    定义并解析命令行参数，主要是服务器的通信方式。
    
    Returns:
        包含解析后参数的命名空间对象
    """
    # 创建参数解析器
    parser = argparse.ArgumentParser(description="OpenManus MCP Server")
    # 添加transport参数
    parser.add_argument(
        "--transport",
        choices=["stdio"],  # 目前只支持stdio
        default="stdio",
        help="Communication method: stdio or http (default: stdio)",
    )
    # 解析并返回参数
    return parser.parse_args()


if __name__ == "__main__":
    # 当脚本作为主程序运行时执行
    # 解析命令行参数
    args = parse_args()

    # 创建并运行服务器（保持原始流程）
    server = MCPServer()
    server.run(transport=args.transport)
