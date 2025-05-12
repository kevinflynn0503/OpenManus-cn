"""
异步Docker终端模块

该模块为Docker容器提供异步终端功能，支持交互式命令执行并具备超时控制能力。
主要功能包括：

1. 创建与容器的交互式会话连接
2. 在定义的工作目录中执行命令
3. 支持设置环境变量
4. 提供超时控制机制
5. 并发处理多个容器会话

该模块使用低级别Docker API和套接字通信，实现了与容器的实时交互，
远超过普通Docker exec命令的能力。其异步设计确保了在重负载情况下的高效性能。
"""

import asyncio
import re
import socket
from typing import Dict, Optional, Tuple, Union

import docker
from docker import APIClient
from docker.errors import APIError
from docker.models.containers import Container


class DockerSession:
    """与Docker容器的交互式会话管理类。
    
    该类提供了与Docker容器建立交互式终端会话的功能，支持实时命令执行、
    输出捕获和会话管理。它使用低级别Docker API和套接字连接，实现了真正的
    交互式终端功能，可以模拟用户在容器内部的shell会话。
    
    该类采用异步设计，所有的网络和命令执行操作都是非阻塞的，以确保
    在并发场景下的高效性能。
    """
    
    def __init__(self, container_id: str) -> None:
        """初始化Docker会话对象。

        创建一个新的DockerSession实例，用于与指定的Docker容器建立交互。
        初始化时只设置必要的属性，实际的连接需要调用create方法来建立。

        参数:
            container_id: Docker容器的ID。
        """
        self.api = APIClient()
        self.container_id = container_id
        self.exec_id = None
        self.socket = None

    async def create(self, working_dir: str, env_vars: Dict[str, str]) -> None:
        """创建与容器的交互式会话。

        该方法使用Docker API在容器内部启动一个交互式的bash会话，并建立一个套接字连接
        用于后续的命令发送和输出捕获。方法会设置Bash提示符为简单的'$ '格式，
        以便于输出解析。该方法必须在使用一个会话进行任何其他操作之前调用。

        参数:
            working_dir: 容器内的工作目录。
            env_vars: 要设置的环境变量字典。

        抛出:
            RuntimeError: 如果套接字连接失败。
        """

        startup_command = [
            "bash",
            "-c",
            f"cd {working_dir} && "
            "PROMPT_COMMAND='' "
            "PS1='$ ' "
            "exec bash --norc --noprofile",
        ]

        exec_data = self.api.exec_create(
            self.container_id,
            startup_command,
            stdin=True,
            tty=True,
            stdout=True,
            stderr=True,
            privileged=True,
            user="root",
            environment={**env_vars, "TERM": "dumb", "PS1": "$ ", "PROMPT_COMMAND": ""},
        )
        self.exec_id = exec_data["Id"]

        socket_data = self.api.exec_start(
            self.exec_id, socket=True, tty=True, stream=True, demux=True
        )

        if hasattr(socket_data, "_sock"):
            self.socket = socket_data._sock
            self.socket.setblocking(False)
        else:
            raise RuntimeError("Failed to get socket connection")

        await self._read_until_prompt()

    async def close(self) -> None:
        """清理会话资源。

        该方法负责安全地清理与容器交互会话相关的所有资源，执行以下操作：

        1. 向容器发送exit命令，优雅地结束终端会话
        2. 关闭并清理套接字连接
        3. 清理Docker exec实例资源

        这个方法实现了错误容错机制，确保即使在清理过程中发生错误，
        也会尽可能地释放所有资源。在会话结束时应始终调用此方法。
        """
        try:
            if self.socket:
                # Send exit command to close bash session
                try:
                    self.socket.sendall(b"exit\n")
                    # Allow time for command execution
                    await asyncio.sleep(0.1)
                except:
                    pass  # Ignore sending errors, continue cleanup

                # Close socket connection
                try:
                    self.socket.shutdown(socket.SHUT_RDWR)
                except:
                    pass  # Some platforms may not support shutdown

                self.socket.close()
                self.socket = None

            if self.exec_id:
                try:
                    # Check exec instance status
                    exec_inspect = self.api.exec_inspect(self.exec_id)
                    if exec_inspect.get("Running", False):
                        # If still running, wait for it to complete
                        await asyncio.sleep(0.5)
                except:
                    pass  # Ignore inspection errors, continue cleanup

                self.exec_id = None

        except Exception as e:
            # Log error but don't raise, ensure cleanup continues
            print(f"Warning: Error during session cleanup: {e}")

    async def _read_until_prompt(self) -> str:
        """读取输出直到找到提示符。

        该方法从容器的套接字连接中持续读取数据，直到发现终端提示符('$ ')，
        表示容器内的命令执行已经完成并且终端就绪接收新的命令。这是一个内部
        帮助方法，用于同步命令执行流程。
        
        该方法实现了非阻塞读取，当没有数据可用时会使用asyncio.sleep让出当前协程。

        返回:
            含有输出内容直到提示符的字符串。

        抛出:
            socket.error: 如果套接字通信失败。
        """
        buffer = b""
        while b"$ " not in buffer:
            try:
                chunk = self.socket.recv(4096)
                if chunk:
                    buffer += chunk
            except socket.error as e:
                if e.errno == socket.EWOULDBLOCK:
                    await asyncio.sleep(0.1)
                    continue
                raise
        return buffer.decode("utf-8")

    async def execute(self, command: str, timeout: Optional[int] = None) -> str:
        """执行命令并返回处理过的输出结果。

        该方法在容器内执行指定的shell命令，并返回命令的输出。它进行了安全处理
        以防止shell注入，并实现了超时控制机制。该方法自动添加一个'echo $?'命令
        来捕获命令的返回状态码。输出结果会被清理，移除命令提示符和其他非命令输出。

        参数:
            command: 要执行的shell命令。
            timeout: 最大执行时间（秒），如果为None则无超时限制。

        返回:
            已移除提示符标记的命令输出字符串。

        抛出:
            RuntimeError: 如果会话未初始化或执行失败。
            TimeoutError: 如果命令执行超过超时时间。
        """
        if not self.socket:
            raise RuntimeError("Session not initialized")

        try:
            # Sanitize command to prevent shell injection
            sanitized_command = self._sanitize_command(command)
            full_command = f"{sanitized_command}\necho $?\n"
            self.socket.sendall(full_command.encode())

            async def read_output() -> str:
                buffer = b""
                result_lines = []
                command_sent = False

                while True:
                    try:
                        chunk = self.socket.recv(4096)
                        if not chunk:
                            break

                        buffer += chunk
                        lines = buffer.split(b"\n")

                        buffer = lines[-1]
                        lines = lines[:-1]

                        for line in lines:
                            line = line.rstrip(b"\r")

                            if not command_sent:
                                command_sent = True
                                continue

                            if line.strip() == b"echo $?" or line.strip().isdigit():
                                continue

                            if line.strip():
                                result_lines.append(line)

                        if buffer.endswith(b"$ "):
                            break

                    except socket.error as e:
                        if e.errno == socket.EWOULDBLOCK:
                            await asyncio.sleep(0.1)
                            continue
                        raise

                output = b"\n".join(result_lines).decode("utf-8")
                output = re.sub(r"\n\$ echo \$\$?.*$", "", output)

                return output

            if timeout:
                result = await asyncio.wait_for(read_output(), timeout)
            else:
                result = await read_output()

            return result.strip()

        except asyncio.TimeoutError:
            raise TimeoutError(f"Command execution timed out after {timeout} seconds")
        except Exception as e:
            raise RuntimeError(f"Failed to execute command: {e}")

    def _sanitize_command(self, command: str) -> str:
        """清洗命令字符串以防止shell注入。

        该方法检查命令是否包含潜在的危险操作，以防止运行可能损坏系统的命令。
        它会检查命令中是否包含危险的模式，例如删除根目录、格式化磁盘、fork炸弹等。
        如果发现危险模式，将抛出异常而不执行命令。

        参数:
            command: 原始命令字符串。

        返回:
            清洗过的命令字符串。

        抛出:
            ValueError: 如果命令包含潜在危险的模式。
        """

        # Additional checks for specific risky commands
        risky_commands = [
            "rm -rf /",
            "rm -rf /*",
            "mkfs",
            "dd if=/dev/zero",
            ":(){:|:&};:",
            "chmod -R 777 /",
            "chown -R",
        ]

        for risky in risky_commands:
            if risky in command.lower():
                raise ValueError(
                    f"Command contains potentially dangerous operation: {risky}"
                )

        return command


