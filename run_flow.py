"""
OpenManus 多代理流程入口文件

这个文件是 OpenManus 项目的多代理流程入口点，实现了基于规划流程(Planning Flow)的多代理协作执行模式。
该模式下，系统会创建一个执行计划，并由多个代理协作完成该计划的每个步骤。
整个执行过程设有超时限制和异常处理机制。
"""

import asyncio
import time

from app.agent.manus import Manus
from app.flow.flow_factory import FlowFactory, FlowType
from app.logger import logger


async def run_flow():
    """
    多代理流程执行函数
    
    功能:
    1. 初始化代理集合，当前只使用了 Manus 代理，但设计上支持多代理
    2. 创建规划流程(Planning Flow)
    3. 执行流程并监控执行时间
    4. 处理各类异常情况（超时、用户中断、其他异常）
    """
    # 初始化代理集合，可以扩展为多个不同的代理
    agents = {
        "manus": Manus(),
    }

    try:
        # 获取用户输入
        prompt = input("Enter your prompt: ")

        # 检查用户输入是否为空
        if prompt.strip().isspace() or not prompt:
            logger.warning("Empty prompt provided.")
            return

        # 使用流程工厂创建规划流程
        flow = FlowFactory.create_flow(
            flow_type=FlowType.PLANNING,  # 使用规划流程类型
            agents=agents,               # 指定要使用的代理集合
        )
        logger.warning("Processing your request...")

        try:
            # 记录开始时间用于计算执行时间
            start_time = time.time()
            # 使用asyncio.wait_for设置最大超时时间，防止执行时间过长
            result = await asyncio.wait_for(
                flow.execute(prompt),     # 执行流程处理用户输入
                timeout=3600,             # 60分钟超时限制
            )
            # 计算总执行时间
            elapsed_time = time.time() - start_time
            logger.info(f"Request processed in {elapsed_time:.2f} seconds")
            logger.info(result)
        except asyncio.TimeoutError:
            # 处理超时异常
            logger.error("Request processing timed out after 1 hour")
            logger.info(
                "Operation terminated due to timeout. Please try a simpler request."
            )

    except KeyboardInterrupt:
        # 处理用户手动中断操作
        logger.info("Operation cancelled by user.")
    except Exception as e:
        # 处理其他所有异常
        logger.error(f"Error: {str(e)}")


if __name__ == "__main__":
    # 使用 asyncio 运行异步主函数
    asyncio.run(run_flow())
