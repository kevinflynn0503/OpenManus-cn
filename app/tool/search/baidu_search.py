"""
百度搜索引擎模块

这个模块提供了BaiduSearchEngine类，实现了WebSearchEngine接口来使用百度搜索引擎。
它使用baidusearch库来执行实际的搜索请求，并处理不同格式的搜索结果，将它们转换为
标准的SearchItem对象。这个模块为系统提供了面向中文用户的搜索功能。
"""

from typing import List

# 使用baidusearch库来执行百度搜索查询
from baidusearch.baidusearch import search

# 导入搜索基础类和搜索结果项模型
from app.tool.search.base import SearchItem, WebSearchEngine


class BaiduSearchEngine(WebSearchEngine):
    """
    百度搜索引擎实现类。
    
    这个类继承自WebSearchEngine基类，提供了使用百度搜索引擎执行搜索的实现。
    它使用baidusearch库来执行实际的搜索请求，并处理不同格式的搜索结果返回。
    由于百度网页为中文用户提供更相关的内容，这个实现对于中文查询特别有用。
    """
    def perform_search(
        self, query: str, num_results: int = 10, *args, **kwargs
    ) -> List[SearchItem]:
        """
        执行百度搜索并返回格式化的搜索结果。
        
        这个方法实现了WebSearchEngine基类中的抽象方法，使用baidusearch库
        来执行实际的搜索查询。由于百度搜索结果可能以不同的格式返回，
        这个方法处理多种结果类型，并将它们转换为标准的SearchItem对象。
        
        参数:
            query: 搜索查询字符串
            num_results: 要返回的结果数量（默认为10）
            *args, **kwargs: 传递给搜索引擎的额外参数
            
        返回:
            按照SearchItem模型格式化的搜索结果列表
        """
        # 使用baidusearch库执行搜索查询
        raw_results = search(query, num_results=num_results)

        # 将原始结果转换为SearchItem格式
        results = []
        # 遍历所有原始搜索结果
        for i, item in enumerate(raw_results):
            # 如果结果只是一个字符串URL
            if isinstance(item, str):
                # 如果只是URL，创建一个带默认标题的搜索结果
                results.append(
                    SearchItem(title=f"Baidu Result {i+1}", url=item, description=None)
                )
            # 如果结果是一个字典
            elif isinstance(item, dict):
                # 如果是包含详细信息的字典，提取相关字段
                results.append(
                    SearchItem(
                        title=item.get("title", f"Baidu Result {i+1}"),  # 获取标题或使用默认值
                        url=item.get("url", ""),  # 获取URL或使用空字符串
                        description=item.get("abstract", None),  # 获取描述或使用None
                    )
                )
            # 如果结果是其他类型的对象
            else:
                # 尝试直接获取属性
                try:
                    # 尝试直接使用getattr获取对象属性
                    results.append(
                        SearchItem(
                            title=getattr(item, "title", f"Baidu Result {i+1}"),  # 获取标题属性或使用默认值
                            url=getattr(item, "url", ""),  # 获取URL属性或使用空字符串
                            description=getattr(item, "abstract", None),  # 获取描述属性或使用None
                        )
                    )
                except Exception:
                    # 如果无法获取属性，回退到基本结果
                    results.append(
                        SearchItem(
                            title=f"Baidu Result {i+1}", url=str(item), description=None
                        )
                    )

        # 返回标准化的搜索结果列表
        return results
