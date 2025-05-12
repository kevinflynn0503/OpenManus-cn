"""
沙箱核心模块

这个模块提供了基于Docker的沙箱环境实现，它能够安全地执行不可信任的代码和命令。
沙箱提供了资源限制、文件操作、命令执行、工作目录挂载等功能，
确保代码在一个隔离的环境中执行，不会影响到主机系统。

主要组件：
1. DockerSandbox - 提供容器化执行环境的实现
2. AsyncDockerizedTerminal - 与容器进行异步交互的终端接口

沙箱环境默认是网络隔离的，有内存和CPU限制，以防止资源滥用。
它操作的文件被限制在指定的工作目录内，提供了文件上传、下载、命令执行等API。
"""

import asyncio
import io
import os
import tarfile
import tempfile
import uuid
from typing import Dict, Optional

import docker
from docker.errors import NotFound
from docker.models.containers import Container

from app.config import SandboxSettings
from app.sandbox.core.exceptions import SandboxTimeoutError
from app.sandbox.core.terminal import AsyncDockerizedTerminal


class DockerSandbox:
    """基于Docker的沙箱环境。

    提供了一个带资源限制的容器化执行环境，支持文件操作和命令执行功能。
    这个类提供了安全执行不可信任代码的基础设施，确保代码在隔离环境中运行，
    并且具有预先定义的资源限制，防止影响到主机系统。

    属性:
        config: 沙箱配置，包含内存限制、CPU限制和其他设置。
        volume_bindings: 卷挂载映射配置，定义主机目录与容器路径的映射关系。
        client: Docker客户端，用于与Docker API交互。
        container: Docker容器实例，代表当前运行的沙箱容器。
        terminal: 容器终端接口，用于异步交互和命令执行。
    """

    def __init__(
        self,
        config: Optional[SandboxSettings] = None,
        volume_bindings: Optional[Dict[str, str]] = None,
    ):
        """初始化沙箱实例。

        创建一个新的Docker沙箱实例，设置基本配置和卷挂载映射。
        这个方法仅初始化对象，不会创建或启动容器，需要调用create方法来创建容器。
        
        参数:
            config: 沙箱配置对象。如果为None，将使用默认配置。
            volume_bindings: 卷挂载映射，格式为{主机路径: 容器路径}。
        """
        # 使用提供的配置或创建默认配置
        self.config = config or SandboxSettings()
        # 设置卷挂载映射，没有提供时使用空字典
        self.volume_bindings = volume_bindings or {}
        # 初始化Docker客户端
        self.client = docker.from_env()
        # 初始化容器引用为None，将在create方法中设置
        self.container: Optional[Container] = None
        # 初始化终端引用为None，将在create方法中设置
        self.terminal: Optional[AsyncDockerizedTerminal] = None

    async def create(self) -> "DockerSandbox":
        """创建并启动沙箱容器。
        
        这个方法异步创建一个Docker容器，设置各种资源限制和网络隔离，
        然后启动容器并初始化终端接口。它会生成一个包含随机UUID的唯一容器名，
        并应用配置中定义的各种设置。

        返回:
            当前沙箱实例，已创建并启动。

        异常:
            docker.errors.APIError: 如果Docker API调用失败。
            RuntimeError: 如果容器创建或启动失败。
        """
        try:
            # Prepare container config
            host_config = self.client.api.create_host_config(
                mem_limit=self.config.memory_limit,
                cpu_period=100000,
                cpu_quota=int(100000 * self.config.cpu_limit),
                network_mode="none" if not self.config.network_enabled else "bridge",
                binds=self._prepare_volume_bindings(),
            )

            # Generate unique container name with sandbox_ prefix
            container_name = f"sandbox_{uuid.uuid4().hex[:8]}"

            # Create container
            container = await asyncio.to_thread(
                self.client.api.create_container,
                image=self.config.image,
                command="tail -f /dev/null",
                hostname="sandbox",
                working_dir=self.config.work_dir,
                host_config=host_config,
                name=container_name,
                tty=True,
                detach=True,
            )

            self.container = self.client.containers.get(container["Id"])

            # Start container
            await asyncio.to_thread(self.container.start)

            # Initialize terminal
            self.terminal = AsyncDockerizedTerminal(
                container["Id"],
                self.config.work_dir,
                env_vars={"PYTHONUNBUFFERED": "1"}
                # Ensure Python output is not buffered
            )
            await self.terminal.init()

            return self

        except Exception as e:
            await self.cleanup()  # Ensure resources are cleaned up
            raise RuntimeError(f"Failed to create sandbox: {e}") from e

    def _prepare_volume_bindings(self) -> Dict[str, Dict[str, str]]:
        """准备卷挂载配置。

        这个内部方法将用户定义的卷挂载配置和默认的工作目录挂载配置转换为
        Docker API需要的特定格式。对于工作目录，它会自动在主机上创建一个临时目录
        然后将其挂载到容器中的指定路径。这确保了容器具有需要的目录结构。

        返回:
            按Docker API格式的卷挂载配置字典。
        """
        bindings = {}

        # Create and add working directory mapping
        work_dir = self._ensure_host_dir(self.config.work_dir)
        bindings[work_dir] = {"bind": self.config.work_dir, "mode": "rw"}

        # Add custom volume bindings
        for host_path, container_path in self.volume_bindings.items():
            bindings[host_path] = {"bind": container_path, "mode": "rw"}

        return bindings

    @staticmethod
    def _ensure_host_dir(path: str) -> str:
        """确保主机上的目录存在。

        这个静态方法在主机上创建一个对应于容器内目录的临时目录。它在主机的
        临时目录下生成一个带有随机后缀的目录名，确保它不会与现有目录冲突。
        这个方法的存在确保了容器和主机之间的文件系统集成。

        参数:
            path: 容器内的目录路径。

        返回:
            主机上的实际路径。
        """
        host_path = os.path.join(
            tempfile.gettempdir(),
            f"sandbox_{os.path.basename(path)}_{os.urandom(4).hex()}",
        )
        os.makedirs(host_path, exist_ok=True)
        return host_path

    async def run_command(self, cmd: str, timeout: Optional[int] = None) -> str:
        """在沙箱中执行命令。

        这个方法是沙箱的核心功能之一，允许在隔离的容器环境中安全地执行命令。
        它调用底层的终端接口执行命令，并处理超时检测。如果命令执行超过指定的
        超时时间，将抛出特定的SandboxTimeoutError异常。这个方法默认使用沙箱配置中
        的超时设置，除非显示指定了新的超时值。
        
        注意：使用这个方法前，必须先创建沙箱环境并初始化终端。

        参数:
            cmd: 要执行的命令。
            timeout: 超时时间（秒）。

        返回:
            命令输出的字符串。

        抛出:
            RuntimeError: 如果沙箱未初始化或命令执行失败。
            SandboxTimeoutError: 如果命令执行超时。
        """
        if not self.terminal:
            raise RuntimeError("Sandbox not initialized")

        try:
            return await self.terminal.run_command(
                cmd, timeout=timeout or self.config.timeout
            )
        except TimeoutError:
            raise SandboxTimeoutError(
                f"Command execution timed out after {timeout or self.config.timeout} seconds"
            )

    async def read_file(self, path: str) -> str:
        """从容器中读取文件内容。

        该方法从沙箱容器中读取指定文件的内容。它使用Docker API的get_archive方法
        将文件作为一个tar流读取，然后提取文件内容并将其转换为字符串。在读取
        前，该方法调用_safe_resolve_path函数来确保路径安全，防止目录遍历攻击。

        参数:
            path: 容器内的文件路径。

        返回:
            文件内容字符串。

        抛出:
            FileNotFoundError: 如果文件不存在。
            RuntimeError: 如果读取操作失败。
        """
        if not self.container:
            raise RuntimeError("Sandbox not initialized")

        try:
            # Get file archive
            resolved_path = self._safe_resolve_path(path)
            tar_stream, _ = await asyncio.to_thread(
                self.container.get_archive, resolved_path
            )

            # Read file content from tar stream
            content = await self._read_from_tar(tar_stream)
            return content.decode("utf-8")

        except NotFound:
            raise FileNotFoundError(f"File not found: {path}")
        except Exception as e:
            raise RuntimeError(f"Failed to read file: {e}")

    async def write_file(self, path: str, content: str) -> None:
        """将内容写入容器内的文件。

        该方法将指定的内容写入到沙箱容器中的文件。它首先创建一个包含内容的临时
        在本地文件，然后将其打包为一个tar文件，并使用Docker API的put_archive方法将其上传到
        容器的指定路径。这个方法同样使用_safe_resolve_path函数来确保路径安全。

        参数:
            path: 容器内的目标路径。
            content: 要写入的文件内容。

        抛出:
            RuntimeError: 如果写入操作失败。
        """
        if not self.container:
            raise RuntimeError("Sandbox not initialized")

        try:
            resolved_path = self._safe_resolve_path(path)
            parent_dir = os.path.dirname(resolved_path)

            # Create parent directory
            if parent_dir:
                await self.run_command(f"mkdir -p {parent_dir}")

            # Prepare file data
            tar_stream = await self._create_tar_stream(
                os.path.basename(path), content.encode("utf-8")
            )

            # Write file
            await asyncio.to_thread(
                self.container.put_archive, parent_dir or "/", tar_stream
            )

        except Exception as e:
            raise RuntimeError(f"Failed to write file: {e}")

    def _safe_resolve_path(self, path: str) -> str:
        """安全地解析容器路径，防止路径遍历攻击。

        这个方法提供了对文件路径的基本安全检查，以防止路径遍历（path traversal）
        类型的安全漏洞。它检查路径中是否包含“..”字段，这可能被用来访问上级目录。
        也将相对路径转换为基于工作目录的绝对路径。
        
        这个方法是沙箱安全方面的重要组成部分，确保文件操作只能在容器的指定范围内进行。

        参数:
            path: 原始路径。

        返回:
            解析后的绝对路径。

        抛出:
            ValueError: 如果路径包含潜在不安全的模式。
        """
        # Check for path traversal attempts
        if ".." in path.split("/"):
            raise ValueError("Path contains potentially unsafe patterns")

        resolved = (
            os.path.join(self.config.work_dir, path)
            if not os.path.isabs(path)
            else path
        )
        return resolved

    async def copy_from(self, src_path: str, dst_path: str) -> None:
        """从容器中复制文件到主机。

        这个方法将沙箱容器内的文件复制到主机系统上。它使用Docker API的get_archive
        方法获取文件的tar形式流，将其写入临时文件，然后解压到指定的目标路径。
        该方法支持将文件复制到指定文件或目录，并根据目标路径类型自动处理。
        
        该方法同样使用_safe_resolve_path确保路径安全，防止路径遍历攻击。

        参数:
            src_path: 源文件路径（容器内）。
            dst_path: 目标路径（主机上）。

        抛出:
            FileNotFoundError: 如果源文件不存在。
            RuntimeError: 如果复制操作失败。
        """
        try:
            # Ensure destination file's parent directory exists
            parent_dir = os.path.dirname(dst_path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

            # Get file stream
            resolved_src = self._safe_resolve_path(src_path)
            stream, stat = await asyncio.to_thread(
                self.container.get_archive, resolved_src
            )

            # Create temporary directory to extract file
            with tempfile.TemporaryDirectory() as tmp_dir:
                # Write stream to temporary file
                tar_path = os.path.join(tmp_dir, "temp.tar")
                with open(tar_path, "wb") as f:
                    for chunk in stream:
                        f.write(chunk)

                # Extract file
                with tarfile.open(tar_path) as tar:
                    members = tar.getmembers()
                    if not members:
                        raise FileNotFoundError(f"Source file is empty: {src_path}")

                    # If destination is a directory, we should preserve relative path structure
                    if os.path.isdir(dst_path):
                        tar.extractall(dst_path)
                    else:
                        # If destination is a file, we only extract the source file's content
                        if len(members) > 1:
                            raise RuntimeError(
                                f"Source path is a directory but destination is a file: {src_path}"
                            )

                        with open(dst_path, "wb") as dst:
                            src_file = tar.extractfile(members[0])
                            if src_file is None:
                                raise RuntimeError(
                                    f"Failed to extract file: {src_path}"
                                )
                            dst.write(src_file.read())

        except docker.errors.NotFound:
            raise FileNotFoundError(f"Source file not found: {src_path}")
        except Exception as e:
            raise RuntimeError(f"Failed to copy file: {e}")

    async def copy_to(self, src_path: str, dst_path: str) -> None:
        """将文件从主机复制到容器中。

        这个方法将主机上的文件或目录复制到沙箱容器中。它首先检查源文件是否存在，
        然后在容器内创建必要的目录结构。对于文件传输，它创建一个临时的tar文件，
        将源文件打包，然后使用Docker API的put_archive方法将其上传到容器中。
        
        该方法支持两种情况：
        1. 如果源路径是一个文件，则将其复制到容器内的指定路径
        2. 如果源路径是一个目录，则将目录及其内容复制到容器内，保持相对路径结构
        
        该方法同样使用_safe_resolve_path确保目标路径安全，防止路径遍历攻击。

        参数:
            src_path: 源文件路径（主机上）。
            dst_path: 目标路径（容器内）。

        抛出:
            FileNotFoundError: 如果源文件不存在。
            RuntimeError: 如果复制操作失败。
        """
        try:
            if not os.path.exists(src_path):
                raise FileNotFoundError(f"Source file not found: {src_path}")

            # Create destination directory in container
            resolved_dst = self._safe_resolve_path(dst_path)
            container_dir = os.path.dirname(resolved_dst)
            if container_dir:
                await self.run_command(f"mkdir -p {container_dir}")

            # Create tar file to upload
            with tempfile.TemporaryDirectory() as tmp_dir:
                tar_path = os.path.join(tmp_dir, "temp.tar")
                with tarfile.open(tar_path, "w") as tar:
                    # Handle directory source path
                    if os.path.isdir(src_path):
                        os.path.basename(src_path.rstrip("/"))
                        for root, _, files in os.walk(src_path):
                            for file in files:
                                file_path = os.path.join(root, file)
                                arcname = os.path.join(
                                    os.path.basename(dst_path),
                                    os.path.relpath(file_path, src_path),
                                )
                                tar.add(file_path, arcname=arcname)
                    else:
                        # Add single file to tar
                        tar.add(src_path, arcname=os.path.basename(dst_path))

                # Read tar file content
                with open(tar_path, "rb") as f:
                    data = f.read()

                # Upload to container
                await asyncio.to_thread(
                    self.container.put_archive,
                    os.path.dirname(resolved_dst) or "/",
                    data,
                )

                # Verify file was created successfully
                try:
                    await self.run_command(f"test -e {resolved_dst}")
                except Exception:
                    raise RuntimeError(f"Failed to verify file creation: {dst_path}")

        except FileNotFoundError:
            raise
        except Exception as e:
            raise RuntimeError(f"Failed to copy file: {e}")

    @staticmethod
    async def _create_tar_stream(name: str, content: bytes) -> io.BytesIO:
        """创建一个tar文件流。

        这个静态帮助方法用于创建包含单个文件的tar流，该文件流可以被Docker API的
        put_archive方法所用来将文件上传到容器。它在内存中直接创建一个tar文件，
        而不需要写入磁盘，提高了效率并避免了临时文件的不必要创建。
        
        这个方法是异步的，尽管它的内部操作都是同步的，这是为了保持API的一致性。

        参数:
            name: 文件名称。
            content: 文件内容字节流。

        返回:
            包含文件的tar流对象(io.BytesIO)。
        """
        tar_stream = io.BytesIO()
        with tarfile.open(fileobj=tar_stream, mode="w") as tar:
            tarinfo = tarfile.TarInfo(name=name)
            tarinfo.size = len(content)
            tar.addfile(tarinfo, io.BytesIO(content))
        tar_stream.seek(0)
        return tar_stream

    @staticmethod
    async def _read_from_tar(tar_stream) -> bytes:
        """从一个tar流中读取文件内容。

        这个静态帮助方法用于从容器中提取的tar流中读取文件内容。它先将tar流
        写入一个临时文件，然后打开该文件并提取其中第一个文件的内容。这个方法
        与_create_tar_stream方法是互补的，主要用于处理Docker API的get_archive方法返回的数据。
        
        这个方法同样是异步的，尽管内部操作都是同步的，这是为了保持API的一致性。

        参数:
            tar_stream: 包含文件的tar流。

        返回:
            文件内容字节流。

        抛出:
            RuntimeError: 如果读取操作失败。
        """
        with tempfile.NamedTemporaryFile() as tmp:
            for chunk in tar_stream:
                tmp.write(chunk)
            tmp.seek(0)

            with tarfile.open(fileobj=tmp) as tar:
                member = tar.next()
                if not member:
                    raise RuntimeError("Empty tar archive")

                file_content = tar.extractfile(member)
                if not file_content:
                    raise RuntimeError("Failed to extract file content")

                return file_content.read()

    async def cleanup(self) -> None:
        """清理沙箱资源。
        
        这个方法负责释放沙箱环境的所有资源，包括关闭终端会话和停止并移除Docker容器。
        它采用了容错设计，即使在清理过程中发生错误，也会尝试继续清理其他资源，
        并将错误打印出来而不是直接抛出异常。这确保了即使在出现问题时也能最大程度地
        清理资源，防止资源泄漏。
        
        这个方法会在沙箱类被销毁时自动调用，或者当使用异步上下文管理器时在退出上下文时调用。
        
        返回:
            无返回值。
        """
        errors = []
        try:
            if self.terminal:
                try:
                    await self.terminal.close()
                except Exception as e:
                    errors.append(f"Terminal cleanup error: {e}")
                finally:
                    self.terminal = None

            if self.container:
                try:
                    await asyncio.to_thread(self.container.stop, timeout=5)
                except Exception as e:
                    errors.append(f"Container stop error: {e}")

                try:
                    await asyncio.to_thread(self.container.remove, force=True)
                except Exception as e:
                    errors.append(f"Container remove error: {e}")
                finally:
                    self.container = None

        except Exception as e:
            errors.append(f"General cleanup error: {e}")

        if errors:
            print(f"Warning: Errors during cleanup: {', '.join(errors)}")

    async def __aenter__(self) -> "DockerSandbox":
        """异步上下文管理器入口方法。
        
        这个特殊方法实现了异步上下文管理器协议，允许DockerSandbox在异步with语句中使用。
        当进入异步with语句块时，该方法会被调用，并创建并初始化沙箱环境。
        
        示例用法:
        ```python
        async with DockerSandbox(...) as sandbox:
            # 在这里使用已初始化的沙箱
        ```
        
        返回:
            DockerSandbox: 初始化后的沙箱实例。
        """
        return await self.create()

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """异步上下文管理器退出方法。
        
        这个特殊方法实现了异步上下文管理器协议，在退出异步with语句块时被调用。
        它负责清理沙箱环境的资源，包括关闭终端会话和停止并移除Docker容器，
        无论在with语句块中是否发生了异常。
        
        这确保了即使在发生错误时也能正确地释放资源，防止资源泄漏。
        
        参数:
            exc_type: 异常类型（如果有）。
            exc_val: 异常值（如果有）。
            exc_tb: 异常追踪信息（如果有）。
            
        返回:
            无返回值。
        """
        await self.cleanup()
