"""
网络搜索工具模块

这个模块提供了WebSearch工具，允许代理使用各种搜索引擎在网络上搜索信息。
它支持多个搜索引擎（Google、Bing、DuckDuckGo、百度），并具有失败时自动切换引擎的容错机制。
此外，它还可以提取和规范化搜索结果内容，提供高质量的搜索结果。

主要功能：
1. 跨多个搜索引擎执行搜索查询
2. 提供结构化的搜索结果，包含URL、标题和描述
3. 可选择性地获取搜索结果页面的完整内容
4. 支持失败重试和引擎回退机制
5. 自定义语言和国家设置
"""

import asyncio
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict, Field, model_validator
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import config
from app.logger import logger
from app.tool.base import BaseTool, ToolResult
from app.tool.search import (
    BaiduSearchEngine,  # 百度搜索引擎
    BingSearchEngine,  # 必应搜索引擎
    DuckDuckGoSearchEngine,  # DuckDuckGo搜索引擎
    GoogleSearchEngine,  # 谷歌搜索引擎
    WebSearchEngine,  # 搜索引擎基类
)
from app.tool.search.base import SearchItem  # 基础搜索项目类


class SearchResult(BaseModel):
    """表示搜索引擎返回的单个搜索结果。
    
    这个类存储来自搜索引擎的搜索结果数据，包括标题、URL、描述及其他元数据。
    同时支持可选的原始内容获取，便于更详细地分析搜索结果。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)  # 允许使用任意类型

    position: int = Field(description="Position in search results")  # 在搜索结果中的位置
    url: str = Field(description="URL of the search result")  # 搜索结果的URL
    title: str = Field(default="", description="Title of the search result")  # 搜索结果标题
    description: str = Field(
        default="", description="Description or snippet of the search result"
    )  # 搜索结果描述或摘要
    source: str = Field(description="The search engine that provided this result")  # 提供此结果的搜索引擎
    raw_content: Optional[str] = Field(
        default=None, description="Raw content from the search result page if available"
    )  # 可用的搜索结果页面原始内容

    def __str__(self) -> str:
        """搜索结果的字符串表示。返回标题和URL的格式化字符串。"""
        return f"{self.title} ({self.url})"


class SearchMetadata(BaseModel):
    """搜索操作的元数据信息。
    
    存储搜索过程中的元数据，如搜索结果总数、语言设置和国家设置等。
    这些信息对于理解搜索结果的上下文和编写准确的查询很有帮助。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)  # 允许使用任意类型

    total_results: int = Field(description="Total number of results found")  # 找到的结果总数
    language: str = Field(description="Language code used for the search")  # 用于搜索的语言代码
    country: str = Field(description="Country code used for the search")  # 用于搜索的国家代码


