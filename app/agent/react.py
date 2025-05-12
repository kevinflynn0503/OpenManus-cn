"""
ReAct 代理模块

这个模块实现了 ReActAgent 类，该类基于 ReAct 模式（思考-行动-观察）实现代理的核心递归执行逻辑。
这是一个抽象基类，需要子类实现 think 和 act 方法。
ReActAgent 是 ToolCallAgent 的父类，提供了思考-行动循环的基础框架。
"""

from abc import ABC, abstractmethod
from typing import Optional

from pydantic import Field

from app.agent.base import BaseAgent
from app.llm import LLM
from app.schema import AgentState, Memory


class ReActAgent(BaseAgent, ABC):
    """基于 ReAct 模式的代理抽象基类。
    
    这个类实现了 ReAct 思考-行动-观察模式的基本框架，它需要子类实现思考和行动的具体逻辑。
    它继承自 BaseAgent 并添加了 ReAct 模式特有的属性和方法。
    
    ReAct 模式的三个核心阶段：
    1. 思考(Reasoning): 理解当前状态并决定下一步行动
    2. 行动(Acting): 执行选定的行动
    3. 观察(Observing): 观察行动的结果并更新内部状态
    """
    # 代理名称
    name: str
    # 代理描述（可选）
    description: Optional[str] = None

    # 提示词设置
    system_prompt: Optional[str] = None  # 系统全局提示词
    next_step_prompt: Optional[str] = None  # 下一步提示词

    # 代理核心组件
    llm: Optional[LLM] = Field(default_factory=LLM)  # 语言模型实例
    memory: Memory = Field(default_factory=Memory)  # 代理内存
    state: AgentState = AgentState.IDLE  # 初始状态为空闲

    # 执行控制
    max_steps: int = 10  # 最大步骤数
    current_step: int = 0  # 当前步骤

    @abstractmethod
    async def think(self) -> bool:
        """处理当前状态并决定下一步行动。
        
        这是 ReAct 模式的“思考”阶段，需要子类实现。
        该方法应分析当前情况并决定是否需要采取行动。
        
        返回:
            bool: 如果需要执行行动返回 True，否则返回 False。
        """

    @abstractmethod
    async def act(self) -> str:
        """执行已决定的行动。
        
        这是 ReAct 模式的“行动”阶段，需要子类实现。
        该方法应执行先前在思考阶段定义的行动。
        
        返回:
            str: 执行行动的结果或观察内容。
        """

    async def step(self) -> str:
        """执行单个步骤：思考和行动。
        
        这个方法实现了 ReAct 模式的完整循环：先思考，如果需要则执行行动。
        它协调了 think 和 act 方法的调用序列。
        
        返回:
            str: 步骤执行的结果或观察内容。
        """
        # 先执行思考阶段并决定是否需要行动
        should_act = await self.think()
        # 如果不需要行动，返回完成思考的消息
        if not should_act:
            return "Thinking complete - no action needed"
        # 如果需要行动，执行行动并返回结果
        return await self.act()
