"""
沙箱客户端模块

该模块定义了与沙箱环境交互的客户端接口和实现。它提供了一个统一的API来创建沙箱、
执行命令、管理文件和清理资源。该模块将具体的沙箱实现细节与上层程序隔离，
使得应用程序可以集中于业务逻辑，而不需要关心沙箱的具体实现。

主要组件：
1. SandboxFileOperations - 沙箱文件操作的协议定义
2. BaseSandboxClient - 沙箱客户端的抽象基类
3. LocalSandboxClient - 本地沙箱客户端的具体实现

该模块采用异步编程模式，所有的沙箱操作都是非阻塞的，确保了在执行耗时操作时不会阻堵主线程。
"""

from abc import ABC, abstractmethod
from typing import Dict, Optional, Protocol

from app.config import SandboxSettings
from app.sandbox.core.sandbox import DockerSandbox


class SandboxFileOperations(Protocol):
    """沙箱文件操作协议。
    
    该协议定义了与沙箱环境进行文件交互的标准接口。实现该协议的类可以
    提供文件传输、读取和写入功能，实现了沙箱内外文件系统的交互。
    这种协议方式允许不同的沙箱实现提供一致的文件操作接口。
    """

    async def copy_from(self, container_path: str, local_path: str) -> None:
        """从容器复制文件到本地。

        将沙箱容器内的文件复制到本地文件系统。这个方法允许从沙箱环境
        中提取文件，例如获取运行结果或生成的数据。

        参数:
            container_path: 容器内的文件路径。
            local_path: 本地目标路径。
        """
        ...

    async def copy_to(self, local_path: str, container_path: str) -> None:
        """从本地复制文件到容器。

        将本地文件系统的文件复制到沙箱容器内。这个方法允许向沙箱环境
        提供输入文件，例如代码文件、数据文件或配置文件。

        参数:
            local_path: 本地源文件路径。
            container_path: 容器内的目标路径。
        """
        ...

    async def read_file(self, path: str) -> str:
        """读取容器内文件的内容。

        直接读取并返回沙箱容器内指定文件的内容。这个方法对于获取小型
        文本文件的内容非常有用，而不需要先将文件复制到本地。

        参数:
            path: 容器内的文件路径。

        返回:
            str: 文件内容。
        """
        ...

    async def write_file(self, path: str, content: str) -> None:
        """将内容写入容器内的文件。

        直接将指定的内容写入到沙箱容器内的文件中。这个方法对于创建或
        更新小型文本文件非常有用，而不需要先在本地创建文件再复制到容器。

        参数:
            path: 容器内的文件路径。
            content: 要写入的内容。
        """
        ...


class BaseSandboxClient(ABC):
    """沙箱客户端基类接口。
    
    这个抽象基类定义了与沙箱环境交互的标准接口。所有的沙箱客户端实现必须
    继承这个基类并实现其所有抽象方法。这种设计确保了不同的沙箱实现都提供
    一致的接口，使得上层应用可以不依赖于特定的沙箱实现。
    """

    @abstractmethod
    async def create(
        self,
        config: Optional[SandboxSettings] = None,
        volume_bindings: Optional[Dict[str, str]] = None,
    ) -> None:
        """创建沙箱。
        
        根据指定的配置创建一个新的沙箱环境。如果未提供配置，则使用默认配置。
        使用volume_bindings参数可以将本地目录挂载到沙箱环境中。
        
        参数:
            config: 沙箱配置设置，定义资源限制和其他参数。
            volume_bindings: 卷挂载配置，格式为{'本地路径': '容器路径'}。
        """

    @abstractmethod
    async def run_command(self, command: str, timeout: Optional[int] = None) -> str:
        """在沙箱中执行命令。
        
        在沙箱环境中执行指定的命令，并返回命令的输出。可以设置超时时间
        来限制命令的最长执行时间。
        
        参数:
            command: 要执行的命令字符串。
            timeout: 可选的超时时间(秒)，如果为None则不设置超时。
        
        返回:
            str: 命令执行的输出结果。
        """

    @abstractmethod
    async def copy_from(self, container_path: str, local_path: str) -> None:
        """从容器复制文件到本地。
        
        将沙箱容器内的文件复制到本地文件系统。
        
        参数:
            container_path: 容器内的文件路径。
            local_path: 本地目标路径。
        """

    @abstractmethod
    async def copy_to(self, local_path: str, container_path: str) -> None:
        """从本地复制文件到容器。
        
        将本地文件系统的文件复制到沙箱容器内。
        
        参数:
            local_path: 本地源文件路径。
            container_path: 容器内的目标路径。
        """

    @abstractmethod
    async def read_file(self, path: str) -> str:
        """读取容器内文件的内容。
        
        直接读取并返回沙箱容器内指定文件的内容。
        
        参数:
            path: 容器内的文件路径。
        
        返回:
            str: 文件内容。
        """

    @abstractmethod
    async def write_file(self, path: str, content: str) -> None:
        """将内容写入容器内的文件。
        
        直接将指定的内容写入到沙箱容器内的文件中。
        
        参数:
            path: 容器内的文件路径。
            content: 要写入的内容。
        """

    @abstractmethod
    async def cleanup(self) -> None:
        """清理资源。
        
        清理沙箱实例相关的所有资源，包括内存、磁盘和网络资源。
        在不再需要沙箱时应该调用此方法以释放资源。
        """


