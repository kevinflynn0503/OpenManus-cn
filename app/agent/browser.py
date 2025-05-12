# -*- coding: utf-8 -*-
"""
浏览器代理模块

该模块实现了浏览器代理，用于控制浏览器进行网页操作、内容提取和交互。
代理可以导航、点击元素、填写表单、提取内容等，实现自动化的网页操作。
"""

import json  # 用于处理JSON数据
from typing import TYPE_CHECKING, Optional  # 类型注解

from pydantic import Field, model_validator  # 数据验证和模型验证

from app.agent.toolcall import ToolCallAgent  # 工具调用代理基类
from app.logger import logger  # 日志记录器
from app.prompt.browser import NEXT_STEP_PROMPT, SYSTEM_PROMPT  # 浏览器提示模板
from app.schema import Message, ToolChoice  # 消息和工具选择模型
from app.tool import BrowserUseTool, Terminate, ToolCollection  # 工具类


# 避免当BrowserAgent需要BrowserContextHelper时发生循环导入
if TYPE_CHECKING:
    from app.agent.base import BaseAgent  # 导入代理基类（仅用于类型检查）


class BrowserContextHelper:
    """浏览器上下文助手类
    
    负责管理浏览器状态、格式化提示和清理浏览器资源。
    该类为BrowserAgent提供了与浏览器状态交互的方法。
    """
    
    def __init__(self, agent: "BaseAgent"):
        """初始化浏览器上下文助手
        
        Args:
            agent: 关联的代理实例
        """
        self.agent = agent  # 存储代理实例引用
        self._current_base64_image: Optional[str] = None  # 当前的浏览器截图bae64数据

    async def get_browser_state(self) -> Optional[dict]:
        """获取当前的浏览器状态
        
        使用BrowserUseTool工具执行获取状态操作，并处理返回的数据。
        
        Returns:
            如果成功，返回包含浏览器状态的字典；如果出错，返回None
        """
        # 从代理的可用工具中获取浏览器工具
        browser_tool = self.agent.available_tools.get_tool(BrowserUseTool().name)
        if not browser_tool or not hasattr(browser_tool, "get_current_state"):
            # 如果浏览器工具不存在或没有get_current_state方法
            logger.warning("BrowserUseTool not found or doesn't have get_current_state")
            return None
        try:
            # 尝试获取浏览器状态
            result = await browser_tool.get_current_state()
            if result.error:
                # 如果有错误发生，记录并返回None
                logger.debug(f"Browser state error: {result.error}")
                return None
            # 处理截图数据
            if hasattr(result, "base64_image") and result.base64_image:
                self._current_base64_image = result.base64_image  # 保存截图数据
            else:
                self._current_base64_image = None
            # 解析并返回浏览器状态信息
            return json.loads(result.output)
        except Exception as e:
            # 捕获并记录任何异常
            logger.debug(f"Failed to get browser state: {str(e)}")
            return None

    async def format_next_step_prompt(self) -> str:
        """获取浏览器状态并格式化浏览器提示。
        
        获取当前浏览器状态，处理各种信息（URL、标签页、滚动位置等），
        将截图添加到代理内存中，并格式化下一步提示。
        
        Returns:
            格式化后的下一步提示字符串
        """
        # 获取浏览器状态
        browser_state = await self.get_browser_state()
        # 初始化各种信息变量
        url_info, tabs_info, content_above_info, content_below_info = "", "", "", ""
        results_info = ""  # 或在需要时从代理获取

        if browser_state and not browser_state.get("error"):
            # 格式化URL和标题信息
            url_info = f"\n   URL: {browser_state.get('url', 'N/A')}\n   Title: {browser_state.get('title', 'N/A')}"
            
            # 处理标签页信息
            tabs = browser_state.get("tabs", [])
            if tabs:
                tabs_info = f"\n   {len(tabs)} tab(s) available"
                
            # 处理页面滚动位置信息
            pixels_above = browser_state.get("pixels_above", 0)
            pixels_below = browser_state.get("pixels_below", 0)
            if pixels_above > 0:
                content_above_info = f" ({pixels_above} pixels)"
            if pixels_below > 0:
                content_below_info = f" ({pixels_below} pixels)"

            # 如果有截图数据，添加到代理记忆中
            if self._current_base64_image:
                image_message = Message.user_message(
                    content="Current browser screenshot:",
                    base64_image=self._current_base64_image,
                )
                self.agent.memory.add_message(image_message)
                self._current_base64_image = None  # 添加后清除截图缓存

        # 使用模板格式化下一步提示
        return NEXT_STEP_PROMPT.format(
            url_placeholder=url_info,
            tabs_placeholder=tabs_info,
            content_above_placeholder=content_above_info,
            content_below_placeholder=content_below_info,
            results_placeholder=results_info,
        )

    async def cleanup_browser(self):
        """清理浏览器资源
        
        调用浏览器工具的清理方法来释放浏览器资源，如关闭浏览器实例等。
        """
        # 获取浏览器工具
        browser_tool = self.agent.available_tools.get_tool(BrowserUseTool().name)
        # 如果工具存在且有cleanup方法，调用它
        if browser_tool and hasattr(browser_tool, "cleanup"):
            await browser_tool.cleanup()


class BrowserAgent(ToolCallAgent):
    """浏览器代理类
    
    该代理使用browser_use库控制浏览器执行操作。

    浏览器代理可以导航网页、与元素交互、填写表单、
    提取内容和执行其他基于浏览器的操作来完成任务。
    """

    name: str = "browser"  # 代理名称
    description: str = "一个可以控制浏览器完成任务的代理"  # 代理描述

    system_prompt: str = SYSTEM_PROMPT  # 系统提示
    next_step_prompt: str = NEXT_STEP_PROMPT  # 下一步提示

    max_observe: int = 10000  # 最大观察数量
    max_steps: int = 20  # 最大步骤数

    # 配置可用工具
    available_tools: ToolCollection = Field(
        default_factory=lambda: ToolCollection(BrowserUseTool(), Terminate())
    )

    # 使用Auto设置工具选择，允许同时使用工具和自由形式响应
    tool_choices: ToolChoice = ToolChoice.AUTO
    # 特殊工具名称列表，包含终止工具
    special_tool_names: list[str] = Field(default_factory=lambda: [Terminate().name])

    # 浏览器上下文助手实例
    browser_context_helper: Optional[BrowserContextHelper] = None

    @model_validator(mode="after")
    def initialize_helper(self) -> "BrowserAgent":
        """初始化浏览器上下文助手
        
        在模型验证后创建BrowserContextHelper实例。
        
        Returns:
            当前代理实例
        """
        self.browser_context_helper = BrowserContextHelper(self)
        return self

    async def think(self) -> bool:
        """处理当前状态并使用工具决定下一步操作，包含浏览器状态信息
        
        在调用父类的think方法前，格式化并设置包含浏览器状态的下一步提示。
        
        Returns:
            如果思考成功则返回true，否则返回false
        """
        # 使用浏览器上下文助手格式化下一步提示
        self.next_step_prompt = (
            await self.browser_context_helper.format_next_step_prompt()
        )
        # 调用父类的think方法
        return await super().think()

    async def cleanup(self):
        """清理浏览器代理资源。
        
        调用浏览器上下文助手的cleanup_browser方法来释放浏览器资源。
        """
        # 清理浏览器资源
        await self.browser_context_helper.cleanup_browser()
