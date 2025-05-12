# -*- coding: utf-8 -*-
"""
数据分析代理模块

该模块实现了数据分析代理，用于执行各种数据分析任务。
代理集成了Python执行、数据可视化、图表生成等能力。
"""

from pydantic import Field  # 数据验证工具

from app.agent.toolcall import ToolCallAgent  # 工具调用代理基类
from app.config import config  # 应用配置
from app.prompt.visualization import NEXT_STEP_PROMPT, SYSTEM_PROMPT  # 可视化提示模板
from app.tool import Terminate, ToolCollection  # 工具类和工具集合
from app.tool.chart_visualization.chart_prepare import VisualizationPrepare  # 可视化准备工具
from app.tool.chart_visualization.data_visualization import DataVisualization  # 数据可视化工具
from app.tool.chart_visualization.python_execute import NormalPythonExecute  # Python执行工具


class DataAnalysis(ToolCallAgent):
    """数据分析代理类
    
    该代理使用规划方法解决各种数据分析任务。

    该代理扩展了ToolCallAgent，具备一组全面的工具和能力，
    包括数据分析、图表可视化、数据报告等功能。
    """

    name: str = "DataAnalysis"  # 代理名称
    description: str = "一个利用多种工具解决各种数据分析任务的分析代理"  # 代理描述

    # 系统提示，使用配置中的工作区根目录格式化
    system_prompt: str = SYSTEM_PROMPT.format(directory=config.workspace_root)
    next_step_prompt: str = NEXT_STEP_PROMPT  # 下一步提示

    max_observe: int = 15000  # 最大观察数量
    max_steps: int = 20      # 最大步骤数

    # 将通用工具添加到工具集合中
    available_tools: ToolCollection = Field(
        default_factory=lambda: ToolCollection(
            NormalPythonExecute(),    # Python代码执行工具
            VisualizationPrepare(),   # 可视化准备工具
            DataVisualization(),      # 数据可视化工具
            Terminate(),              # 终止工具
        )
    )
