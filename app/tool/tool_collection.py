"""用于管理多个工具的集合类。

这个模块提供了工具集合类，管理多个工具的注册、查询和执行。
工具集合是代理的核心组件之一，它使代理可以访问和调用各种工具来完成任务。
"""
from typing import Any, Dict, List

from app.exceptions import ToolError
from app.logger import logger
from app.tool.base import BaseTool, ToolFailure, ToolResult


class ToolCollection:
    """已定义工具的集合类。
    
    这个类管理一组工具，提供工具查询、执行和添加的功能。
    每个代理都会拥有一个工具集合，定义了该代理可以使用的工具。
    """

    class Config:
        arbitrary_types_allowed = True  # 允许任意类型

    def __init__(self, *tools: BaseTool):
        """初始化工具集合。
        
        参数:
            *tools: 要包含在集合中的工具实例
        """
        self.tools = tools  # 工具列表
        self.tool_map = {tool.name: tool for tool in tools}  # 工具名称到工具实例的映射

    def __iter__(self):
        """实现集合的迭代功能，允许直接迭代工具对象。"""
        return iter(self.tools)

    def to_params(self) -> List[Dict[str, Any]]:
        """将所有工具转换为参数格式，供语言模型使用。
        
        返回:
            包含所有工具参数的列表
        """
        return [tool.to_param() for tool in self.tools]

    async def execute(
        self, *, name: str, tool_input: Dict[str, Any] = None
    ) -> ToolResult:
        """根据名称执行指定的工具。
        
        参数:
            name: 要执行的工具名称
            tool_input: 传递给工具的输入参数
            
        返回:
            工具执行结果或失败信息
        """
        # 从映射中获取工具
        tool = self.tool_map.get(name)
        if not tool:
            # 如果工具不存在，返回失败结果
            return ToolFailure(error=f"Tool {name} is invalid")
        try:
            # 执行工具并返回结果
            result = await tool(**tool_input)
            return result
        except ToolError as e:
            # 捕获工具错误并返回失败结果
            return ToolFailure(error=e.message)

    async def execute_all(self) -> List[ToolResult]:
        """按顺序执行集合中的所有工具。
        
        返回:
            所有工具执行结果的列表
        """
        results = []
        for tool in self.tools:
            try:
                # 执行工具并收集结果
                result = await tool()
                results.append(result)
            except ToolError as e:
                # 捕获工具错误并添加失败结果
                results.append(ToolFailure(error=e.message))
        return results

    def get_tool(self, name: str) -> BaseTool:
        """根据名称获取工具实例。
        
        参数:
            name: 工具名称
            
        返回:
            工具实例或 None（如果工具不存在）
        """
        return self.tool_map.get(name)

    def add_tool(self, tool: BaseTool):
        """将单个工具添加到集合中。

        如果已存在同名工具，将跳过并记录警告。
        
        参数:
            tool: 要添加的工具实例
            
        返回:
            工具集合自身，支持链式调用
        """
        # 检查是否已存在同名工具
        if tool.name in self.tool_map:
            logger.warning(f"Tool {tool.name} already exists in collection, skipping")
            return self

        # 添加工具到工具列表和映射
        self.tools += (tool,)
        self.tool_map[tool.name] = tool
        return self

    def add_tools(self, *tools: BaseTool):
        """将多个工具添加到集合中。

        如果有工具与现有工具名称冲突，将跳过并记录警告。
        
        参数:
            *tools: 要添加的工具实例
            
        返回:
            工具集合自身，支持链式调用
        """
        # 逐个添加工具
        for tool in tools:
            self.add_tool(tool)
        return self
