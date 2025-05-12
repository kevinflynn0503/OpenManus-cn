"""
搜索引擎基础模块

这个模块定义了搜索引擎的基础类和数据模型，为不同的搜索引擎实现提供通用接口。
它包含了搜索结果项（SearchItem）的定义和网络搜索引擎（WebSearchEngine）的基类。
所有特定的搜索引擎实现（如Google、Bing、百度等）都继承自这个基类。
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class SearchItem(BaseModel):
    """表示单个搜索结果项
    
    这个类定义了搜索结果的基本属性，包括标题、URL和描述。
    它被所有搜索引擎用来表示标准化的搜索结果，便于后续处理和展示。
    """

    title: str = Field(description="The title of the search result")  # 搜索结果的标题
    url: str = Field(description="The URL of the search result")  # 搜索结果的URL
    description: Optional[str] = Field(
        default=None, description="A description or snippet of the search result"  # 搜索结果的描述或摘要
    )

    def __str__(self) -> str:
        """搜索结果项的字符串表示。
        
        返回包含标题和URL的格式化字符串，用于显示和调试。
        """
        return f"{self.title} - {self.url}"


class WebSearchEngine(BaseModel):
    """网络搜索引擎的基类。
    
    这个类作为所有特定搜索引擎实现的基类，定义了通用的搜索接口。
    它提供了perform_search方法的标准签名，子类需要实现这个方法来执行实际的搜索操作。
    通过使用这个基类，不同的搜索引擎可以被统一处理，使它们可以在系统中无缝切换。
    """

    # 允许模型使用任意类型，这在处理第三方库时很有用
    model_config = {"arbitrary_types_allowed": True}

    def perform_search(
        self, query: str, num_results: int = 10, *args, **kwargs
    ) -> List[SearchItem]:
        """
        执行网络搜索并返回搜索结果项列表。
        
        这是一个抽象方法，子类必须实现该方法来提供特定搜索引擎的功能。
        它定义了标准的参数和返回类型，便于所有搜索引擎实现的一致性。

        参数:
            query (str): 要提交给搜索引擎的搜索查询。
            num_results (int, optional): 要返回的搜索结果数量。默认为10。
            args: 额外的位置参数。
            kwargs: 额外的关键字参数，如语言和国家设置。

        返回:
            List[SearchItem]: 与搜索查询匹配的SearchItem对象列表。
        """
        # 这是一个抽象方法，子类需要实现该方法
        raise NotImplementedError