class LocalSandboxClient(BaseSandboxClient):
    """本地沙箱客户端实现。
    
    这个类提供了BaseSandboxClient抽象基类的具体实现，使用DockerSandbox作为底层实现。
    它封装了沙箱的创建、命令执行、文件操作和资源清理等功能，为上层应用
    提供了简单统一的接口。
    """

    def __init__(self):
        """初始化本地沙箱客户端。
        
        创建一个新的本地沙箱客户端实例。初始状态下沙箱实例为None，
        需要调用create方法创建实际的沙箱实例。
        """
        self.sandbox: Optional[DockerSandbox] = None  # 沙箱实例引用

    async def create(
        self,
        config: Optional[SandboxSettings] = None,
        volume_bindings: Optional[Dict[str, str]] = None,
    ) -> None:
        """创建沙箱实例。

        根据指定的配置创建一个新的Docker沙箱实例。这个方法创建一个新的DockerSandbox
        对象并调用其create方法来初始化容器。在执行其他操作前必须先调用此方法。

        参数:
            config: 沙箱配置对象，定义了资源限制和其他设置。
            volume_bindings: 卷映射配置，格式为{'本地路径': '容器路径'}。

        抛出:
            RuntimeError: 如果沙箱创建失败。
        """
        self.sandbox = DockerSandbox(config, volume_bindings)
        await self.sandbox.create()

    async def run_command(self, command: str, timeout: Optional[int] = None) -> str:
        """在沙箱中执行命令。

        在沙箱环境中执行指定的命令，并返回该命令的输出结果。此方法将命令委托给
        底层的DockerSandbox实例执行。可以通过timeout参数设置命令的最长执行时间。

        参数:
            command: 要执行的命令字符串。
            timeout: 执行超时时间（秒）。

        返回:
            命令的输出结果字符串。

        抛出:
            RuntimeError: 如果沙箱未初始化（未调用create方法）。
        """
        if not self.sandbox:
            raise RuntimeError("Sandbox not initialized")
        return await self.sandbox.run_command(command, timeout)

    async def copy_from(self, container_path: str, local_path: str) -> None:
        """从沙箱容器复制文件到本地。

        将沙箱容器内指定路径的文件复制到本地文件系统。这个方法将复制操作
        委托给底层的DockerSandbox实例实现。它常用于提取沙箱中生成的输出文件或结果。

        参数:
            container_path: 容器内的文件路径。
            local_path: 本地目标路径。

        抛出:
            RuntimeError: 如果沙箱未初始化（未调用create方法）。
        """
        if not self.sandbox:
            raise RuntimeError("Sandbox not initialized")
        await self.sandbox.copy_from(container_path, local_path)

    async def copy_to(self, local_path: str, container_path: str) -> None:
        """从本地复制文件到沙箱容器。

        将本地文件系统的文件复制到沙箱容器内的指定位置。这个方法将复制操作
        委托给底层的DockerSandbox实例实现。它常用于向沙箱中添加要处理的输入文件。

        参数:
            local_path: 本地源文件路径。
            container_path: 容器内的目标路径。

        抛出:
            RuntimeError: 如果沙箱未初始化（未调用create方法）。
        """
        if not self.sandbox:
            raise RuntimeError("Sandbox not initialized")
        await self.sandbox.copy_to(local_path, container_path)

    async def read_file(self, path: str) -> str:
        """读取沙箱容器内的文件。

        直接读取并返回沙箱容器内指定文件的内容。这个方法将读取操作委托给
        底层的DockerSandbox实例实现。它对于获取容器内生成的文本文件内容非常有用，
        而不需要先将文件复制到本地再读取。

        参数:
            path: 容器内的文件路径。

        返回:
            文件内容字符串。

        抛出:
            RuntimeError: 如果沙箱未初始化（未调用create方法）。
        """
        if not self.sandbox:
            raise RuntimeError("Sandbox not initialized")
        return await self.sandbox.read_file(path)

    async def write_file(self, path: str, content: str) -> None:
        """将内容写入容器内的文件。

        直接将指定的内容写入到沙箱容器内的文件中。这个方法将写入操作委托给
        底层的DockerSandbox实例实现。它对于创建或更新容器内的文本文件非常有用，
        而不需要先在本地创建文件再复制到容器。

        参数:
            path: 容器内的文件路径。
            content: 要写入的文件内容。

        抛出:
            RuntimeError: 如果沙箱未初始化（未调用create方法）。
        """
        if not self.sandbox:
            raise RuntimeError("Sandbox not initialized")
        await self.sandbox.write_file(path, content)

    async def cleanup(self) -> None:
        """清理沙箱资源。
        
        清理与沙箱实例相关的所有资源，包括容器、卷存储和网络资源。这个方法将
        清理操作委托给底层的DockerSandbox实例实现。清理完成后，会重置沙箱实例引用，
        使客户端回到未初始化状态。在不再需要沙箱时应该调用此方法以释放资源。
        """
        # 如果沙箱实例存在，清理其资源
        if self.sandbox:
            # 清理底层沙箱实例的资源
            await self.sandbox.cleanup()
            # 重置引用，允许垃圾回收
            self.sandbox = None


def create_sandbox_client() -> LocalSandboxClient:
    """创建沙箱客户端实例。
    
    这个工厂函数创建并返回一个新的LocalSandboxClient实例。它封装了客户端的
    创建逻辑，如果将来需要更改客户端的具体实现，只需要修改这个函数返回
    不同的客户端实现类即可，而不需要修改使用处的代码。

    返回:
        LocalSandboxClient: 沙箱客户端实例。
    """
    return LocalSandboxClient()


SANDBOX_CLIENT = create_sandbox_client()
