"""异常定义模块

该模块定义了OpenManus项目中使用的各种自定义异常类。这些异常类用于在程序运行时
标识并处理特定类型的错误情况，如工具错误、令牌限制超出等。每个异常类都继承自
基本的Exception类或项目的基础异常类OpenManusError，以允许分层捕获和处理异常。
"""

class ToolError(Exception):
    """当工具遇到错误时抛出该异常。
    
    这个异常类用于标识工具调用过程中发生的错误，包括但不限于参数错误、
    执行失败或资源不可用等情况。它包含一个错误消息，描述发生的错误。
    """

    def __init__(self, message):
        """初始化工具错误异常。
        
        参数:
            message: 描述错误的消息字符串
        """
        self.message = message


class OpenManusError(Exception):
    """所有OpenManus错误的基础异常类。
    
    这个类作为项目中所有自定义异常的父类，便于统一处理和分类各种类型的错误。
    通过在try-except块中捕获这个基础异常，可以一次性处理所有类型的OpenManus特定错误。
    """


class TokenLimitExceeded(OpenManusError):
    """当超过令牌限制时抛出的异常。
    
    这个异常用于标识请求所需的令牌数量超过了设置的限制的情况。
    它通常在与API交互前检查令牌限制时抛出，以防止发送过大的请求并避免不必要的API费用。
    这个异常不会被重试机制捕获并重试，因为这是一个预计的限制而非临时问题。
    """
