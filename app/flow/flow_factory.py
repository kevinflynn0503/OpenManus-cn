# -*- coding: utf-8 -*-
"""
流程工厂模块

该模块实现了流程工厂类，用于创建不同类型的执行流程实例。
工厂模式允许根据指定的流程类型创建相应的流程对象。
"""

from enum import Enum  # 用于创建枚举类型
from typing import Dict, List, Union  # 类型注解

from app.agent.base import BaseAgent  # 代理基类
from app.flow.base import BaseFlow  # 流程基类
from app.flow.planning import PlanningFlow  # 规划流程实现


class FlowType(str, Enum):
    """流程类型枚举
    
    定义了系统支持的不同流程类型。
    继承str和Enum，使每个枚举值都是字符串类型。
    """
    PLANNING = "planning"  # 规划型流程，用于执行多步骤规划


class FlowFactory:
    """创建支持多代理的不同类型流程的工厂类
    
    该工厂类提供了创建不同类型流程实例的方法。
    它通过隐藏流程的创建细节，使客户端代码只需要指定流程类型和代理即可创建适当的流程实例。
    """

    @staticmethod
    def create_flow(
        flow_type: FlowType,
        agents: Union[BaseAgent, List[BaseAgent], Dict[str, BaseAgent]],
        **kwargs,
    ) -> BaseFlow:
        """创建指定类型的流程实例
        
        根据提供的流程类型和代理，创建并返回相应的流程实例。
        
        Args:
            flow_type: 流程类型，来自FlowType枚举
            agents: 代理，可以是单个代理、代理列表或代理字典
            **kwargs: 传递给流程构造函数的其他参数
            
        Returns:
            创建的流程实例
            
        Raises:
            ValueError: 当指定的流程类型不存在时抛出
        """
        # 定义流程类型到流程类的映射
        flows = {
            FlowType.PLANNING: PlanningFlow,  # 规划流程
        }

        # 获取对应的流程类
        flow_class = flows.get(flow_type)
        if not flow_class:
            # 如果流程类型不存在，抛出异常
            raise ValueError(f"Unknown flow type: {flow_type}")

        # 实例化并返回流程对象
        return flow_class(agents, **kwargs)
