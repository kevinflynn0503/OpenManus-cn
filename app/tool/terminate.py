"""终止工具模块

这个模块定义了 Terminate 工具类，该工具用于在代理完成全部任务或无法继续时
终止代理的执行。这是一个特殊工具，在 ToolCallAgent 类中受到特殊处理。
当这个工具被调用时，代理会将其状态设置为 FINISHED，从而结束执行循环。
"""

from app.tool.base import BaseTool


# 终止工具的描述文本，用于指导语言模型何时调用该工具
_TERMINATE_DESCRIPTION = """Terminate the interaction when the request is met OR if the assistant cannot proceed further with the task.
When you have finished all the tasks, call this tool to end the work."""


class Terminate(BaseTool):
    """终止工具类，用于结束代理的执行循环。
    
    这个工具在以下情况下应被调用：
    1. 当所有任务都已完成
    2. 当代理无法继续处理任务
    
    
    调用该工具会触发 ToolCallAgent._handle_special_tool 方法，将代理状态设置为 FINISHED。
    """
    # 工具名称
    name: str = "terminate"
    # 工具描述
    description: str = _TERMINATE_DESCRIPTION
    # 工具参数模式
    parameters: dict = {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "description": "The finish status of the interaction.",
                "enum": ["success", "failure"], # 允许的状态值：成功或失败
            }
        },
        "required": ["status"],  # status 是必需参数
    }

    async def execute(self, status: str) -> str:
        """结束当前执行并返回状态信息。
        
        这个方法简单地返回一条完成消息，实际的终止逻辑在 ToolCallAgent 类中处理。
        
        参数:
            status: 执行状态，可以是 'success'(成功) 或 'failure'(失败)
            
        返回:
            str: 包含状态信息的完成消息
        """
        return f"The interaction has been completed with status: {status}"
