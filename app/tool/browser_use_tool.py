"""浏览器自动化工具模块。

该模块实现了一个功能强大的浏览器自动化工具，可以模拟用户在Web浏览器中的各种操作，
包括网页导航、点击元素、输入文本、滚动页面和提取内容等。它维护浏览器会话状态，
并提供多标签页管理和内容提取功能。
"""

import asyncio
import base64
import json
from typing import Generic, Optional, TypeVar

from browser_use import Browser as BrowserUseBrowser
from browser_use import BrowserConfig
from browser_use.browser.context import BrowserContext, BrowserContextConfig
from browser_use.dom.service import DomService
from pydantic import Field, field_validator
from pydantic_core.core_schema import ValidationInfo

from app.config import config
from app.llm import LLM
from app.tool.base import BaseTool, ToolResult
from app.tool.web_search import WebSearch


_BROWSER_DESCRIPTION = """\
# 浏览器自动化工具
一个强大的浏览器自动化工具，允许通过各种操作与网页交互。
* 此工具提供用于控制浏览器会话、导航网页和提取信息的命令
* 它在调用之间维持状态，保持浏览器会话活动直到显式关闭
* 当你需要浏览网站、填写表单、点击按钮、提取内容或执行网络搜索时使用此工具
* 每个操作都需要工具依赖项中定义的特定参数

主要功能包括：
* 导航：访问特定URL、返回、搜索网页或刷新页面
* 交互：点击元素、输入文本、从下拉列表中选择、发送键盘命令
* 滚动：按像素数量上下滚动或滚动到特定文本
* 内容提取：基于特定目标从网页中提取和分析内容
* 标签页管理：在标签页之间切换、打开新标签页或关闭标签页

注意事项：
* 浏览器操作可能有副作用，如提交表单或改变状态
* 某些页面可能有反机器人措施，可能会阻止自动浏览
* 为获得最佳结果，请留出足够的等待时间使页面完全加载
* 网络连接问题可能导致操作失败
"""

Context = TypeVar("Context")


