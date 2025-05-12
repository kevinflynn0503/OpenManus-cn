# coding: utf-8
"""
MCP服务器启动脚本

这个脚本是启动OpenManus MCP（Model Context Protocol）服务器的快捷方式。
MCP是一个标准协议，允许AI系统与外部工具和数据源进行交互。
该脚本导入并运行服务器，同时解决了相关的导入问题。
"""

from app.mcp.server import MCPServer, parse_args


if __name__ == "__main__":
    # 解析命令行参数
    args = parse_args()

    # 创建并运行服务器（保持原始流程）
    server = MCPServer()
    server.run(transport=args.transport)  # 使用指定的传输方式运行服务器
