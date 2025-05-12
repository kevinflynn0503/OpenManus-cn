# -*- coding: utf-8 -*-
"""
执行流程基础模块

该模块定义了执行流程的基础类，用于支持多个代理的协作和流程管理。
"""

from abc import ABC, abstractmethod  # 用于创建抽象基类和抽象方法
from typing import Dict, List, Optional, Union  # 类型注解

from pydantic import BaseModel  # 用于数据验证和设置

from app.agent.base import BaseAgent  # 导入代理基类


class BaseFlow(BaseModel, ABC):
    """支持多代理的执行流程基类
    
    该基类提供了执行流程的基础功能，允许多个代理协同工作。
    它继承了Pydantic的BaseModel用于数据验证，并且是一个抽象基类（ABC）。
    """

    agents: Dict[str, BaseAgent]  # 代理字典，键是代理名，值是BaseAgent实例
    tools: Optional[List] = None  # 可选的工具列表
    primary_agent_key: Optional[str] = None  # 主要代理的键名，可选

    class Config:
        arbitrary_types_allowed = True  # 允许任意类型作为属性

    def __init__(
        self, agents: Union[BaseAgent, List[BaseAgent], Dict[str, BaseAgent]], **data
    ):
        """初始化执行流程
        
        支持多种方式提供代理：单个代理、代理列表或代理字典。
        
        Args:
            agents: 可以是单个代理实例、代理列表或代理字典
            **data: 其他配置数据
        """
        # 处理不同方式提供的代理
        if isinstance(agents, BaseAgent):
            # 如果是单个代理，创建以"default"为键的字典
            agents_dict = {"default": agents}
        elif isinstance(agents, list):
            # 如果是代理列表，使用agent_0, agent_1等作为键
            agents_dict = {f"agent_{i}": agent for i, agent in enumerate(agents)}
        else:
            # 如果本身就是字典，直接使用
            agents_dict = agents

        # 如果没有指定主要代理，使用第一个代理
        primary_key = data.get("primary_agent_key")
        if not primary_key and agents_dict:
            primary_key = next(iter(agents_dict))  # 获取字典的第一个键
            data["primary_agent_key"] = primary_key

        # 设置代理字典
        data["agents"] = agents_dict

        # 使用BaseModel的初始化方法
        super().__init__(**data)

    @property
    def primary_agent(self) -> Optional[BaseAgent]:
        """获取流程的主要代理
        
        返回当前指定为主要代理的实例。如果主要代理不存在，则返回None。
        
        Returns:
            主要代理实例或None
        """
        return self.agents.get(self.primary_agent_key)

    def get_agent(self, key: str) -> Optional[BaseAgent]:
        """根据键获取特定的代理
        
        通过提供的键从代理字典中检索并返回对应的代理实例。
        
        Args:
            key: 要检索的代理键名
            
        Returns:
            对应的代理实例或None（如果不存在）
        """
        return self.agents.get(key)

    def add_agent(self, key: str, agent: BaseAgent) -> None:
        """向流程添加新的代理
        
        使用指定的键将新代理添加到代理字典中。如果键已存在，将覆盖原有代理。
        
        Args:
            key: 代理的键名
            agent: 要添加的代理实例
        """
        self.agents[key] = agent

    @abstractmethod
    async def execute(self, input_text: str) -> str:
        """使用给定输入执行流程
        
        这是一个抽象方法，必须由子类实现。实现应处理流程的执行逻辑。
        
        Args:
            input_text: 输入文本，用于触发流程执行
            
        Returns:
            流程执行的结果文本
        """
        pass