class SearchResponse(ToolResult):
    """网络搜索工具的结构化响应，继承自ToolResult。
    
    存储本次搜索的查询语句、结果列表和元数据信息。它继承自ToolResult，
    提供了标准化的接口来呈现搜索结果。这个类会将搜索结果格式化为
    结构良好的文本输出，便于用户阅读和代理理解。
    """

    query: str = Field(description="The search query that was executed")  # 执行的搜索查询
    results: List[SearchResult] = Field(
        default_factory=list, description="List of search results"
    )  # 搜索结果列表
    metadata: Optional[SearchMetadata] = Field(
        default=None, description="Metadata about the search"
    )  # 搜索的元数据信息

    @model_validator(mode="after")
    def populate_output(self) -> "SearchResponse":
        """根据搜索结果填充输出或错误字段。
        
        这个方法将搜索结果转换为格式化的文本输出，包括搜索查询、标题、URL、
        描述和内容预览（如果有）。它还会添加元数据信息，如结果总数、语言和国家。
        这个方法算是一个后处理验证器，在对象创建完成后自动调用。
        
        返回：
            填充了输出字段的SearchResponse对象
        """
        # 如果有错误，直接返回自身，不填充输出
        if self.error:
            return self

        # 创建结果文本列表，以搜索查询开头
        result_text = [f"Search results for '{self.query}':"]

        # 遍历所有搜索结果，从1开始编号
        for i, result in enumerate(self.results, 1):
            # 添加带编号的标题，如果没有标题则显示"No title"
            title = result.title.strip() or "No title"
            result_text.append(f"\n{i}. {title}")

            # 添加带适当缩进的URL
            result_text.append(f"   URL: {result.url}")

            # 如果有描述，添加描述
            if result.description.strip():
                result_text.append(f"   Description: {result.description}")

            # 如果有原始内容，添加内容预览
            if result.raw_content:
                # 获取前1000个字符的内容预览，并将换行符替换为空格
                content_preview = result.raw_content[:1000].replace("\n", " ").strip()
                # 如果原始内容超过1000个字符，添加省略号
                if len(result.raw_content) > 1000:
                    content_preview += "..."
                result_text.append(f"   Content: {content_preview}")

        # 如果有元数据，在底部添加元数据信息
        if self.metadata:
            result_text.extend(
                [
                    f"\nMetadata:",
                    f"- Total results: {self.metadata.total_results}",
                    f"- Language: {self.metadata.language}",
                    f"- Country: {self.metadata.country}",
                ]
            )

        # 将所有结果文本连接为一个字符串，并设置到output字段
        self.output = "\n".join(result_text)
        return self