class AsyncDockerizedTerminal:
    """异步Docker终端高级封装类。
    
    该类提供了对DockerSession的更高级别封装，简化了与Docker容器交互的操作。
    它封装了会话初始化、命令执行和资源清理等复杂操作，提供了一个简单的
    接口来执行容器命令和管理容器会话。
    
    该类支持异步上下文管理器模式(使用async with)，在上下文退出时自动清理资源。
    它还提供了工作目录管理和环境变量设置功能。
    """
    
    def __init__(
        self,
        container: Union[str, Container],
        working_dir: str = "/workspace",
        env_vars: Optional[Dict[str, str]] = None,
        default_timeout: int = 60,
    ) -> None:
        """初始化Docker容器的异步终端。

        创建一个新的AsyncDockerizedTerminal实例，用于与指定的Docker容器进行交互。
        初始化仅设置基本属性，实际的会话初始化需要调用init方法来完成。

        参数:
            container: Docker容器ID或Container对象。
            working_dir: 容器内的工作目录。
            env_vars: 要设置的环境变量字典。
            default_timeout: 默认命令执行超时时间（秒）。
        """
        self.client = docker.from_env()
        self.container = (
            container
            if isinstance(container, Container)
            else self.client.containers.get(container)
        )
        self.working_dir = working_dir
        self.env_vars = env_vars or {}
        self.default_timeout = default_timeout
        self.session = None

    async def init(self) -> None:
        """初始化终端环境。

        该方法确保工作目录存在并创建一个交互式会话。它首先调用_ensure_workdir方法
        确保容器内工作目录存在，然后创建一个DockerSession实例并初始化与容器的交互会话。
        在能开始执行命令和其他操作之前，必须先调用该方法。

        抛出:
            RuntimeError: 如果初始化失败。
        """
        await self._ensure_workdir()

        self.session = DockerSession(self.container.id)
        await self.session.create(self.working_dir, self.env_vars)

    async def _ensure_workdir(self) -> None:
        """确保容器内工作目录存在。

        该方法使用'mkdir -p'命令在容器内创建工作目录，如果该目录已经存在则不会报错。
        这是一个内部帮助方法，用于确保在容器中初始化工作环境。

        抛出:
            RuntimeError: 如果目录创建失败。
        """
        try:
            await self._exec_simple(f"mkdir -p {self.working_dir}")
        except APIError as e:
            raise RuntimeError(f"Failed to create working directory: {e}")

    async def _exec_simple(self, cmd: str) -> Tuple[int, str]:
        """使用Docker的exec_run执行简单命令。

        该方法使用Docker客户端的exec_run方法在容器中执行简单的命令。与交互式会话不同，
        这种方式适合执行短期、非交互式的命令，比如创建目录、检查文件等。
        该方法使用asyncio.to_thread将同步的Docker API调用转化为异步操作。

        参数:
            cmd: 要执行的命令。

        返回:
            包含退出代码和输出的元组(exit_code, output)。
        """
        result = await asyncio.to_thread(
            self.container.exec_run, cmd, environment=self.env_vars
        )
        return result.exit_code, result.output.decode("utf-8")

    async def run_command(self, cmd: str, timeout: Optional[int] = None) -> str:
        """在容器中运行命令并提供超时控制。

        该方法是类的主要公共接口，用于在容器中执行命令并返回结果。它使用底层的
        DockerSession会话执行命令，并应用指定的超时设置。如果未提供超时值，则使用实例
        初始化时设置的默认值。在调用此方法前，必须先调用init方法初始化会话。

        参数:
            cmd: 要执行的Shell命令。
            timeout: 最大执行时间（秒）。

        返回:
            命令输出字符串。

        抛出:
            RuntimeError: 如果终端未初始化。
            TimeoutError: 如果命令执行超时。
        """
        if not self.session:
            raise RuntimeError("Terminal not initialized")

        return await self.session.execute(cmd, timeout=timeout or self.default_timeout)

    async def close(self) -> None:
        """关闭终端会话。
        
        该方法清理并关闭与容器的交互会话。它调用底层DockerSession的close方法
        来释放所有相关的资源，包括关闭套接字连接和清理exec实例。在结束使用
        终端时应该调用此方法以避免资源泄漏。当使用异步上下文管理器时，
        该方法会自动在退出上下文时调用。
        """
        if self.session:
            await self.session.close()

    async def __aenter__(self) -> "AsyncDockerizedTerminal":
        """异步上下文管理器入口方法。
        
        该方法在使用`async with`语法创建实例时被调用。它自动调用init方法
        初始化终端会话，包括确保工作目录存在和创建交互式会话。
        
        这个方法的存在允许用户使用以下更简洁的方式使用终端：
        ```python
        async with AsyncDockerizedTerminal(container_id) as terminal:
            result = await terminal.run_command('echo "hello world"')
        ```
        
        返回:
            AsyncDockerizedTerminal: 终端实例本身。
        """
        await self.init()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """异步上下文管理器退出方法。
        
        该方法在使用`async with`语法的上下文块结束时被调用。它自动调用close方法
        清理和关闭终端会话，确保即使在发生异常时也能正确释放资源。
        
        参数:
            exc_type: 异常类型（如果有）。
            exc_val: 异常值（如果有）。
            exc_tb: 异常跟踪信息（如果有）。
        """
        await self.close()