class BrowserUseTool(BaseTool, Generic[Context]):
    """浏览器自动化工具类。
    
    该类提供了一个与浏览器交互的工具接口，允许AI代理执行各种浏览器操作，
    如导航网页、与元素交互、滚动页面、提取内容等。
    它实现了通用的浏览器接口，并维护浏览器会话状态。
    
    属性:
        browser: 浏览器实例
        context: 浏览器上下文
        dom_service: 用于DOM操作的服务
        lock: 用于线程安全的锁
        llm: 可选的用于内容提取的LLM
        web_search_tool: 用于网络搜索的工具
        tool_context: 此工具的通用上下文

    依赖项:
        - 需要browser_use包用于浏览器自动化
        - 使用网络搜索工具进行搜索功能
        - 可选用LLM进行内容提取
    """
    name: str = "browser_use"  # 工具名称
    description: str = _BROWSER_DESCRIPTION  # 工具描述
    # 工具参数定义，指定各种可用的浏览器操作及其参数
    parameters: dict = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "go_to_url",          # 访问指定URL
                    "click_element",      # 点击元素
                    "input_text",         # 输入文本
                    "scroll_down",        # 向下滚动
                    "scroll_up",          # 向上滚动
                    "scroll_to_text",     # 滚动到指定文本
                    "send_keys",          # 发送键盘命令
                    "get_dropdown_options",  # 获取下拉选项
                    "select_dropdown_option", # 选择下拉选项
                    "go_back",            # 返回上一页
                    "web_search",         # 执行网页搜索
                    "wait",               # 等待指定时间
                    "extract_content",    # 提取网页内容
                    "switch_tab",         # 切换标签页
                    "open_tab",           # 打开新标签页
                    "close_tab",          # 关闭标签页
                ],
                "description": "The browser action to perform", # 要执行的浏览器操作
            },
            "url": {
                "type": "string",
                "description": "URL for 'go_to_url' or 'open_tab' actions", # 用于go_to_url或open_tab操作的URL
            },
            "index": {
                "type": "integer",
                "description": "Element index for 'click_element', 'input_text', 'get_dropdown_options', or 'select_dropdown_option' actions", # 元素索引
            },
            "text": {
                "type": "string",
                "description": "Text for 'input_text', 'scroll_to_text', or 'select_dropdown_option' actions", # 要输入或搜索的文本
            },
            "scroll_amount": {
                "type": "integer",
                "description": "Pixels to scroll (positive for down, negative for up) for 'scroll_down' or 'scroll_up' actions", # 滚动像素数
            },
            "tab_id": {
                "type": "integer",
                "description": "Tab ID for 'switch_tab' action", # 标签页ID
            },
            "query": {
                "type": "string",
                "description": "Search query for 'web_search' action", # 搜索查询
            },
            "goal": {
                "type": "string",
                "description": "Extraction goal for 'extract_content' action", # 内容提取目标
            },
            "keys": {
                "type": "string",
                "description": "Keys to send for 'send_keys' action", # 要发送的键盘键
            },
            "seconds": {
                "type": "integer",
                "description": "Seconds to wait for 'wait' action", # 等待的秒数
            },
        },
        "required": ["action"],  # 必需参数
        "dependencies": {  # 各操作所依赖的参数
            "go_to_url": ["url"],  # 访问网页需要URL
            "click_element": ["index"],  # 点击元素需要元素索引
            "input_text": ["index", "text"],  # 输入文本需要元素索引和文本
            "switch_tab": ["tab_id"],  # 切换标签页需要标签页ID
            "open_tab": ["url"],  # 打开新标签页需要URL
            "scroll_down": ["scroll_amount"],  # 向下滚动需要滚动像素数
            "scroll_up": ["scroll_amount"],  # 向上滚动需要滚动像素数
            "scroll_to_text": ["text"],  # 滚动到文本需要目标文本
            "send_keys": ["keys"],  # 发送键盘命令需要键值
            "get_dropdown_options": ["index"],  # 获取下拉选项需要元素索引
            "select_dropdown_option": ["index", "text"],  # 选择下拉选项需要元素索引和选项文本
            "go_back": [],  # 返回上一页不需要额外参数
            "web_search": ["query"],  # 网页搜索需要查询文本
            "wait": ["seconds"],  # 等待需要指定秒数
            "extract_content": ["goal"],  # 提取内容需要目标描述
        },
    }

    # 类属性定义
    lock: asyncio.Lock = Field(default_factory=asyncio.Lock)  # 用于同步访问的锁
    browser: Optional[BrowserUseBrowser] = Field(default=None, exclude=True)  # 浏览器实例
    context: Optional[BrowserContext] = Field(default=None, exclude=True)  # 浏览器上下文
    dom_service: Optional[DomService] = Field(default=None, exclude=True)  # DOM服务，用于操作网页元素
    web_search_tool: WebSearch = Field(default_factory=WebSearch, exclude=True)  # 网页搜索工具

    # 通用功能的上下文
    tool_context: Optional[Context] = Field(default=None, exclude=True)  # 工具上下文

    llm: Optional[LLM] = Field(default_factory=LLM)  # 语言模型实例

    @field_validator("parameters", mode="before")
    def validate_parameters(cls, v: dict, info: ValidationInfo) -> dict:
        """验证参数是否为空。
        
        在构造实例前验证参数字典是否为空。
        
        参数:
            v: 参数字典
            info: 验证信息
            
        返回:
            dict: 验证后的参数字典
            
        异常:
            ValueError: 当参数为空时抛出
        """
        if not v:  # 检查参数是否为空
            raise ValueError("Parameters cannot be empty")
        return v

    async def _ensure_browser_initialized(self) -> BrowserContext:
        """
        确保浏览器和上下文已初始化。
        
        如果浏览器或上下文尚未初始化，则进行初始化。
        这可确保在执行浏览器操作之前环境已就绪。
        
        返回:
            BrowserContext: 初始化的浏览器上下文
        """
        # 如果浏览器实例不存在，初始化它
        if self.browser is None:
            # 设置默认配置：非无头模式，禁用安全限制
            browser_config_kwargs = {"headless": False, "disable_security": True}

            # 使用全局配置中的浏览器设置
            if config.browser_config:
                from browser_use.browser.browser import ProxySettings

                # 处理代理服务器设置
                if config.browser_config.proxy and config.browser_config.proxy.server:
                    browser_config_kwargs["proxy"] = ProxySettings(
                        server=config.browser_config.proxy.server,
                        username=config.browser_config.proxy.username,
                        password=config.browser_config.proxy.password,
                    )

                # 浏览器配置属性列表
                browser_attrs = [
                    "headless",  # 无头模式
                    "disable_security",  # 禁用安全限制
                    "extra_chromium_args",  # 额外的Chromium参数
                    "chrome_instance_path",  # Chrome实例路径
                    "wss_url",  # WebSocket安全连接URL
                    "cdp_url",  # Chrome DevTools Protocol URL
                ]

                # 将存在于配置中的属性添加到浏览器配置中
                for attr in browser_attrs:
                    value = getattr(config.browser_config, attr, None)
                    if value is not None:  # 如果属性有值
                        # 对于列表属性，确保列表不为空
                        if not isinstance(value, list) or value:
                            browser_config_kwargs[attr] = value

            # 创建浏览器实例
            self.browser = BrowserUseBrowser(BrowserConfig(**browser_config_kwargs))

        # 如果浏览器上下文不存在，初始化它
        if self.context is None:
            # 创建默认上下文配置
            context_config = BrowserContextConfig()

            # 如果全局配置中有上下文配置，使用它
            if (
                config.browser_config
                and hasattr(config.browser_config, "new_context_config")
                and config.browser_config.new_context_config
            ):
                context_config = config.browser_config.new_context_config

            # 创建新的浏览器上下文
            self.context = await self.browser.new_context(context_config)
            # 创建DOM服务，用于操作页面元素
            self.dom_service = DomService(await self.context.get_current_page())

        # 返回浏览器上下文
        return self.context

    async def execute(
        self,
        action: str,
        url: Optional[str] = None,
        index: Optional[int] = None,
        text: Optional[str] = None,
        scroll_amount: Optional[int] = None,
        tab_id: Optional[int] = None,
        query: Optional[str] = None,
        goal: Optional[str] = None,
        keys: Optional[str] = None,
        seconds: Optional[int] = None,
        **kwargs,
    ) -> ToolResult:
        """执行浏览器操作。
        
        根据指定的操作类型和相关参数，在浏览器中执行操作。
        操作包括导航、交互、滚动、内容提取等各种浏览器操作。
        
        参数:
            action: 要执行的操作类型
            url: 用于网页导航的URL
            index: 用于指定要交互的元素索引
            text: 用于输入或搜索的文本
            scroll_amount: 滚动的像素数量
            tab_id: 标签页ID
            query: 搜索查询
            goal: 内容提取目标
            keys: 要发送的键盘键
            seconds: 等待的秒数
            **kwargs: 其他可选参数
            
        返回:
            ToolResult: 操作结果，包含输出或错误信息
        """
        async with self.lock:
            try:
                context = await self._ensure_browser_initialized()

                # 从配置中获取内容最大长度限制
                max_content_length = getattr(
                    config.browser_config, "max_content_length", 2000  # 默认为2000字符
                )

                # 导航类操作
                if action == "go_to_url":  # 访问指定URL
                    if not url:  # 验证URL参数
                        return ToolResult(
                            error="URL is required for 'go_to_url' action"  # URL参数缺失错误
                        )
                    page = await context.get_current_page()  # 获取当前页面
                    await page.goto(url)  # 跳转到目标URL
                    await page.wait_for_load_state()  # 等待页面加载完成
                    return ToolResult(output=f"Navigated to {url}")  # 返回成功结果

                elif action == "go_back":  # 返回上一页
                    await context.go_back()  # 执行后退操作
                    return ToolResult(output="Navigated back")  # 返回成功结果

                elif action == "refresh":  # 刷新页面
                    await context.refresh_page()  # 执行页面刷新
                    return ToolResult(output="Refreshed current page")  # 返回成功结果

                elif action == "web_search":  # 网页搜索
                    if not query:  # 验证搜索查询参数
                        return ToolResult(
                            error="Query is required for 'web_search' action"  # 搜索查询缺失错误
                        )
                    # 执行网页搜索并直接返回结果，不通过浏览器导航
                    search_response = await self.web_search_tool.execute(
                        query=query, fetch_content=True, num_results=1  # 获取一个搜索结果及其内容
                    )
                    # 导航到第一个搜索结果
                    first_search_result = search_response.results[0]  # 获取第一个搜索结果
                    url_to_navigate = first_search_result.url  # 提取URL

                    page = await context.get_current_page()  # 获取当前页面
                    await page.goto(url_to_navigate)  # 跳转到搜索结果URL
                    await page.wait_for_load_state()  # 等待页面加载完成

                    return search_response  # 返回搜索响应结果

                # 元素交互操作
                elif action == "click_element":  # 点击元素
                    if index is None:  # 验证元素索引参数
                        return ToolResult(
                            error="Index is required for 'click_element' action"  # 元素索引缺失错误
                        )
                    element = await context.get_dom_element_by_index(index)  # 根据索引获取DOM元素
                    if not element:  # 检查元素是否存在
                        return ToolResult(error=f"Element with index {index} not found")  # 返回未找到元素错误
                    download_path = await context._click_element_node(element)  # 点击元素，可能会下载文件
                    output = f"Clicked element at index {index}"  # 点击成功的基本输出
                    if download_path:  # 如果点击触发了文件下载
                        output += f" - Downloaded file to {download_path}"  # 添加下载信息
                    return ToolResult(output=output)  # 返回点击结果

                elif action == "input_text":  # 输入文本
                    if index is None or not text:  # 验证元素索引和文本参数
                        return ToolResult(
                            error="Index and text are required for 'input_text' action"  # 参数缺失错误
                        )
                    element = await context.get_dom_element_by_index(index)  # 根据索引获取DOM元素
                    if not element:  # 检查元素是否存在
                        return ToolResult(error=f"Element with index {index} not found")  # 返回未找到元素错误
                    await context._input_text_element_node(element, text)  # 在元素中输入文本
                    return ToolResult(
                        output=f"Input '{text}' into element at index {index}"  # 返回输入成功结果
                    )

                elif action == "scroll_down" or action == "scroll_up":  # 上下滚动
                    direction = 1 if action == "scroll_down" else -1  # 决定滚动方向，向下为正，向上为负
                    amount = (
                        scroll_amount  # 使用指定的滚动量
                        if scroll_amount is not None
                        else context.config.browser_window_size["height"]  # 如果未指定，使用浏览器窗口高度
                    )
                    await context.execute_javascript(
                        f"window.scrollBy(0, {direction * amount});"  # 执行JS滚动命令
                    )
                    return ToolResult(
                        output=f"Scrolled {'down' if direction > 0 else 'up'} by {amount} pixels"  # 返回滚动结果
                    )

                elif action == "scroll_to_text":  # 滚动到指定文本
                    if not text:  # 验证文本参数
                        return ToolResult(
                            error="Text is required for 'scroll_to_text' action"  # 文本参数缺失错误
                        )
                    page = await context.get_current_page()  # 获取当前页面
                    try:
                        locator = page.get_by_text(text, exact=False)  # 查找包含指定文本的元素
                        await locator.scroll_into_view_if_needed()  # 滚动到元素可见位置
                        return ToolResult(output=f"Scrolled to text: '{text}'")  # 返回滚动成功结果
                    except Exception as e:  # 捕获可能的错误
                        return ToolResult(error=f"Failed to scroll to text: {str(e)}")  # 返回滚动失败错误

                elif action == "send_keys":  # 发送键盘命令
                    if not keys:  # 验证键值参数
                        return ToolResult(
                            error="Keys are required for 'send_keys' action"  # 键值参数缺失错误
                        )
                    page = await context.get_current_page()  # 获取当前页面
                    await page.keyboard.press(keys)  # 发送键盘按键
                    return ToolResult(output=f"Sent keys: {keys}")  # 返回发送成功结果

                elif action == "get_dropdown_options":  # 获取下拉选项
                    if index is None:  # 验证元素索引参数
                        return ToolResult(
                            error="Index is required for 'get_dropdown_options' action"  # 索引参数缺失错误
                        )
                    element = await context.get_dom_element_by_index(index)  # 根据索引获取DOM元素
                    if not element:  # 检查元素是否存在
                        return ToolResult(error=f"Element with index {index} not found")  # 返回未找到元素错误
                    page = await context.get_current_page()  # 获取当前页面
                    options = await page.evaluate(  # 调用JavaScript进行评估
                        """
                        (xpath) => {
                            const select = document.evaluate(xpath, document, null,
                                XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                            if (!select) return null;
                            return Array.from(select.options).map(opt => ({  // 将选项转换为数组
                                text: opt.text,  // 选项文本
                                value: opt.value,  // 选项值
                                index: opt.index  // 选项索引
                            }));
                        }
                    """,
                        element.xpath,  # 元素的XPath路径
                    )
                    return ToolResult(output=f"Dropdown options: {options}")  # 返回下拉选项列表

                elif action == "select_dropdown_option":  # 选择下拉选项
                    if index is None or not text:  # 验证元素索引和文本参数
                        return ToolResult(
                            error="Index and text are required for 'select_dropdown_option' action"  # 参数缺失错误
                        )
                    element = await context.get_dom_element_by_index(index)  # 根据索引获取DOM元素
                    if not element:  # 检查元素是否存在
                        return ToolResult(error=f"Element with index {index} not found")  # 返回未找到元素错误
                    page = await context.get_current_page()  # 获取当前页面
                    await page.select_option(element.xpath, label=text)  # 基于标签文本选择选项
                    return ToolResult(
                        output=f"Selected option '{text}' from dropdown at index {index}"  # 返回选择成功结果
                    )

                # 内容提取操作
                elif action == "extract_content":  # 提取内容
                    if not goal:  # 验证目标参数
                        return ToolResult(
                            error="Goal is required for 'extract_content' action"  # 目标参数缺失错误
                        )

                    page = await context.get_current_page()  # 获取当前页面
                    import markdownify  # 导入将HTML转为Markdown的工具

                    content = markdownify.markdownify(await page.content())  # 将页面内容转换为Markdown格式

                    prompt = f"""\
Your task is to extract the content of the page. You will be given a page and a goal, and you should extract all relevant information around this goal from the page. If the goal is vague, summarize the page. Respond in json format.
Extraction goal: {goal}

Page content:
{content[:max_content_length]}
"""  # 创建提取内容的提示，包含目标和页面内容
                    messages = [{"role": "system", "content": prompt}]  # 创建系统角色消息

                    # 定义内容提取函数模式
                    extraction_function = {
                        "type": "function",  # 函数类型
                        "function": {
                            "name": "extract_content",  # 函数名称
                            "description": "Extract specific information from a webpage based on a goal",  # 函数描述
                            "parameters": {  # 函数参数
                                "type": "object",
                                "properties": {
                                    "extracted_content": {  # 提取的内容
                                        "type": "object",
                                        "description": "The content extracted from the page according to the goal",  # 根据目标从页面提取的内容
                                        "properties": {
                                            "text": {  # 提取的文本内容
                                                "type": "string",
                                                "description": "Text content extracted from the page",  # 从页面提取的文本内容
                                            },
                                            "metadata": {  # 元数据
                                                "type": "object",
                                                "description": "Additional metadata about the extracted content",  # 有关提取内容的元数据
                                                "properties": {
                                                    "source": {  # 内容来源
                                                        "type": "string",
                                                        "description": "Source of the extracted content",  # 提取内容的来源
                                                    }
                                                },
                                            },
                                        },
                                    }
                                },
                                "required": ["extracted_content"],  # 必需参数
                            },
                        },
                    }

                    # 使用LLM提取内容，要求执行函数调用
                    response = await self.llm.ask_tool(
                        messages,  # 消息列表
                        tools=[extraction_function],  # 工具函数
                        tool_choice="required",  # 要求必须使用工具
                    )

                    if response and response.tool_calls:  # 如果有响应和工具调用
                        args = json.loads(response.tool_calls[0].function.arguments)  # 解析调用参数
                        extracted_content = args.get("extracted_content", {})  # 获取提取的内容
                        return ToolResult(
                            output=f"Extracted from page:\n{extracted_content}\n"  # 返回提取的内容
                        )

                    return ToolResult(output="No content was extracted from the page.")  # 如果未提取到内容，返回提示

                # 标签页管理操作
                elif action == "switch_tab":  # 切换标签页
                    if tab_id is None:  # 验证标签页ID参数
                        return ToolResult(
                            error="Tab ID is required for 'switch_tab' action"  # 标签页ID缺失错误
                        )
                    await context.switch_to_tab(tab_id)  # 切换到指定标签页
                    page = await context.get_current_page()  # 获取当前页面
                    await page.wait_for_load_state()  # 等待页面加载完成
                    return ToolResult(output=f"Switched to tab {tab_id}")  # 返回切换成功结果

                elif action == "open_tab":  # 打开新标签页
                    if not url:  # 验证URL参数
                        return ToolResult(error="URL is required for 'open_tab' action")  # URL缺失错误
                    await context.create_new_tab(url)  # 创建新标签页并访问指定URL
                    return ToolResult(output=f"Opened new tab with {url}")  # 返回打开成功结果

                elif action == "close_tab":  # 关闭标签页
                    await context.close_current_tab()  # 关闭当前标签页
                    return ToolResult(output="Closed current tab")  # 返回关闭成功结果

                # 实用工具操作
                elif action == "wait":  # 等待操作
                    seconds_to_wait = seconds if seconds is not None else 3  # 使用指定的等待时间或默认为3秒
                    await asyncio.sleep(seconds_to_wait)  # 等待指定秒数
                    return ToolResult(output=f"Waited for {seconds_to_wait} seconds")  # 返回等待结果

                else:  # 未知操作
                    return ToolResult(error=f"Unknown action: {action}")  # 返回未知操作错误

            except Exception as e:  # 捕获所有异常
                return ToolResult(error=f"Browser action '{action}' failed: {str(e)}")  # 返回操作失败错误

    async def get_current_state(
        self, context: Optional[BrowserContext] = None
    ) -> ToolResult:
        """
        获取当前浏览器状态。
        
        返回浏览器的当前状态，包括页面URL、标题、标签页信息和可交互元素。
        如果没有提供上下文，则使用self.context。
        
        参数:
            context: 可选的浏览器上下文对象
            
        返回:
            ToolResult: 包含浏览器状态信息和页面截图的结果
        """
        try:
            # 使用提供的上下文或默认使用self.context
            ctx = context or self.context
            if not ctx:  # 如果上下文不存在
                return ToolResult(error="Browser context not initialized")  # 返回浏览器上下文未初始化错误

            # 获取浏览器当前状态
            state = await ctx.get_state()

            # 如果视口信息不存在，则创建视口信息字典
            viewport_height = 0  # 初始化视口高度
            if hasattr(state, "viewport_info") and state.viewport_info:  # 如果状态中存在视口信息
                viewport_height = state.viewport_info.height  # 使用状态中的视口高度
            elif hasattr(ctx, "config") and hasattr(ctx.config, "browser_window_size"):  # 如果配置中存在浏览器窗口大小
                viewport_height = ctx.config.browser_window_size.get("height", 0)  # 使用配置中的窗口高度

            # 为当前状态捕捉屏幕截图
            page = await ctx.get_current_page()  # 获取当前浏览器页面

            await page.bring_to_front()  # 将页面置于前台
            await page.wait_for_load_state()  # 等待页面加载完成

            # 捕捉页面截图，完整页面，禁用动画，JPEG格式，最高质量
            screenshot = await page.screenshot(
                full_page=True, animations="disabled", type="jpeg", quality=100
            )

            # 将截图转换为Base64编码的字符串
            screenshot = base64.b64encode(screenshot).decode("utf-8")

            # 构建包含所有必要字段的状态信息
            state_info = {
                "url": state.url,  # 当前页面URL
                "title": state.title,  # 当前页面标题
                "tabs": [tab.model_dump() for tab in state.tabs],  # 所有标签页的数据
                "help": "[0], [1], [2], etc., represent clickable indices corresponding to the elements listed. Clicking on these indices will navigate to or interact with the respective content behind them.",  # 帮助文本
                "interactive_elements": (  # 可交互元素信息
                    state.element_tree.clickable_elements_to_string()  # 如果存在元素树，转换可点击元素为字符串
                    if state.element_tree
                    else ""  # 如果不存在元素树，返回空字符串
                ),
                "scroll_info": {  # 滚动相关信息
                    "pixels_above": getattr(state, "pixels_above", 0),  # 视口上方的像素数
                    "pixels_below": getattr(state, "pixels_below", 0),  # 视口下方的像素数
                    "total_height": getattr(state, "pixels_above", 0)  # 计算页面总高度
                    + getattr(state, "pixels_below", 0)  # 视口上方像素 + 视口下方像素
                    + viewport_height,  # + 视口高度
                },
                "viewport_height": viewport_height,  # 视口高度
            }

            # 返回包含状态信息和截图的结果
            return ToolResult(
                output=json.dumps(state_info, indent=4, ensure_ascii=False),  # 将状态信息字典转为格式化的JSON字符串
                base64_image=screenshot,  # 将Base64编码的截图包含在结果中
            )
        except Exception as e:  # 捕获所有异常
            return ToolResult(error=f"Failed to get browser state: {str(e)}")  # 返回获取浏览器状态失败的错误信息

    async def cleanup(self):
        """清理浏览器资源。
        
        关闭浏览器上下文和浏览器实例，释放相关资源。
        在工具完成使用或销毁时调用。
        """
        async with self.lock:
            if self.context is not None:
                await self.context.close()
                self.context = None
                self.dom_service = None
            if self.browser is not None:
                await self.browser.close()
                self.browser = None

    def __del__(self):
        """在对象被销毁时确保清理资源。
        
        Python的析构函数，在对象被垃圾回收时调用。
        确保浏览器资源被正确关闭，防止资源泄漏。
        """
        if self.browser is not None or self.context is not None:
            try:
                asyncio.run(self.cleanup())
            except RuntimeError:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(self.cleanup())
                loop.close()

    @classmethod
    def create_with_context(cls, context: Context) -> "BrowserUseTool[Context]":
        """创建一个带有特定上下文的BrowserUseTool的工厂方法。
        
        这是一个类方法，用于创建带有特定上下文的浏览器工具实例。
        
        参数:
            context: 要使用的特定上下文对象
            
        返回:
            BrowserUseTool[Context]: 创建的浏览器工具实例
        """
        tool = cls()
        tool.tool_context = context
        return tool
