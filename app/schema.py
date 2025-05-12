"""数据模型和架构模块

这个模块定义了 OpenManus 中使用的所有核心数据结构和模型，包括：
1. 消息类型与角色定义（Role、Message）
2. 代理状态枚举（AgentState）
3. 工具使用相关模型（ToolChoice、ToolCall、Function）
4. 内存管理模型（Memory）

所有类都基于 Pydantic，提供运行时类型验证和序列化功能。
"""

from enum import Enum
from typing import Any, List, Literal, Optional, Union

from pydantic import BaseModel, Field


class Role(str, Enum):
    """Message role options"""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


ROLE_VALUES = tuple(role.value for role in Role)
ROLE_TYPE = Literal[ROLE_VALUES]  # type: ignore


class ToolChoice(str, Enum):
    """Tool choice options"""

    NONE = "none"
    AUTO = "auto"
    REQUIRED = "required"


TOOL_CHOICE_VALUES = tuple(choice.value for choice in ToolChoice)
TOOL_CHOICE_TYPE = Literal[TOOL_CHOICE_VALUES]  # type: ignore


class AgentState(str, Enum):
    """Agent execution states"""

    IDLE = "IDLE"
    RUNNING = "RUNNING"
    FINISHED = "FINISHED"
    ERROR = "ERROR"


class Function(BaseModel):
    name: str
    arguments: str


class ToolCall(BaseModel):
    """Represents a tool/function call in a message"""

    id: str
    type: str = "function"
    function: Function


class Message(BaseModel):
    """表示对话中的消息。
    
    这个类是 OpenManus 中实现不同角色（用户、系统、助手、工具）间通信的基础结构。
    它支持文本内容、工具调用和多模态内容（图像），与 LLM API 格式兼容。
    该类提供了多种工厂方法来创建不同类型的消息，以及操作符重载以方便消息的组合。
    """

    role: ROLE_TYPE = Field(...)  # type: ignore  # 消息发送者角色（用户、系统、助手、工具）
    content: Optional[str] = Field(default=None)  # 消息文本内容
    tool_calls: Optional[List[ToolCall]] = Field(default=None)  # 工具调用列表
    name: Optional[str] = Field(default=None)  # 发送者名称（主要用于工具消息）
    tool_call_id: Optional[str] = Field(default=None)  # 工具调用ID（用于工具消息）
    base64_image: Optional[str] = Field(default=None)  # base64编码的图像（用于多模态消息）

    def __add__(self, other) -> List["Message"]:
        """重载加号操作符，支持 Message + list 或 Message + Message 的操作。
        
        这个方法允许消息对象与列表或另一个消息对象直接相加，结果是一个新的消息列表。
        
        参数:
            other: 要相加的对象（列表或另一个消息对象）
            
        返回:
            List["Message"]: 包含所有消息的新列表
            
        异常:
            TypeError: 如果不支持的类型被用于加法操作
        """
        if isinstance(other, list):
            return [self] + other
        elif isinstance(other, Message):
            return [self, other]
        else:
            raise TypeError(
                f"unsupported operand type(s) for +: '{type(self).__name__}' and '{type(other).__name__}'"
            )

    def __radd__(self, other) -> List["Message"]:
        """重载右侧加号操作符，支持 list + Message 的操作。
        
        这个方法允许列表与消息对象直接相加，结果是一个新的消息列表。
        
        参数:
            other: 要相加的对象（应为列表）
            
        返回:
            List["Message"]: 包含所有消息的新列表
            
        异常:
            TypeError: 如果不支持的类型被用于加法操作
        """
        if isinstance(other, list):
            return other + [self]
        else:
            raise TypeError(
                f"unsupported operand type(s) for +: '{type(other).__name__}' and '{type(self).__name__}'"
            )

    def to_dict(self) -> dict:
        """将消息转换为字典格式。
        
        这个方法将消息对象转换为与 LLM API 兼容的字典格式，
        只包含非空字段。
        
        返回:
            dict: 消息的字典表示
        """
        # 初始化基本字段
        message = {"role": self.role}
        # 根据实际情况添加非空字段
        if self.content is not None:
            message["content"] = self.content
        if self.tool_calls is not None:
            message["tool_calls"] = [tool_call.dict() for tool_call in self.tool_calls]
        if self.name is not None:
            message["name"] = self.name
        if self.tool_call_id is not None:
            message["tool_call_id"] = self.tool_call_id
        if self.base64_image is not None:
            message["base64_image"] = self.base64_image
        return message

    @classmethod
    def user_message(
        cls, content: str, base64_image: Optional[str] = None
    ) -> "Message":
        """创建用户消息。
        
        这个方法创建一个用户角色的消息，可选地包含图像。
        
        参数:
            content: 消息文本内容
            base64_image: 可选的 base64 编码图像
            
        返回:
            Message: 新的用户消息实例
        """
        return cls(role=Role.USER, content=content, base64_image=base64_image)

    @classmethod
    def system_message(cls, content: str) -> "Message":
        """创建系统消息。
        
        这个方法创建一个系统角色的消息，用于设置提示词或指令。
        
        参数:
            content: 系统消息文本内容
            
        返回:
            Message: 新的系统消息实例
        """
        return cls(role=Role.SYSTEM, content=content)

    @classmethod
    def assistant_message(
        cls, content: Optional[str] = None, base64_image: Optional[str] = None
    ) -> "Message":
        """创建助手消息。
        
        这个方法创建一个助手角色的消息，可以包含文本和图像。
        
        参数:
            content: 可选的消息文本内容
            base64_image: 可选的 base64 编码图像
            
        返回:
            Message: 新的助手消息实例
        """
        return cls(role=Role.ASSISTANT, content=content, base64_image=base64_image)

    @classmethod
    def tool_message(
        cls, content: str, name, tool_call_id: str, base64_image: Optional[str] = None
    ) -> "Message":
        """创建工具消息。
        
        这个方法创建一个工具角色的消息，代表工具执行的结果。
        
        参数:
            content: 工具返回的消息内容
            name: 工具名称
            tool_call_id: 对应的工具调用 ID
            base64_image: 可选的 base64 编码图像结果
            
        返回:
            Message: 新的工具消息实例
        """
        return cls(
            role=Role.TOOL,
            content=content,
            name=name,
            tool_call_id=tool_call_id,
            base64_image=base64_image,
        )

    @classmethod
    def from_tool_calls(
        cls,
        tool_calls: List[Any],
        content: Union[str, List[str]] = "",
        base64_image: Optional[str] = None,
        **kwargs,
    ):
        """从原始工具调用创建助手工具调用消息。

        这个方法将来自 LLM 的原始工具调用转换为标准格式的 Message 对象，
        主要用于处理模型返回的工具调用。

        参数:
            tool_calls: 来自 LLM 的原始工具调用列表
            content: 可选的消息文本内容
            base64_image: 可选的 base64 编码图像
            **kwargs: 其他参数
            
        返回:
            Message: 新的助手消息实例，包含格式化的工具调用
        """
        # 将原始工具调用转换为标准格式
        formatted_calls = [
            {"id": call.id, "function": call.function.model_dump(), "type": "function"}
            for call in tool_calls
        ]
        # 创建助手消息并返回
        return cls(
            role=Role.ASSISTANT,
            content=content,
            tool_calls=formatted_calls,
            base64_image=base64_image,
            **kwargs,
        )


