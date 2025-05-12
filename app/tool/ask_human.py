"""人类交互工具模块。

该模块提供了一个简单的工具，允许AI代理向人类用户提问问题并获取答复。
这在需要人类决策、确认或提供额外信息的情况下非常有用。
"""

from app.tool import BaseTool


class AskHuman(BaseTool):
    """添加一个工具，用于向人类寻求帮助。
    
    这个工具允许AI代理向人类用户提出问题，并等待用户的响应。
    当AI需要用户输入、意见或决策时，这个工具非常有用。
    """

    name: str = "ask_human"  # 工具名称
    description: str = "Use this tool to ask human for help."  # 工具描述
    parameters: str = {
        "type": "object",
        "properties": {
            "inquire": {
                "type": "string",
                "description": "The question you want to ask human.",  # 要询问人类的问题
            }
        },
        "required": ["inquire"],  # 必需参数
    }

    async def execute(self, inquire: str) -> str:
        """执行向人类提问的操作。
        
        此方法在命令行接口中显示一个提示，并等待用户输入响应。
        
        参数:
            inquire: 要提问的问题或信息
            
        返回:
            str: 用户的响应，已去除首尾空白
        """
        # 在命令行显示问题并收集用户输入
        return input(f"""Bot: {inquire}

You: """).strip()
