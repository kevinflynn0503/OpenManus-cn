"""
DuckDuckGo搜索引擎模块

这个模块提供了DuckDuckGoSearchEngine类，实现了WebSearchEngine接口来使用DuckDuckGo搜索引擎。
它使用duckduckgo_search库执行实际的搜索请求，并将结果转换为标准的SearchItem对象。
DuckDuckGo是一个注重隐私的搜索引擎，不跟踪用户搜索历史，并且更少内容过滤。
"""

from typing import List

# 使用duckduckgo_search库的DDGS类来执行搜索
from duckduckgo_search import DDGS

# 导入搜索基础类和搜索结果项模型
from app.tool.search.base import SearchItem, WebSearchEngine


class DuckDuckGoSearchEngine(WebSearchEngine):
    """
    DuckDuckGo搜索引擎实现类。
    
    这个类继承自WebSearchEngine基类，提供了使用DuckDuckGo搜索引擎执行搜索的实现。
    它使用duckduckgo_search库的DDGS类来执行搜索查询，并处理不同格式的搜索结果。
    DuckDuckGo的主要特点是隐私保护和不跟踪用户，这使其成为需要隐私搜索的场景下的良好选择。
    """
    def perform_search(
        self, query: str, num_results: int = 10, *args, **kwargs
    ) -> List[SearchItem]:
        """
        执行DuckDuckGo搜索并返回格式化的搜索结果。
        
        这个方法实现了WebSearchEngine基类中的抽象方法，使用duckduckgo_search库
        来执行实际的搜索查询。由于DuckDuckGo的API返回结果格式特定，该方法
        处理了不同类型的结果格式，并将其转换为标准的SearchItem对象。
        
        参数:
            query: 搜索查询字符串
            num_results: 要返回的结果数量（默认为10）
            *args, **kwargs: 传递给搜索引擎的额外参数
            
        返回:
            按照SearchItem模型格式化的搜索结果列表
        """
        # 使用DDGS类的text方法执行文本搜索，并限制结果数量
        raw_results = DDGS().text(query, max_results=num_results)

        # 初始化结果列表
        results = []
        # 遍历所有原始搜索结果
        for i, item in enumerate(raw_results):
            # 如果结果是字符串（URL）
            if isinstance(item, str):
                # 如果只是URL，创建一个带默认标题的搜索结果
                results.append(
                    SearchItem(
                        title=f"DuckDuckGo Result {i + 1}", url=item, description=None
                    )
                )
            # 如果结果是字典
            elif isinstance(item, dict):
                # 从字典中提取数据，DuckDuckGo返回的字段为title、href和body
                results.append(
                    SearchItem(
                        title=item.get("title", f"DuckDuckGo Result {i + 1}"),  # 获取标题或使用默认值
                        url=item.get("href", ""),  # 获取URL（在href字段中）
                        description=item.get("body", None),  # 获取描述（在body字段中）
                    )
                )
            # 如果结果是其他类型的对象
            else:
                # 尝试直接提取属性
                try:
                    # 使用getattr尝试直接从对象中获取属性
                    results.append(
                        SearchItem(
                            title=getattr(item, "title", f"DuckDuckGo Result {i + 1}"),  # 获取标题属性或使用默认值
                            url=getattr(item, "href", ""),  # 获取URL属性或使用空字符串
                            description=getattr(item, "body", None),  # 获取描述属性或使用None
                        )
                    )
                except Exception:
                    # 如果无法获取属性，使用备用方案
                    results.append(
                        SearchItem(
                            title=f"DuckDuckGo Result {i + 1}",  # 使用默认标题
                            url=str(item),  # 将项转换为字符串作为URL
                            description=None,  # 没有描述
                        )
                    )

        # 返回标准化的搜索结果列表
        return results
