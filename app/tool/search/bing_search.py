"""
Bing搜索引擎模块

这个模块提供了BingSearchEngine类，实现了WebSearchEngine接口来使用Bing搜索引擎。
不同于Google搜索实现，这个实现直接解析Bing的HTML搜索结果页面，并使用伪造的浏览器头信息
来模拟正常的用户访问。这个实现支持分页获取结果，并且能够从搜索结果中提取标题、URL和描述。
"""

from typing import List, Optional, Tuple

import requests  # 用于发送HTTP请求
from bs4 import BeautifulSoup  # 用于解析HTML

from app.logger import logger  # 用于记录日志
from app.tool.search.base import SearchItem, WebSearchEngine  # 导入搜索基础类


# 搜索结果描述的最大长度，超过这个长度将会被截断
ABSTRACT_MAX_LENGTH = 300

# 用户代理字符串列表，用于伪造浏览器访问，降低被封禁的风险
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/68.0.3440.106 Safari/537.36",
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Ubuntu Chromium/49.0.2623.108 Chrome/49.0.2623.108 Safari/537.36",
    "Mozilla/5.0 (Windows; U; Windows NT 5.1; pt-BR) AppleWebKit/533.3 (KHTML, like Gecko) QtWeb Internet Browser/3.7 http://www.QtWeb.net",
    "Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/41.0.2228.0 Safari/537.36",
    "Mozilla/5.0 (Windows; U; Windows NT 5.1; en-US) AppleWebKit/532.2 (KHTML, like Gecko) ChromePlus/4.0.222.3 Chrome/4.0.222.3 Safari/532.2",
    "Mozilla/5.0 (Windows; U; Windows NT 5.1; en-US; rv:1.8.1.4pre) Gecko/20070404 K-Ninja/2.1.3",
    "Mozilla/5.0 (Future Star Technologies Corp.; Star-Blade OS; x86_64; U; en-US) iNet Browser 4.7",
    "Mozilla/5.0 (Windows; U; Windows NT 6.1; rv:2.2) Gecko/20110201",
    "Mozilla/5.0 (Windows; U; Windows NT 5.1; en-US; rv:1.8.1.13) Gecko/20080414 Firefox/2.0.0.13 Pogo/2.0.0.13.6866",
]

# HTTP请求头信息，用于模拟正常的浏览器请求
HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",  # 接受的内容类型
    "Content-Type": "application/x-www-form-urlencoded",  # 内容类型
    "User-Agent": USER_AGENTS[0],  # 用户代理字符串，使用第一个作为默认
    "Referer": "https://www.bing.com/",  # 访问来源
    "Accept-Encoding": "gzip, deflate",  # 接受的编码
    "Accept-Language": "zh-CN,zh;q=0.9",  # 接受的语言
}

# Bing搜索的基础URL
BING_HOST_URL = "https://www.bing.com"  # Bing主机域URL
BING_SEARCH_URL = "https://www.bing.com/search?q="  # Bing搜索URL前缀，后面需要追加查询字符串


class BingSearchEngine(WebSearchEngine):
    """
    Bing搜索引擎实现类。
    
    这个类继承自WebSearchEngine基类，实现了使用Bing搜索引擎执行搜索的功能。
    它通过解析Bing的HTML搜索结果页面来获取搜索结果，并支持分页获取更多结果。
    为了模拟正常的浏览器行为，该类使用请求会话并设置特定的HTTP头信息。
    """
    # 请求会话，用于维持连接并复用HTTP连接
    session: Optional[requests.Session] = None

    def __init__(self, **data):
        """使用requests会话初始化BingSearch工具。
        
        这个构造方法创建一个请求会话并设置适当的HTTP头信息，以模拟正常的浏览器行为。
        这样可以降低被Bing识别为爬虫并被封禁的风险。
        
        参数:
            **data: 传递给父类的额外参数
        """
        super().__init__(**data)
        # 创建新的请求会话
        self.session = requests.Session()
        # 更新会话的头信息，使用预定义的HEADERS
        self.session.headers.update(HEADERS)

    def _search_sync(self, query: str, num_results: int = 10) -> List[SearchItem]:
        """
        同步实现Bing搜索并获取搜索结果。
        
        这个内部方法执行同步Bing搜索，并在需要时获取多页结果。它通过循环调用
        _parse_html方法来解析搜索结果页面，直到获取足够的结果或者没有更多的结果页面。

        参数:
            query (str): 要提交给Bing的搜索查询。
            num_results (int, optional): 要返回的最大结果数量。默认为10。

        返回:
            List[SearchItem]: 包含标题、URL和描述的搜索结果项列表。
        """
        # 检查查询是否为空，如果为空则返回空列表
        if not query:
            return []

        # 初始化结果列表
        list_result = []
        # 初始化第一页的索引参数
        first = 1
        # 初始化搜索URL，连接基础URL和查询字符串
        next_url = BING_SEARCH_URL + query

        # 循环获取结果，直到获得足够的结果数量
        while len(list_result) < num_results:
            # 解析当前页面并获取数据及下一页URL
            data, next_url = self._parse_html(
                next_url, rank_start=len(list_result), first=first
            )
            # 如果有数据，添加到结果列表
            if data:
                list_result.extend(data)
            # 如果没有下一页URL，说明已经到达最后一页，退出循环
            if not next_url:
                break
            # 页面参数递增，每页结果数为10
            first += 10

        # 返回指定数量的结果
        return list_result[:num_results]

    def _parse_html(
        self, url: str, rank_start: int = 0, first: int = 1
    ) -> Tuple[List[SearchItem], str]:
        """
        Parse Bing search result HTML to extract search results and the next page URL.

        Returns:
            tuple: (List of SearchItem objects, next page URL or None)
        """
        try:
            res = self.session.get(url=url)
            res.encoding = "utf-8"
            root = BeautifulSoup(res.text, "lxml")

            list_data = []
            ol_results = root.find("ol", id="b_results")
            if not ol_results:
                return [], None

            for li in ol_results.find_all("li", class_="b_algo"):
                title = ""
                url = ""
                abstract = ""
                try:
                    h2 = li.find("h2")
                    if h2:
                        title = h2.text.strip()
                        url = h2.a["href"].strip()

                    p = li.find("p")
                    if p:
                        abstract = p.text.strip()

                    if ABSTRACT_MAX_LENGTH and len(abstract) > ABSTRACT_MAX_LENGTH:
                        abstract = abstract[:ABSTRACT_MAX_LENGTH]

                    rank_start += 1

                    # Create a SearchItem object
                    list_data.append(
                        SearchItem(
                            title=title or f"Bing Result {rank_start}",
                            url=url,
                            description=abstract,
                        )
                    )
                except Exception:
                    continue

            next_btn = root.find("a", title="Next page")
            if not next_btn:
                return list_data, None

            next_url = BING_HOST_URL + next_btn["href"]
            return list_data, next_url
        except Exception as e:
            logger.warning(f"Error parsing HTML: {e}")
            return [], None

    def perform_search(
        self, query: str, num_results: int = 10, *args, **kwargs
    ) -> List[SearchItem]:
        """
        Bing search engine.

        Returns results formatted according to SearchItem model.
        """
        return self._search_sync(query, num_results=num_results)
