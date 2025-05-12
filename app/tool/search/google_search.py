"""
Google搜索引擎模块

这个模块提供了GoogleSearchEngine类，实现了WebSearchEngine接口来使用Google搜索引擎。
它使用googlesearch库来执行实际的搜索请求并处理结果。
"""

from typing import List

# 使用googlesearch库来执行搜索查询
from googlesearch import search

# 导入搜索基础类和搜索结果项模型
from app.tool.search.base import SearchItem, WebSearchEngine


class GoogleSearchEngine(WebSearchEngine):
    """
    Google搜索引擎实现类。
    
    这个类继承自WebSearchEngine基类，提供了使用Google搜索引擎执行搜索的实现。
    它使用googlesearch库来执行实际的搜索请求，并将结果转换为标准的SearchItem对象。
    """
    def perform_search(
        self, query: str, num_results: int = 10, *args, **kwargs
    ) -> List[SearchItem]:
        """
        执行Google搜索并返回格式化的搜索结果。
        
        这个方法实现了WebSearchEngine基类中的抽象方法，使用googlesearch库
        来执行实际的搜索查询。它处理不同类型的搜索结果，并将它们转换为
        标准的SearchItem对象。
        
        参数:
            query: 搜索查询字符串
            num_results: 要返回的结果数量（默认为10）
            *args, **kwargs: 传递给搜索引擎的额外参数
            
        返回:
            按照SearchItem模型格式化的搜索结果列表
        """
        # 使用googlesearch库执行搜索，启用高级模式以获取更详细的结果
        raw_results = search(query, num_results=num_results, advanced=True)

        # 初始化结果列表
        results = []
        # 遍历原始搜索结果并转换格式
        for i, item in enumerate(raw_results):
            if isinstance(item, str):
                # 如果结果只是一个URL字符串，创建一个带默认标题的结果
                results.append(
                    {"title": f"Google Result {i+1}", "url": item, "description": ""}
                )
            else:
                # 如果结果是一个带标题和描述的对象，创建标准SearchItem
                results.append(
                    SearchItem(
                        title=item.title, url=item.url, description=item.description
                    )
                )

        # 返回格式化的搜索结果列表
        return results