class Memory(BaseModel):
    """代理内存类，负责管理消息历史和会话上下文。
    
    这个类管理代理与用户、工具和其他组件的对话历史，提供了存储、检索和管理消息的功能。
    它支持添加单个或多个消息、清除消息历史、获取最近消息和转换为字典格式。
    为防止内存溢出，它还实现了消息数量的限制。
    """
    # 消息列表，默认为空列表
    messages: List[Message] = Field(default_factory=list)
    # 消息存储的最大数量，超过时会移除最早的消息
    max_messages: int = Field(default=100)

    def add_message(self, message: Message) -> None:
        """将单个消息添加到内存中。
        
        这个方法添加一条消息到内存中，并确保消息数量不超过限制。
        如果超过了 max_messages，会移除最早的消息以保持限制。
        
        参数:
            message: 要添加的消息对象
        """
        # 添加消息到列表末尾
        self.messages.append(message)
        # 如果消息数量超过限制，则只保留最新的 max_messages 条
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages :]

    def add_messages(self, messages: List[Message]) -> None:
        """添加多条消息到内存中。
        
        这个方法批量添加多条消息到内存中，同样确保消息数量不超过限制。
        
        参数:
            messages: 要添加的消息对象列表
        """
        # 扩展消息列表
        self.messages.extend(messages)
        # 如果消息数量超过限制，则只保留最新的 max_messages 条
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages :]

    def clear(self) -> None:
        """清除所有消息。
        
        这个方法将清除内存中的所有消息历史。
        """
        # 清空消息列表
        self.messages.clear()

    def get_recent_messages(self, n: int) -> List[Message]:
        """获取最近 n 条消息。
        
        参数:
            n: 要检索的消息数量
            
        返回:
            List[Message]: 最近 n 条消息的列表
        """
        # 返回最近 n 条消息
        return self.messages[-n:]

    def to_dict_list(self) -> List[dict]:
        """将消息列表转换为字典列表。
        
        这个方法将所有 Message 对象转换为字典格式，便于序列化和 API 交互。
        
        返回:
            List[dict]: 消息对象转换为字典格式的列表
        """
        # 使用列表推导式将每个消息对象转换为字典
        return [msg.to_dict() for msg in self.messages]
