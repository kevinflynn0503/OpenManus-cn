"""文件操作接口和实现模块。

这个模块定义了文件操作的通用接口(FileOperator)，以及在本地环境(LocalFileOperator)
和沙箱环境(SandboxFileOperator)中的实现。这些类负责文件的读写操作、路径检查和命令执行，
它们封装了不同环境下的实现细节，使得上层工具可以透明地在不同环境间切换。
"""

import asyncio
from pathlib import Path
from typing import Optional, Protocol, Tuple, Union, runtime_checkable

from app.config import SandboxSettings
from app.exceptions import ToolError
from app.sandbox.client import SANDBOX_CLIENT


# 路径类型别名，可以是字符串或Path对象
PathLike = Union[str, Path]


@runtime_checkable
class FileOperator(Protocol):
    """不同环境下的文件操作接口。
    
    这个协议定义了所有文件操作实现必须提供的方法。它包括文件读写、
    路径检查和命令执行等基本操作。不同的实现（本地或沙箱）将提供具体的操作逻辑。
    """

    async def read_file(self, path: PathLike) -> str:
        """从文件读取内容。
        
        参数:
            path: 要读取的文件路径
            
        返回:
            str: 文件内容字符串
        """
        ...

    async def write_file(self, path: PathLike, content: str) -> None:
        """将内容写入文件。
        
        参数:
            path: 要写入的文件路径
            content: 要写入的内容
        """
        ...

    async def is_directory(self, path: PathLike) -> bool:
        """检查路径是否指向目录。
        
        参数:
            path: 要检查的路径
            
        返回:
            bool: 如果是目录返回 True，否则返回 False
        """
        ...

    async def exists(self, path: PathLike) -> bool:
        """检查路径是否存在。
        
        参数:
            path: 要检查的路径
            
        返回:
            bool: 如果路径存在返回 True，否则返回 False
        """
        ...

    async def run_command(
        self, cmd: str, timeout: Optional[float] = 120.0
    ) -> Tuple[int, str, str]:
        """执行命令并返回结果。
        
        参数:
            cmd: 要执行的命令字符串
            timeout: 可选的超时时间（秒）
            
        返回:
            Tuple[int, str, str]: 包含 (返回码, 标准输出, 标准错误) 的元组
        """
        ...


class LocalFileOperator(FileOperator):
    """本地文件系统上的文件操作实现。
    
    这个类实现了 FileOperator 协议，提供在本地文件系统上进行操作的方法。
    它直接使用 Python 的 Path 对象和 asyncio 来进行文件操作和命令执行。
    """

    # 文件编码格式，默认为 UTF-8
    encoding: str = "utf-8"

    async def read_file(self, path: PathLike) -> str:
        """从本地文件读取内容。
        
        使用指定编码读取文件并处理可能的异常。
        
        参数:
            path: 要读取的文件路径
            
        返回:
            str: 文件内容字符串
            
        异常:
            ToolError: 如果读取文件过程中发生错误
        """
        try:
            return Path(path).read_text(encoding=self.encoding)
        except Exception as e:
            raise ToolError(f"Failed to read {path}: {str(e)}") from None

    async def write_file(self, path: PathLike, content: str) -> None:
        """将内容写入本地文件。
        
        使用指定编码将内容写入文件并处理可能的异常。
        
        参数:
            path: 要写入的文件路径
            content: 要写入的内容
            
        异常:
            ToolError: 如果写入文件过程中发生错误
        """
        try:
            Path(path).write_text(content, encoding=self.encoding)
        except Exception as e:
            raise ToolError(f"Failed to write to {path}: {str(e)}") from None

    async def is_directory(self, path: PathLike) -> bool:
        """检查路径是否指向本地目录。
        
        参数:
            path: 要检查的路径
            
        返回:
            bool: 如果是目录返回 True，否则返回 False
        """
        return Path(path).is_dir()

    async def exists(self, path: PathLike) -> bool:
        """检查路径在本地是否存在。
        
        参数:
            path: 要检查的路径
            
        返回:
            bool: 如果路径存在返回 True，否则返回 False
        """
        return Path(path).exists()

    async def run_command(
        self, cmd: str, timeout: Optional[float] = 120.0
    ) -> Tuple[int, str, str]:
        """在本地执行命令并捕获输出。
        
        使用 asyncio 异步创建子进程并执行指定的命令，支持超时控制。
        
        参数:
            cmd: 要执行的命令字符串
            timeout: 可选的超时时间（秒）
            
        返回:
            Tuple[int, str, str]: 包含 (返回码, 标准输出, 标准错误) 的元组
            
        异常:
            TimeoutError: 如果命令执行超过指定的超时时间
        """
        # 创建子进程执行命令
        process = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )

        try:
            # 等待命令执行完成，并应用超时
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
            return (
                process.returncode or 0,
                stdout.decode(),
                stderr.decode(),
            )
        except asyncio.TimeoutError as exc:
            # 超时时尝试终止进程
            try:
                process.kill()
            except ProcessLookupError:
                pass
            # 抛出带有有用错误信息的超时异常
            raise TimeoutError(
                f"Command '{cmd}' timed out after {timeout} seconds"
            ) from exc


