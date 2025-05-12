"""基础工具类模块

该模块定义了 OpenManus 系统中工具的基础类和结果模型。
所有具体工具都继承自 BaseTool 类并实现其抽象方法。
工具执行的结果通过 ToolResult 类及其子类来表示。
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class BaseTool(ABC, BaseModel):
    """所有工具的基础抽象类。
    
    这个类定义了工具的基本属性和方法接口，
    所有具体工具实现都必须继承自这个类。
    """
    name: str  # 工具名称
    description: str  # 工具描述
    parameters: Optional[dict] = None  # 工具参数模式

    class Config:
        arbitrary_types_allowed = True  # 允许任意类型

    async def __call__(self, **kwargs) -> Any:
        """使用给定参数执行工具。
        
        这个方法允许工具实例可以像函数一样直接调用。
        例如: `result = await my_tool(param1="value1")`
        """
        return await self.execute(**kwargs)

    @abstractmethod
    async def execute(self, **kwargs) -> Any:
        """使用给定参数执行工具。
        
        这是一个抽象方法，必须由子类实现。
        子类应该在这个方法中实现具体的工具逻辑。
        """

    def to_param(self) -> Dict:
        """将工具转换为函数调用格式。
        
        将工具属性转换为适用于语言模型工具调用格式的字典。
        返回的字典符合 OpenAI 或类似模型的函数调用格式要求。
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolResult(BaseModel):
    """表示工具执行结果的类。
    
    这个类封装了工具执行的返回值，包括正常输出、错误信息、
    图像数据和系统信息等。
    """

    output: Any = Field(default=None)  # 工具执行的输出结果
    error: Optional[str] = Field(default=None)  # 错误信息（如果有）
    base64_image: Optional[str] = Field(default=None)  # 可选的 base64 编码图像
    system: Optional[str] = Field(default=None)  # 系统相关信息

    class Config:
        arbitrary_types_allowed = True  # 允许任意类型

    def __bool__(self):
        """定义布尔运算的行为。
        
        如果任何字段有值，则返回 True，否则返回 False。
        这允许直接使用 if result: 这样的判断。
        """
        return any(getattr(self, field) for field in self.__fields__)

    def __add__(self, other: "ToolResult"):
        """定义两个工具结果的加法运算。
        
        允许将多个工具结果组合在一起，例如 result1 + result2。
        """
        def combine_fields(
            field: Optional[str], other_field: Optional[str], concatenate: bool = True
        ):
            """组合两个字段的内部辅助函数。"""
            if field and other_field:
                if concatenate:
                    return field + other_field
                raise ValueError("Cannot combine tool results")
            return field or other_field

        # 创建新的组合结果
        return ToolResult(
            output=combine_fields(self.output, other.output),
            error=combine_fields(self.error, other.error),
            base64_image=combine_fields(self.base64_image, other.base64_image, False),
            system=combine_fields(self.system, other.system),
        )

    def __str__(self):
        """定义工具结果的字符串表示。
        
        如果有错误，返回错误信息；否则返回输出结果。
        """
        return f"Error: {self.error}" if self.error else self.output

    def replace(self, **kwargs):
        """返回一个字段被替换后的新 ToolResult 实例。
        
        这个方法允许创建当前结果的变体，可以替换特定字段。
        """
        # return self.copy(update=kwargs)
        return type(self)(**{**self.dict(), **kwargs})


class CLIResult(ToolResult):
    """可以渲染为 CLI 输出的工具结果。
    
    这是一个专门为命令行工具设计的结果类。
    """


class ToolFailure(ToolResult):
    """表示失败的工具结果。
    
    当工具执行失败时，使用这个类来表示结果。
    通常包含错误信息。
    """
