"""日志模块

这个模块提供了应用程序的日志记录功能，基于loguru库实现。它配置了日志的输出格式、级别和存储位置。
日志会同时输出到控制台和日志文件，可以分别设置不同的日志级别，便于调试和问题追踪。
日志文件会根据时间自动命名，并保存在项目根目录的logs文件夹中。
"""

import sys
from datetime import datetime

from loguru import logger as _logger

from app.config import PROJECT_ROOT


# 默认控制台打印日志级别
_print_level = "INFO"


def define_log_level(print_level="INFO", logfile_level="DEBUG", name: str = None):
    """设置日志级别和配置。
    
    这个函数负责配置日志的输出目标、级别和格式。它会设置两个日志输出:
    1. 控制台输出（stderr），级别由print_level参数控制
    2. 文件输出（保存在logs目录），级别由logfile_level参数控制
    
    日志文件会使用当前时间戳自动命名，如果提供name参数，则会使用name作为前缀。
    
    参数:
        print_level: 控制台输出的日志级别，默认为"INFO"
        logfile_level: 文件输出的日志级别，默认为"DEBUG"
        name: 可选的日志文件名称前缀
        
    返回:
        配置好的logger实例
    """
    global _print_level
    _print_level = print_level

    # 获取当前时间并格式化为字符串，用于日志文件命名
    current_date = datetime.now()
    formatted_date = current_date.strftime("%Y%m%d%H%M%S")
    # 构建日志文件名，如果提供了name参数，则添加为前缀
    log_name = (
        f"{name}_{formatted_date}" if name else formatted_date
    )  # 使用前缀和时间组合命名日志

    # 移除所有已经存在的日志处理器
    _logger.remove()
    # 添加控制台输出处理器
    _logger.add(sys.stderr, level=print_level)
    # 添加文件输出处理器，使用项目根目录下的logs文件夹
    _logger.add(PROJECT_ROOT / f"logs/{log_name}.log", level=logfile_level)
    return _logger


# 创建并配置默认的logger实例供应用程序使用
logger = define_log_level()


# 如果直接运行这个模块，将执行一个简单的示例测试
if __name__ == "__main__":
    logger.info("Starting application")  # 信息级别日志
    logger.debug("Debug message")        # 调试级别日志
    logger.warning("Warning message")    # 警告级别日志
    logger.error("Error message")        # 错误级别日志
    logger.critical("Critical message")  # 危险级别日志

    # 测试异常日志记录
    try:
        raise ValueError("Test error")
    except Exception as e:
        # 记录异常信息及堆栈跟踪
        logger.exception(f"An error occurred: {e}")