class SandboxFileOperator(FileOperator):
    """沙箱环境中的文件操作实现。
    
    这个类为在沙箱环境中进行文件操作提供实现。它通过沙箱客户端
    提供的API来进行文件读写和命令执行，保证在隔离的环境中安全操作。
    沙箱环境提供了一层安全隔离，防止不信任的操作影响导致外部系统。
    """

    def __init__(self):
        """初始化沙箱文件操作器。
        
        获取全局沙箱客户端实例作为操作器的接口。
        """
        self.sandbox_client = SANDBOX_CLIENT

    async def _ensure_sandbox_initialized(self):
        """确保沙箱已初始化。
        
        这个内部方法检查沙箱客户端是否已初始化，如果没有则进行初始化。
        在调用任何沙箱操作前都应调用该方法。
        """
        if not self.sandbox_client.sandbox:
            await self.sandbox_client.create(config=SandboxSettings())

    async def read_file(self, path: PathLike) -> str:
        """从沙箱中的文件读取内容。
        
        参数:
            path: 要读取的文件路径
            
        返回:
            str: 文件内容字符串
            
        异常:
            ToolError: 如果读取文件过程中发生错误
        """
        # 确保沙箱已初始化
        await self._ensure_sandbox_initialized()
        try:
            # 使用沙箱客户端读取文件
            return await self.sandbox_client.read_file(str(path))
        except Exception as e:
            # 处理读取错误
            raise ToolError(f"Failed to read {path} in sandbox: {str(e)}") from None

    async def write_file(self, path: PathLike, content: str) -> None:
        """将内容写入沙箱中的文件。
        
        参数:
            path: 要写入的文件路径
            content: 要写入的内容
            
        异常:
            ToolError: 如果写入文件过程中发生错误
        """
        # 确保沙箱已初始化
        await self._ensure_sandbox_initialized()
        try:
            # 使用沙箱客户端写入文件
            await self.sandbox_client.write_file(str(path), content)
        except Exception as e:
            # 处理写入错误
            raise ToolError(f"Failed to write to {path} in sandbox: {str(e)}") from None

    async def is_directory(self, path: PathLike) -> bool:
        """检查路径在沙箱中是否指向目录。
        
        通过在沙箱中运行 shell 命令来检查目录。
        
        参数:
            path: 要检查的路径
            
        返回:
            bool: 如果是目录返回 True，否则返回 False
        """
        # 确保沙箱已初始化
        await self._ensure_sandbox_initialized()
        # 使用 test 命令检查是否为目录
        result = await self.sandbox_client.run_command(
            f"test -d {path} && echo 'true' || echo 'false'"
        )
        return result.strip() == "true"

    async def exists(self, path: PathLike) -> bool:
        """检查路径在沙箱中是否存在。
        
        通过在沙箱中运行 shell 命令来检查路径存在。
        
        参数:
            path: 要检查的路径
            
        返回:
            bool: 如果路径存在返回 True，否则返回 False
        """
        # 确保沙箱已初始化
        await self._ensure_sandbox_initialized()
        # 使用 test 命令检查是否存在
        result = await self.sandbox_client.run_command(
            f"test -e {path} && echo 'true' || echo 'false'"
        )
        return result.strip() == "true"

    async def run_command(
        self, cmd: str, timeout: Optional[float] = 120.0
    ) -> Tuple[int, str, str]:
        """在沙箱环境中执行命令。
        
        在隔离的沙箱环境中执行指定的命令，确保安全性。
        注意：当前沙箱实现不捕获stderr和返回码。
        
        参数:
            cmd: 要执行的命令字符串
            timeout: 可选的超时时间（秒）
            
        返回:
            Tuple[int, str, str]: 包含 (返回码, 标准输出, 标准错误) 的元组
        """
        # 确保沙箱已初始化
        await self._ensure_sandbox_initialized()
        try:
            # 在沙箱中执行命令
            stdout = await self.sandbox_client.run_command(
                cmd, timeout=int(timeout) if timeout else None
            )
            return (
                0,  # 始终返回0，因为当前沙箱实现不提供返回码
                stdout,
                "",  # 当前沙箱实现不捕获标准错误
            )
        except TimeoutError as exc:
            raise TimeoutError(
                f"Command '{cmd}' timed out after {timeout} seconds in sandbox"
            ) from exc
        except Exception as exc:
            return 1, "", f"Error executing command in sandbox: {str(exc)}"
