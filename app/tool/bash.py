"""
Bash命令执行工具模块。

该模块实现了一个可在终端中执行命令的工具，包括对长时间运行、交互式命令以及超时等情况的处理。
"""

import asyncio
import os
from typing import Optional

from app.exceptions import ToolError
from app.tool.base import BaseTool, CLIResult


_BASH_DESCRIPTION = """Execute a bash command in the terminal.
* Long running commands: For commands that may run indefinitely, it should be run in the background and the output should be redirected to a file, e.g. command = `python3 app.py > server.log 2>&1 &`.
* Interactive: If a bash command returns exit code `-1`, this means the process is not yet finished. The assistant must then send a second call to terminal with an empty `command` (which will retrieve any additional logs), or it can send additional text (set `command` to the text) to STDIN of the running process, or it can send command=`ctrl+c` to interrupt the process.
* Timeout: If a command execution result says "Command timed out. Sending SIGINT to the process", the assistant should retry running the command in the background.
"""


class _BashSession:
    """一个Bash shell会话的实现类。
    
    该类管理与终端的交互，包括启动bash进程、执行命令、读取输出和错误，
    以及处理超时和终止操作。
    """

    _started: bool  # 进程是否已启动
    _process: asyncio.subprocess.Process  # 子进程实例

    command: str = "/bin/bash"  # 要执行的shell命令
    _output_delay: float = 0.2  # 输出检测间隔（秒）
    _timeout: float = 120.0  # 超时时间（秒）
    _sentinel: str = "<<exit>>"  # 用于标记命令执行结束的标记字符串

    def __init__(self):
        """初始化Bash会话。
        
        初始化会话状态，包括设置未启动状态和未超时状态。
        """
        self._started = False  # 初始未启动
        self._timed_out = False  # 初始未超时

    async def start(self):
        """开始一个Bash会话。
        
        如果会话已经启动，则不做任何操作。否则，创建一个新的shell子进程。
        """
        if self._started:  # 如果已经启动，则不做任何操作
            return

        # 创建bash子进程，并设置输入和输出流
        self._process = await asyncio.create_subprocess_shell(
            self.command,
            preexec_fn=os.setsid,  # 使用进程组，便于后期终止全组进程
            shell=True,           # 使用系统的shell
            bufsize=0,            # 无缓冲区
            stdin=asyncio.subprocess.PIPE,   # 配置标准输入管道
            stdout=asyncio.subprocess.PIPE,  # 配置标准输出管道
            stderr=asyncio.subprocess.PIPE,  # 配置标准错误管道
        )

        self._started = True  # 标记会话已启动

    def stop(self):
        """终止bash shell进程。
        
        如果会话还未启动，则抛出错误。
        如果进程已经结束，则不做任何操作。
        否则终止进程。
        
        异常:
            ToolError: 当会话尚未启动时抛出
        """
        if not self._started:  # 检查会话是否启动
            raise ToolError("Session has not started.")
        if self._process.returncode is not None:  # 检查进程是否已结束
            return  # 如果进程已结束，不做操作
        self._process.terminate()  # 终止进程

    async def run(self, command: str):
        """在bash shell中执行命令。
        
        在已启动的shell中执行指定的命令，并收集输出。
        如果会话未启动、进程已结束或会话已超时，则抛出错误。
        
        参数:
            command: 要执行的命令字符串
            
        返回:
            CLIResult: 命令执行结果，包含标准输出和错误输出
            
        异常:
            ToolError: 在各种错误情况下抛出
        """
        # 检查会话是否已启动
        if not self._started:
            raise ToolError("Session has not started.")
        # 检查进程是否已结束
        if self._process.returncode is not None:
            return CLIResult(
                system="tool must be restarted",  # 系统信息提示需要重启工具
                error=f"bash has exited with returncode {self._process.returncode}",  # 错误信息包含退出码
            )
        # 检查是否已经超时
        if self._timed_out:
            raise ToolError(
                f"timed out: bash has not returned in {self._timeout} seconds and must be restarted",
            )

        # 确保输入和输出流存在（创建进程时指定了PIPE）
        assert self._process.stdin
        assert self._process.stdout
        assert self._process.stderr

        # 将命令发送到进程的标准输入
        # 在命令后附加一个响仪命令，输出哨兵字符以标记命令执行结束
        self._process.stdin.write(
            command.encode() + f"; echo '{self._sentinel}'\n".encode()
        )
        # 等待写入完成
        await self._process.stdin.drain()

        # 从进程读取输出，直到找到哨兵字符串
        try:
            # 使用超时机制防止命令无限期执行
            async with asyncio.timeout(self._timeout):
                while True:
                    # 间隔一定时间检查输出
                    await asyncio.sleep(self._output_delay)
                    # 直接从 stdout/stderr 读取会无限期等待EOF
                    # 因此直接访问 StreamReader 的缓冲区
                    output = (
                        self._process.stdout._buffer.decode()
                    )  # pyright: ignore[reportAttributeAccessIssue]
                    # 检查是否包含哨兵字符串，表示命令执行完毕
                    if self._sentinel in output:
                        # 去除哨兵字符串及其后的内容
                        output = output[: output.index(self._sentinel)]
                        break  # 找到哨兵字符串，跳出循环
        except asyncio.TimeoutError:
            # 如果超时，标记会话为超时状态
            self._timed_out = True
            # 抛出错误，提示需要重启
            raise ToolError(
                f"timed out: bash has not returned in {self._timeout} seconds and must be restarted",
            ) from None

        # 如果输出以换行符结尾，则移除最后的换行符
        if output.endswith("\n"):
            output = output[:-1]

        # 读取错误输出
        error = (
            self._process.stderr._buffer.decode()
        )  # pyright: ignore[reportAttributeAccessIssue]
        # 同样移除错误输出结尾的换行符
        if error.endswith("\n"):
            error = error[:-1]

        # 清空缓冲区，以便下次读取输出时不会包含当前输出
        self._process.stdout._buffer.clear()  # pyright: ignore[reportAttributeAccessIssue]
        self._process.stderr._buffer.clear()  # pyright: ignore[reportAttributeAccessIssue]

        # 返回命令执行结果，包含标准输出和错误输出
        return CLIResult(output=output, error=error)


