"""结构化聊天完成工具模块。

该模块提供了一个工具，用于生成具有特定结构和格式的聊天补全。
它能够根据指定的返回类型（字符串、列表、字典或Pydantic模型）自动构建适当的JSON Schema。
"""

from typing import Any, List, Optional, Type, Union, get_args, get_origin

from pydantic import BaseModel, Field

from app.tool import BaseTool


class CreateChatCompletion(BaseTool):
    """构建结构化聊天补全的工具类。
    
    该类允许生成符合特定结构和格式要求的输出，使用JSON Schema进行参数验证和格式化。
    """
    name: str = "create_chat_completion"  # 工具名称
    description: str = (
        "Creates a structured completion with specified output formatting."  # 工具描述
    )

    # Python类型映射到JSON Schema类型
    type_mapping: dict = {
        str: "string",     # 字符串类型
        int: "integer",    # 整数类型
        float: "number",   # 浮点数类型
        bool: "boolean",   # 布尔类型
        dict: "object",    # 字典/对象类型
        list: "array",     # 列表/数组类型
    }
    response_type: Optional[Type] = None  # 响应类型
    required: List[str] = Field(default_factory=lambda: ["response"])  # 必需的字段列表

    def __init__(self, response_type: Optional[Type] = str):
        """使用指定的响应类型初始化工具。
        
        参数:
            response_type: 期望的响应类型，默认为字符串类型
        """
        super().__init__()
        self.response_type = response_type  # 设置响应类型
        self.parameters = self._build_parameters()  # 构建JSON Schema参数

    def _build_parameters(self) -> dict:
        """根据响应类型构建参数Schema。
        
        返回:
            dict: 构建的JSON Schema参数定义
        """
        # 当响应类型为字符串时的特殊处理
        if self.response_type == str:
            return {
                "type": "object",
                "properties": {
                    "response": {
                        "type": "string",
                        "description": "The response text that should be delivered to the user.",
                    },
                },
                "required": self.required,
            }

        # 当响应类型为Pydantic模型类时，直接使用其JSON Schema
        if isinstance(self.response_type, type) and issubclass(
            self.response_type, BaseModel
        ):
            schema = self.response_type.model_json_schema()  # 获取模型的Schema
            return {
                "type": "object",
                "properties": schema["properties"],  # 使用模型定义的属性
                "required": schema.get("required", self.required),  # 使用模型定义的必需字段，或默认必需字段
            }

        # 处理其他类型，如列表、字典、联合类型等
        return self._create_type_schema(self.response_type)

    def _create_type_schema(self, type_hint: Type) -> dict:
        """为给定类型创建JSON Schema。
        
        参数:
            type_hint: 类型提示，如list, dict, Union等
            
        返回:
            dict: 构建的JSON Schema
        """
        origin = get_origin(type_hint)  # 获取原始类型，如List[str]的origin是list
        args = get_args(type_hint)      # 获取类型参数，如List[str]的args是(str,)

        # 处理基本类型（如int、str等非泛型类型）
        if origin is None:
            return {
                "type": "object",
                "properties": {
                    "response": {
                        "type": self.type_mapping.get(type_hint, "string"),  # 使用类型映射获取对应的JSON类型
                        "description": f"Response of type {type_hint.__name__}",
                    }
                },
                "required": self.required,
            }

        # 处理列表类型（List）
        if origin is list:
            item_type = args[0] if args else Any  # 获取列表元素类型，如果未指定则使用Any
            return {
                "type": "object",
                "properties": {
                    "response": {
                        "type": "array",
                        "items": self._get_type_info(item_type),  # 递归处理元素类型
                    }
                },
                "required": self.required,
            }

        # 处理字典类型（Dict）
        if origin is dict:
            value_type = args[1] if len(args) > 1 else Any  # 获取字典值类型
            return {
                "type": "object",
                "properties": {
                    "response": {
                        "type": "object",
                        "additionalProperties": self._get_type_info(value_type),  # 递归处理值类型
                    }
                },
                "required": self.required,
            }

        # 处理联合类型（Union）
        if origin is Union:
            return self._create_union_schema(args)  # 调用处理联合类型的方法

        # 如果是不支持的类型，回退到默认参数
        return self._build_parameters()

    def _get_type_info(self, type_hint: Type) -> dict:
        """获取单一类型的类型信息。
        
        参数:
            type_hint: 类型提示
            
        返回:
            dict: 包含类型信息的字典
        """
        # 如果是 Pydantic 模型类，直接返回其 JSON Schema
        if isinstance(type_hint, type) and issubclass(type_hint, BaseModel):
            return type_hint.model_json_schema()

        # 否则返回基本类型信息
        return {
            "type": self.type_mapping.get(type_hint, "string"),  # 获取类型的JSON类型名称
            "description": f"Value of type {getattr(type_hint, '__name__', 'any')}",  # 添加类型描述
        }

    def _create_union_schema(self, types: tuple) -> dict:
        """创建联合类型（Union）的Schema。
        
        参数:
            types: 联合类型中的类型元组
            
        返回:
            dict: 包含联合类型定义的Schema
        """
        # 使用JSON Schema的anyOf表示多种可能类型
        return {
            "type": "object",
            "properties": {
                "response": {"anyOf": [self._get_type_info(t) for t in types]}  # 对每个联合类型成员递归处理
            },
            "required": self.required,
        }

    async def execute(self, required: list | None = None, **kwargs) -> Any:
        """执行聊天补全并进行类型转换。

        根据设置的响应类型，处理并转换输入的数据。

        参数:
            required: 必需字段名称列表或None
            **kwargs: 响应数据

        返回:
            根据响应类型转换的结果
        """
        # 使用提供的必需字段列表或默认的必需字段
        required = required or self.required

        # 处理必需字段是列表的情况
        if isinstance(required, list) and len(required) > 0:
            if len(required) == 1:  # 只有一个必需字段
                required_field = required[0]  # 获取必需字段名
                result = kwargs.get(required_field, "")  # 获取字段值，如果不存在则返回空字符串
            else:  # 有多个必需字段
                # 返回包含多个字段的字典
                return {field: kwargs.get(field, "") for field in required}
        else:  # 没有必需字段列表时使用默认字段“response”
            required_field = "response"
            result = kwargs.get(required_field, "")

        # 类型转换逻辑
        if self.response_type == str:  # 如果响应类型是字符串，直接返回结果
            return result

        # 如果响应类型是Pydantic模型，创建模型实例
        if isinstance(self.response_type, type) and issubclass(
            self.response_type, BaseModel
        ):
            return self.response_type(**kwargs)  # 使用关键字参数创建模型实例

        # 如果是列表或字典类型，假设结果已经是正确格式
        if get_origin(self.response_type) in (list, dict):
            return result  # 假定结果已经是正确的格式

        # 尝试转换到目标类型，比如将字符串转换为整数
        try:
            return self.response_type(result)  # 尝试进行类型转换
        except (ValueError, TypeError):  # 如果转换失败，返回原始结果
            return result
