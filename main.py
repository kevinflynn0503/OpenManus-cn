"""
OpenManus 主入口文件

这个文件是 OpenManus 项目的主入口点，实现了基本的用户交互流程和 Manus 代理的初始化和执行。
整个执行过程是异步的，使用 asyncio 进行异步操作管理。
"""

import asyncio

from app.agent.manus import Manus
from app.logger import logger


async def main():
    """
    主函数 - 异步执行 Manus 代理
    
    功能:
    1. 创建并初始化 Manus 代理
    2. 处理用户输入的提示词
    3. 执行代理处理过程
    4. 确保资源正确清理
    
    异常处理:
    - 捕获 KeyboardInterrupt 中断
    - 确保在任何情况下都会清理资源
    """
    # 创建并初始化 Manus 代理
    agent = await Manus.create()
    try:
        # 获取用户输入
        prompt = input("Enter your prompt: ")
        if not prompt.strip():
            logger.warning("Empty prompt provided.")
            return

        # 处理用户请求
        logger.warning("Processing your request...")
        await agent.run(prompt)
        logger.info("Request processing completed.")
    except KeyboardInterrupt:
        # 处理用户中断操作
        logger.warning("Operation interrupted.")
    finally:
        # 确保在退出前清理代理资源，防止资源泄漏
        await agent.cleanup()


if __name__ == "__main__":
    # 使用 asyncio 运行主函数
    asyncio.run(main())
