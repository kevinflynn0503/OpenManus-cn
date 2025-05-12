#!/usr/bin/env python
"""
MCP代理运行脚本

这个脚本提供了运行OpenManus MCP代理的各种方式，包括交互模式和单次提示模式。
MCP（Model Context Protocol）代理允许AI系统与外部工具和数据源进行交互，
扩展系统的能力范围。该脚本提供了灵活的命令行接口来配置和运行MCP代理。
"""

import argparse  # 用于解析命令行参数
import asyncio   # 用于异步操作
import sys       # 用于系统相关操作

from app.agent.mcp import MCPAgent  # 导入MCP代理
from app.config import config       # 导入配置
from app.logger import logger       # 导入日志器


class MCPRunner:
    """MCP代理运行器类，提供适当的路径处理和配置。
    
    这个类负责初始化和运行MCP代理，处理不同的连接类型（stdio或SSE），
    并提供多种运行模式，包括交互式和单提示模式。它封装了代理的生命周期管理，
    简化了MCP代理的使用过程。
    """

    def __init__(self):
        """初始化MCP运行器。
        
        设置必要的路径和引用，并创建MCP代理实例。
        """
        self.root_path = config.root_path  # 从配置中获取根路径
        self.server_reference = config.mcp_config.server_reference  # 获取服务器引用
        self.agent = MCPAgent()  # 创建MCP代理实例

    async def initialize(
        self,
        connection_type: str,
        server_url: str | None = None,
    ) -> None:
        """使用适当的连接初始化MCP代理。
        
        根据指定的连接类型（stdio或SSE）初始化MCP代理，建立与MCP服务器的连接。
        
        参数:
            connection_type: 连接类型，可以是'stdio'或'sse'
            server_url: 使用SSE连接时的服务器URL
        """
        logger.info(f"Initializing MCPAgent with {connection_type} connection...")

        if connection_type == "stdio":
            # 对于stdio连接，使用Python解释器启动服务器模块
            await self.agent.initialize(
                connection_type="stdio",
                command=sys.executable,  # Python解释器路径
                args=["-m", self.server_reference],  # 以模块方式运行服务器
            )
        else:  # sse
            # 对于SSE连接，直接连接到指定的URL
            await self.agent.initialize(connection_type="sse", server_url=server_url)

        logger.info(f"Connected to MCP server via {connection_type}")

    async def run_interactive(self) -> None:
        """在交互模式下运行代理。
        
        提供一个交互式界面，用户可以多次输入请求并获取响应，直到用户选择退出。
        这种模式适合对话式交互和调试使用。
        """
        print("\nMCP Agent Interactive Mode (type 'exit' to quit)\n")
        while True:
            # 获取用户输入
            user_input = input("\nEnter your request: ")
            # 检查是否是退出命令
            if user_input.lower() in ["exit", "quit", "q"]:
                break
            # 运行代理并获取响应
            response = await self.agent.run(user_input)
            # 显示代理的回复
            print(f"\nAgent: {response}")

    async def run_single_prompt(self, prompt: str) -> None:
        """使用单个提示运行代理。
        
        处理单个请求并返回结果，适合脚本或管道处理。
        
        参数:
            prompt: 要处理的提示或请求
        """
        await self.agent.run(prompt)

    async def run_default(self) -> None:
        """以默认模式运行代理。
        
        请求用户输入单个提示，处理它，然后退出。这是最基本的使用模式。
        """
        # 获取用户输入的提示
        prompt = input("Enter your prompt: ")
        if not prompt.strip():
            # 如果提示为空，发出警告并返回
            logger.warning("Empty prompt provided.")
            return

        # 处理用户请求
        logger.warning("Processing your request...")
        await self.agent.run(prompt)
        logger.info("Request processing completed.")

    async def cleanup(self) -> None:
        """清理代理资源。
        
        关闭与MCP服务器的连接并释放资源，确保程序可以干净地退出。
        """
        await self.agent.cleanup()
        logger.info("Session ended")


def parse_args() -> argparse.Namespace:
    """解析命令行参数。
    
    定义并处理程序接受的命令行参数，包括连接类型、服务器URL和运行模式等。
    
    返回:
        解析后的参数命名空间
    """
    # 创建参数解析器
    parser = argparse.ArgumentParser(description="Run the MCP Agent")
    # 添加连接类型参数
    parser.add_argument(
        "--connection",
        "-c",
        choices=["stdio", "sse"],  # 可选的连接类型
        default="stdio",          # 默认使用stdio连接
        help="Connection type: stdio or sse",
    )
    # 添加服务器URL参数
    parser.add_argument(
        "--server-url",
        default="http://127.0.0.1:8000/sse",  # 默认本地SSE服务器地址
        help="URL for SSE connection",
    )
    # 添加交互模式标志
    parser.add_argument(
        "--interactive", "-i", action="store_true", help="Run in interactive mode"
    )
    # 添加单提示参数
    parser.add_argument("--prompt", "-p", help="Single prompt to execute and exit")
    return parser.parse_args()


async def run_mcp() -> None:
    """MCP运行器的主入口点。
    
    解析命令行参数，创建运行器，初始化连接，并根据指定的模式运行代理。
    处理异常并确保在退出前清理资源。
    """
    args = parse_args()
    runner = MCPRunner()

    try:
        await runner.initialize(args.connection, args.server_url)

        if args.prompt:
            await runner.run_single_prompt(args.prompt)
        elif args.interactive:
            await runner.run_interactive()
        else:
            await runner.run_default()

    except KeyboardInterrupt:
        logger.info("Program interrupted by user")
    except Exception as e:
        logger.error(f"Error running MCPAgent: {str(e)}", exc_info=True)
        sys.exit(1)
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(run_mcp())