class WebContentFetcher:
    """网页内容获取工具类。
    
    这个工具类负责从指定的URL获取网页内容，并将其提取为纯文本格式。
    它使用BeautifulSoup库来分析HTML并提取有用的文本内容，同时去除脚本、
    样式和其他非主要内容元素。这个类提供网页文本内容以增强搜索结果的价值。
    """

    @staticmethod
    async def fetch_content(url: str, timeout: int = 10) -> Optional[str]:
        """
        从网页获取并提取主要内容。
        
        这个方法异步地从网页上获取内容，然后使用BeautifulSoup提取有用的文本。
        它会删除脚本、样式和导航元素，还会清理多余的空白并限制返回的文本大小。

        参数:
            url: 要获取内容的URL
            timeout: 请求超时时间（秒）

        返回:
            提取的文本内容，如果获取失败则返回None
        """
        # 设置请求头，模拟浏览器访问以避免被拒绝
        headers = {
            "WebSearch": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

        try:
            # 使用asyncio在线程池中运行请求，避免阻塞主线程
            response = await asyncio.get_event_loop().run_in_executor(
                None, lambda: requests.get(url, headers=headers, timeout=timeout)
            )

            # 检查响应码，如果不是200，记录警告并返回None
            if response.status_code != 200:
                logger.warning(
                    f"Failed to fetch content from {url}: HTTP {response.status_code}"
                )
                return None

            # 使用BeautifulSoup解析HTML
            soup = BeautifulSoup(response.text, "html.parser")

            # 移除脚本、样式和导航等非核心内容元素
            for script in soup(["script", "style", "header", "footer", "nav"]):
                script.extract()

            # 获取纯文本内容，使用\n作为分隔符
            text = soup.get_text(separator="\n", strip=True)

            # 清理多余的空白并限制大小（最多10000字符）
            text = " ".join(text.split())
            return text[:10000] if text else None

        except Exception as e:
            # 记录错误并返回None
            logger.warning(f"Error fetching content from {url}: {e}")
            return None


class WebSearch(BaseTool):
    """使用各种搜索引擎在网络上搜索信息的工具。
    
    这个工具类实现了BaseTool接口，允许代理在互联网上搜索实时信息。它支持
    多个搜索引擎（Google、Bing、DuckDuckGo、百度），并提供失败自动切换引擎的功能。
    它返回结构化的搜索结果，包含相关的URL、标题和描述，还可选择性地获取完整页面内容。
    """

    # 工具名称
    name: str = "web_search"
    # 工具描述，用于向语言模型提供工具介绍
    description: str = """在网络上搜索关于任何主题的实时信息。
    该工具返回全面的搜索结果，包含相关信息、URL、标题和描述。
    如果主要搜索引擎失败，它会自动切换到备用引擎。"""
    # 工具参数模式
    parameters: dict = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "(必需) 要提交给搜索引擎的搜索查询。",
            },
            "num_results": {
                "type": "integer",
                "description": "(可选) 要返回的搜索结果数量。默认为5。",
                "default": 5,
            },
            "lang": {
                "type": "string",
                "description": "(可选) 搜索结果的语言代码（默认：en）。",
                "default": "en",
            },
            "country": {
                "type": "string",
                "description": "(可选) 搜索结果的国家代码（默认：us）。",
                "default": "us",
            },
            "fetch_content": {
                "type": "boolean",
                "description": "(可选) 是否从结果页面获取完整内容。默认为false。",
                "default": False,
            },
        },
        "required": ["query"],
    }
    # 搜索引擎实例字典，包含多个不同的搜索引擎实现
    _search_engine: dict[str, WebSearchEngine] = {
        "google": GoogleSearchEngine(),  # 谷歌搜索引擎
        "baidu": BaiduSearchEngine(),    # 百度搜索引擎
        "duckduckgo": DuckDuckGoSearchEngine(),  # DuckDuckGo搜索引擎
        "bing": BingSearchEngine(),      # 必应搜索引擎
    }
    # 网页内容获取器实例，用于获取搜索结果的内容
    content_fetcher: WebContentFetcher = WebContentFetcher()

    async def execute(
        self,
        query: str,
        num_results: int = 5,
        lang: Optional[str] = None,
        country: Optional[str] = None,
        fetch_content: bool = False,
    ) -> SearchResponse:
        """
        执行网络搜索并返回详细的搜索结果。
        
        这个方法是WebSearch工具的主要入口点，负责协调搜索过程。它尝试使用配置的搜索引擎
        执行搜索查询，并在失败时尝试备用引擎。该方法还处理重试逻辑、内容获取和结果格式化。

        参数:
            query: 要提交给搜索引擎的搜索查询
            num_results: 要返回的搜索结果数量（默认：5）
            lang: 搜索结果的语言代码（默认从配置文件获取）
            country: 搜索结果的国家代码（默认从配置文件获取）
            fetch_content: 是否从结果页面获取内容（默认：False）

        返回:
            包含搜索结果和元数据的结构化响应
        """
        # 从配置中获取设置
        # 获取重试延迟时间，默认为60秒
        retry_delay = (
            getattr(config.search_config, "retry_delay", 60)
            if config.search_config
            else 60
        )
        # 获取最大重试次数，默认为3次
        max_retries = (
            getattr(config.search_config, "max_retries", 3)
            if config.search_config
            else 3
        )

        # 如果未指定语言和国家，则使用配置中的值
        # 如果未指定语言，使用配置或默认值"en"
        if lang is None:
            lang = (
                getattr(config.search_config, "lang", "en")
                if config.search_config
                else "en"
            )

        # 如果未指定国家，使用配置或默认值"us"
        if country is None:
            country = (
                getattr(config.search_config, "country", "us")
                if config.search_config
                else "us"
            )

        # 创建搜索参数字典
        search_params = {"lang": lang, "country": country}

        # 尝试使用所有引擎搜索，并在失败时重试
        for retry_count in range(max_retries + 1):
            # 使用所有引擎尝试搜索
            results = await self._try_all_engines(query, num_results, search_params)

            # 如果获得结果，处理并返回
            if results:
                # 如果请求获取内容，为所有结果获取原始内容
                if fetch_content:
                    results = await self._fetch_content_for_results(results)

                # 返回成功的结构化响应
                return SearchResponse(
                    status="success",  # 状态设置为成功
                    query=query,       # 原始查询
                    results=results,   # 搜索结果列表
                    metadata=SearchMetadata(  # 添加元数据
                        total_results=len(results),  # 结果总数
                        language=lang,              # 语言
                        country=country,            # 国家
                    ),
                )

            # 如果还有重试机会，等待后重试
            if retry_count < max_retries:
                # 所有引擎都失败了，等待并重试
                logger.warning(
                    f"All search engines failed. Waiting {retry_delay} seconds before retry {retry_count + 1}/{max_retries}..."
                )
                # 等待指定的延迟时间
                await asyncio.sleep(retry_delay)
            else:
                # 如果达到最大重试次数，记录错误
                logger.error(
                    f"All search engines failed after {max_retries} retries. Giving up."
                )

        # 返回错误响应
        return SearchResponse(
            query=query,  # 原始查询
            error="All search engines failed to return results after multiple retries.",  # 错误信息
            results=[],  # 空结果列表
        )

    async def _try_all_engines(
        self, query: str, num_results: int, search_params: Dict[str, Any]
    ) -> List[SearchResult]:
        """按配置的顺序尝试所有搜索引擎。
        
        这个方法按照配置的优先顺序尝试每个搜索引擎，直到成功获取结果或所有引擎都失败。
        它会跟踪失败的引擎以便记录日志，并将搜索项转换为结构化的SearchResult对象。
        
        参数:
            query: 搜索查询字符串
            num_results: 要返回的搜索结果数量
            search_params: 与语言和国家相关的搜索参数
            
        返回:
            搜索结果列表，如果所有引擎都失败则返回空列表
        """
        # 获取搜索引擎的优先顺序
        engine_order = self._get_engine_order()
        # 记录失败的引擎
        failed_engines = []

        # 按优先顺序尝试每个搜索引擎
        for engine_name in engine_order:
            # 获取当前引擎实例
            engine = self._search_engine[engine_name]
            # 记录尝试使用的引擎
            logger.info(f"🔎 Attempting search with {engine_name.capitalize()}...")
            # 使用当前引擎执行搜索
            search_items = await self._perform_search_with_engine(
                engine, query, num_results, search_params
            )

            # 如果没有结果，继续尝试下一个引擎
            if not search_items:
                continue

            # 如果之前有失败的引擎，记录成功信息
            if failed_engines:
                logger.info(
                    f"Search successful with {engine_name.capitalize()} after trying: {', '.join(failed_engines)}"
                )

            # 将搜索项转换为结构化的搜索结果
            return [
                SearchResult(
                    position=i + 1,  # 位置编号，从1开始
                    url=item.url,    # URL
                    title=item.title
                    or f"Result {i+1}",  # 确保始终有标题
                    description=item.description or "",  # 描述
                    source=engine_name,  # 记录来源引擎
                )
                for i, item in enumerate(search_items)
            ]

        # 如果有失败的引擎，记录错误
        if failed_engines:
            logger.error(f"All search engines failed: {', '.join(failed_engines)}")
        # 所有引擎都失败时返回空列表
        return []

    async def _fetch_content_for_results(
        self, results: List[SearchResult]
    ) -> List[SearchResult]:
        """获取并添加网页内容到搜索结果中。
        
        这个方法并行地为所有搜索结果获取网页内容。它使用asyncio.gather来同时处理
        多个页面的内容获取，以减少等待时间。这个方法会保留原始的搜索结果字段，
        只添加raw_content字段来存储获取的页面内容。
        
        参数:
            results: 搜索结果列表
            
        返回:
            添加了网页内容的搜索结果列表
        """
        # 如果没有结果，返回空列表
        if not results:
            return []

        # 为每个结果创建单独的内容获取任务
        tasks = [self._fetch_single_result_content(result) for result in results]

        # 并行执行所有内容获取任务
        fetched_results = await asyncio.gather(*tasks)

        # 验证返回类型并转换为SearchResult类型
        return [
            (
                result
                if isinstance(result, SearchResult)  # 如果已经是SearchResult类型
                else SearchResult(**result.dict())  # 否则从字典创建新的SearchResult
            )
            for result in fetched_results
        ]

    async def _fetch_single_result_content(self, result: SearchResult) -> SearchResult:
        """获取单个搜索结果的网页内容。
        
        这个方法为单个搜索结果获取其URL指向的网页内容。如果URL存在并且内容获取成功，
        它将原始内容添加到搜索结果的raw_content字段中。这个方法不会修改原始结果的其他字段。
        
        参数:
            result: 要获取内容的搜索结果
            
        返回:
            添加了原始内容的搜索结果
        """
        # 如果结果包含URL，尝试获取其内容
        if result.url:
            # 调用内容获取器获取URL内容
            content = await self.content_fetcher.fetch_content(result.url)
            # 如果成功获取到内容，添加到结果中
            if content:
                result.raw_content = content
        # 返回已处理的结果
        return result

    def _get_engine_order(self) -> List[str]:
        """确定尝试搜索引擎的顺序。
        
        这个方法决定搜索引擎的使用顺序，首先使用首选引擎，然后是备用引擎，
        最后是其余的引擎。这个排序是基于配置文件中的设置。如果首选引擎
        不可用，则会尝试备用引擎列表。
        
        返回:
            搜索引擎名称的有序列表
        """
        # 从配置中获取首选引擎，默认为"google"
        preferred = (
            getattr(config.search_config, "engine", "google").lower()
            if config.search_config
            else "google"
        )
        # 从配置中获取备用引擎列表
        fallbacks = (
            [engine.lower() for engine in config.search_config.fallback_engines]
            if config.search_config
            and hasattr(config.search_config, "fallback_engines")
            else []
        )

        # 首先使用首选引擎，然后是备用引擎，最后是其余引擎
        # 如果首选引擎存在，将其添加到引擎顺序中
        engine_order = [preferred] if preferred in self._search_engine else []
        # 添加备用引擎，前提是它们存在且还未添加
        engine_order.extend(
            [
                fb
                for fb in fallbacks
                if fb in self._search_engine and fb not in engine_order
            ]
        )
        # 添加其余未包含的引擎
        engine_order.extend([e for e in self._search_engine if e not in engine_order])

        return engine_order

    @retry(
        stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10)
    )
    async def _perform_search_with_engine(
        self,
        engine: WebSearchEngine,
        query: str,
        num_results: int,
        search_params: Dict[str, Any],
    ) -> List[SearchItem]:
        """使用给定的引擎和参数执行搜索。
        
        这个方法使用指定的搜索引擎执行搜索查询。它被装饰器@retry包裹，
        在失败时自动重试最多3次，并使用指数退避策略。该方法在单独的线程中
        执行搜索引擎的perform_search方法，以避免阻塞主线程。
        
        参数:
            engine: 要使用的搜索引擎实例
            query: 搜索查询字符串
            num_results: 要返回的结果数量
            search_params: 包含语言和国家代码的搜索参数
            
        返回:
            搜索项列表
        """
        # 在单独的线程中异步执行搜索引擎的perform_search方法
        return await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: list(
                engine.perform_search(
                    query,
                    num_results=num_results,
                    lang=search_params.get("lang"),  # 语言参数
                    country=search_params.get("country"),  # 国家参数
                )
            ),
        )


# 如果该文件被直接执行，运行测试搜索
# 这部分代码只在测试时执行，正常的模块导入不会触发它
if __name__ == "__main__":
    # 创建WebSearch实例
    web_search = WebSearch()
    # 运行异步搜索查询，获取"Python programming"相关的内容
    search_response = asyncio.run(
        web_search.execute(
            query="Python programming", fetch_content=True, num_results=1
        )
    )
    # 打印搜索结果
    print(search_response.to_tool_result())
