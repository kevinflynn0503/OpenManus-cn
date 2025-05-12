# -*- coding: utf-8 -*-
"""
软件工程代理模块

该模块实现了软件工程代理(SWEAgent)，用于自主执行代码和进行自然语言对话。
代理集成了终端命令、文本编辑和终止等工具，能够直接与计算机交互来解决任务。
"""

from typing import List  # 类型注解

from pydantic import Field  # 数据验证工具

from app.agent.toolcall import ToolCallAgent  # 工具调用代理基类
from app.prompt.swe import SYSTEM_PROMPT  # 软件工程代理系统提示
from app.tool import Bash, StrReplaceEditor, Terminate, ToolCollection  # 工具类


class SWEAgent(ToolCallAgent):
    """实现SWEAgent范式的代理，用于执行代码和自然对话。
    
    软件工程代理(SWEAgent)继承了ToolCallAgent类，能够使用终端命令、
    文本编辑和其他工具直接与计算机交互，自主解决编程和开发任务。
    """

    name: str = "swe"  # 代理名称
    description: str = "一个直接与计算机交互来解决任务的自主人工智能程序员"  # 代理描述

    system_prompt: str = SYSTEM_PROMPT  # 系统提示，使用预定义的软件工程代理提示
    next_step_prompt: str = ""  # 下一步提示，保持为空字符串

    # 列出可用工具，包括终端命令、文本编辑器和终止工具
    available_tools: ToolCollection = ToolCollection(
        Bash(),              # 终端命令工具，用于执行命令行命令
        StrReplaceEditor(), # 文本编辑工具，用于编辑文件
        Terminate()         # 终止工具，用于结束代理执行
    )
    # 特殊工具名称列表，这些工具会触发特殊处理，如终止代理
    special_tool_names: List[str] = Field(default_factory=lambda: [Terminate().name])

    max_steps: int = 20  # 最大步骤数，限制代理执行的最大步骤数