class Bash(BaseTool):
    """用于执行Bash命令的工具类。
    
    该工具允许在终端中执行命令，并处理一系列特殊情况，
    如长时间运行的命令、交互式命令和超时情况。
    """

    name: str = "bash"  # 工具名称
    description: str = _BASH_DESCRIPTION  # 工具描述
    parameters: dict = {  # 参数定义
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The bash command to execute. Can be empty to view additional logs when previous exit code is `-1`. Can be `ctrl+c` to interrupt the currently running process.",
            },
        },
        "required": ["command"],  # 必需参数
    }

    _session: Optional[_BashSession] = None  # Bash会话实例

    async def execute(
        self, command: str | None = None, restart: bool = False, **kwargs
    ) -> CLIResult:
        """执行Bash命令。
        
        参数:
            command: 要执行的Bash命令字符串，如果为None则只读取输出
            restart: 是否重新启动Bash会话
            **kwargs: 其他关键字参数
            
        返回:
            CLIResult: 命令执行结果
            
        异常:
            ToolError: 当没有提供命令或会话操作出错时抛出
        """
        # 如果需要重新启动会话
        if restart:
            # 如果存在当前会话，则停止它
            if self._session:
                self._session.stop()
            # 创建新的会话并启动
            self._session = _BashSession()
            await self._session.start()

            # 返回重启成功的消息
            return CLIResult(system="tool has been restarted.")

        # 如果还没有会话，创建并启动一个新的会话
        if self._session is None:
            self._session = _BashSession()
            await self._session.start()

        # 如果提供了命令，则执行该命令
        if command is not None:
            return await self._session.run(command)

        # 如果没有提供命令，抛出错误
        raise ToolError("no command provided.")


# 模块的测试代码，直接运行该模块时执行
# 测试bash工具执行一个简单的列出目录内容的命令
# 并打印返回结果
if __name__ == "__main__":
    bash = Bash()
    rst = asyncio.run(bash.execute("ls -l"))
    print(rst)
