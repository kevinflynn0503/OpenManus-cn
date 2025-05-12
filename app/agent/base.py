"""
基础代理类模块

这个文件定义了 OpenManus 的基础代理类 (BaseAgent)，该类是所有代理的抽象基类。
它提供了状态管理、内存管理和基于步骤的执行循环等基础功能。
所有特定代理实现都继承自这个基础类并扩展其功能。
"""

from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator

from app.llm import LLM
from app.logger import logger
from app.sandbox.client import SANDBOX_CLIENT
from app.schema import ROLE_TYPE, AgentState, Memory, Message


class BaseAgent(BaseModel, ABC):
    """管理代理状态和执行的抽象基类。

    提供状态转换、内存管理和基于步骤的执行循环的基础功能。
    子类必须实现 `step` 方法。
    """

    # 核心属性
    name: str = Field(..., description="Unique name of the agent")
    description: Optional[str] = Field(None, description="Optional agent description")

    # 提示词配置
    system_prompt: Optional[str] = Field(
        None, description="System-level instruction prompt"
    )
    next_step_prompt: Optional[str] = Field(
        None, description="Prompt for determining next action"
    )

     # 依赖项
    llm: LLM = Field(default_factory=LLM, description="Language model instance")
    memory: Memory = Field(default_factory=Memory, description="Agent's memory store")
    state: AgentState = Field(
        default=AgentState.IDLE, description="Current agent state"
    )

    # 执行控制
    max_steps: int = Field(default=10, description="Maximum steps before termination")
    current_step: int = Field(default=0, description="Current step in execution")

    # 用于检测循环的重复阈值，当重复内容达到该阈值时认为代理卡住了
    duplicate_threshold: int = 2

    class Config:
        arbitrary_types_allowed = True  # 允许任意类型
        extra = "allow"  # 允许子类中的额外字段，增强灵活性

    @model_validator(mode="after")
    def initialize_agent(self) -> "BaseAgent":
        """如果未提供，使用默认设置初始化代理。"""
        # 确保 LLM 实例正确初始化
        if self.llm is None or not isinstance(self.llm, LLM):
            self.llm = LLM(config_name=self.name.lower())
        # 确保内存正确初始化
        if not isinstance(self.memory, Memory):
            self.memory = Memory()
        return self

    @asynccontextmanager
    async def state_context(self, new_state: AgentState):
        """用于安全代理状态转换的上下文管理器。

        这个方法提供了一个安全的方式来临时改变代理的状态并在操作完成后自动恢复，
        或在发生异常时转为错误状态。

        参数:
            new_state: 在上下文期间要转换到的状态。

        产出:
            None: 允许在新状态下执行操作。

        异常:
            ValueError: 如果 new_state 无效。
        """
        # 验证状态类型是否合法
        if not isinstance(new_state, AgentState):
            raise ValueError(f"Invalid state: {new_state}")

        # 保存当前状态并设置新状态
        previous_state = self.state
        self.state = new_state
        try:
            # 运行上下文内的代码
            yield
        except Exception as e:
            # 异常时转为错误状态
            self.state = AgentState.ERROR  # 失败时转为错误状态
            raise e
        finally:
            # 在所有情况下恢复为原始状态
            self.state = previous_state  # 恢复为先前状态

    def update_memory(
        self,
        role: ROLE_TYPE,  # type: ignore
        content: str,
        base64_image: Optional[str] = None,
        **kwargs,
    ) -> None:
        """将消息添加到代理的内存中。

        这个方法允许将不同角色(用户、系统、助手、工具)的消息添加到代理的内存中，
        以跟踪与用户或其他组件的交互历史。

        参数:
            role: 消息发送者的角色(用户、系统、助手、工具)。
            content: 消息内容。
            base64_image: 可选的 base64 编码图像。
            **kwargs: 额外参数(例如工具消息的 tool_call_id)。

        异常:
            ValueError: 如果角色不受支持。
        """
        # 角色到消息创建函数的映射
        message_map = {
            "user": Message.user_message,          # 用户消息
            "system": Message.system_message,      # 系统消息
            "assistant": Message.assistant_message, # 助手消息
            "tool": lambda content, **kw: Message.tool_message(content, **kw), # 工具消息
        }

        # 检查角色是否受支持
        if role not in message_map:
            raise ValueError(f"Unsupported message role: {role}")

        # 根据角色创建带有适当参数的消息
        kwargs = {"base64_image": base64_image, **(kwargs if role == "tool" else {})}
        self.memory.add_message(message_map[role](content, **kwargs))

    async def run(self, request: Optional[str] = None) -> str:
        """异步执行代理的主循环。

        这个方法是代理执行的核心入口点，它管理整个执行周期，包括状态转换、
        步骤执行、卡住检测和资源清理。

        参数:
            request: 可选的初始用户请求。

        返回:
            一个字符串，概括执行结果。

        异常:
            RuntimeError: 如果代理不在空闲(IDLE)状态下启动。
        """
        # 验证代理当前状态是否为空闲状态
        if self.state != AgentState.IDLE:
            raise RuntimeError(f"Cannot run agent from state: {self.state}")

        # 如果提供了初始请求，将其添加到内存中
        if request:
            self.update_memory("user", request)

        # 用于收集每个步骤的结果
        results: List[str] = []
        # 使用状态上下文管理器将代理设置为运行状态
        async with self.state_context(AgentState.RUNNING):
            # 循环执行直到达到最大步骤数或代理完成
            while (
                self.current_step < self.max_steps and self.state != AgentState.FINISHED
            ):
                # 增加当前步骤计数
                self.current_step += 1
                logger.info(f"Executing step {self.current_step}/{self.max_steps}")
                # 执行单个步骤(由子类实现)
                step_result = await self.step()

                # 检查是否处于卡住状态
                if self.is_stuck():
                    self.handle_stuck_state()

                # 收集步骤结果
                results.append(f"Step {self.current_step}: {step_result}")

            # 如果达到最大步骤数，重置状态并记录终止信息
            if self.current_step >= self.max_steps:
                self.current_step = 0
                self.state = AgentState.IDLE
                results.append(f"Terminated: Reached max steps ({self.max_steps})")
        # 清理沙箱客户端资源
        await SANDBOX_CLIENT.cleanup()
        # 返回所有步骤结果的合并字符串
        return "\n".join(results) if results else "No steps executed"

    @abstractmethod
    async def step(self) -> str:
        """执行代理工作流程中的单个步骤。

        这是一个抽象方法，必须由子类实现以定义特定的行为。
        每个具体的代理实现都必须提供其自己的 step 方法实现。
        """

    def handle_stuck_state(self):
        """通过添加提示来处理卡住状态，鼓励代理改变策略。"""
        # 定义卡住状态下的特殊提示词，帮助代理改变策略
        stuck_prompt = "\
        Observed duplicate responses. Consider new strategies and avoid repeating ineffective paths already attempted."
        # 将卡住提示添加到下一步提示中
        self.next_step_prompt = f"{stuck_prompt}\n{self.next_step_prompt}"
        logger.warning(f"Agent detected stuck state. Added prompt: {stuck_prompt}")

    def is_stuck(self) -> bool:
        """通过检测重复内容来检查代理是否处于循环卡住状态。"""
        # 如果消息数量不足，不可能卡住
        if len(self.memory.messages) < 2:
            return False

        # 获取最后一条消息
        last_message = self.memory.messages[-1]
        # 如果最后一条消息没有内容，不可能卡住
        if not last_message.content:
            return False

        # 计算相同内容的出现次数
        duplicate_count = sum(
            1
            for msg in reversed(self.memory.messages[:-1])
            if msg.role == "assistant" and msg.content == last_message.content
        )

        # 如果重复计数超过或等于阈值，则认为卡住
        return duplicate_count >= self.duplicate_threshold

    @property
    def messages(self) -> List[Message]:
        """从代理的内存中检索消息列表。
        
        这个属性提供了直接访问代理内存消息的方式。
        """
        return self.memory.messages

    @messages.setter
    def messages(self, value: List[Message]):
        """设置代理内存中的消息列表。
        
        这个属性设置器允许直接覆盖代理的全部消息历史。
        """
        self.memory.messages = value
