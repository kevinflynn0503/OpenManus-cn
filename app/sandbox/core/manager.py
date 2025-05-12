"""
沙箱管理器模块

这个模块实现了Docker沙箱的生命周期管理，包括创建、监控和清理。
它是OpenManus项目中安全执行不可信任代码的核心组件，提供了以下功能：

1. 并发沙箱实例的创建和管理
2. 自动清理闲置沙箱以释放资源
3. 资源限制和访问控制机制
4. 异步上下文管理用于安全的沙箱操作

该模块使用异步编程模式，确保高效处理并发的沙箱操作请求。
"""

import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import Dict, Optional, Set

import docker
from docker.errors import APIError, ImageNotFound

from app.config import SandboxSettings
from app.logger import logger
from app.sandbox.core.sandbox import DockerSandbox


class SandboxManager:
    """沙箱管理器类。

    管理多个DockerSandbox实例的生命周期，包括创建、监控和清理。
    提供并发访问控制和沙箱资源的自动清理机制。该类确保沙箱
    实例的高效管理，遵循资源限制，并在闲置时自动释放资源。

    属性:
        max_sandboxes: 允许的最大沙箱数量。
        idle_timeout: 沙箱闲置超时时间（秒）。
        cleanup_interval: 清理检查间隔（秒）。
        _sandboxes: 活动沙箱实例映射字典。
        _last_used: 沙箱最后使用时间记录。
        _locks: 沙箱操作的异步锁字典。
        _global_lock: 全局锁，用于控制并发创建沙箱。
        _active_operations: 当前活动的操作集合。
        _cleanup_task: 清理任务引用。
    """

    def __init__(
        self,
        max_sandboxes: int = 100,
        idle_timeout: int = 3600,
        cleanup_interval: int = 300,
    ):
        """初始化沙箱管理器。

        创建一个新的沙箱管理器实例，设置监控和清理参数，并初始化资源管理和并发控制结构。
        这个方法还会启动一个后台清理任务，用于定期检查和清理闲置的沙箱实例。

        参数:
            max_sandboxes: 最大沙箱数量限制。
            idle_timeout: 闲置超时时间（秒）。
            cleanup_interval: 清理检查间隔（秒）。
        """
        # 设置配置参数
        self.max_sandboxes = max_sandboxes  # 最大沙箱数量限制
        self.idle_timeout = idle_timeout  # 闲置超时时间（秒）
        self.cleanup_interval = cleanup_interval  # 清理检查间隔（秒）

        # 初始化Docker客户端
        self._client = docker.from_env()

        # 资源映射字典
        self._sandboxes: Dict[str, DockerSandbox] = {}  # 沙箱ID到沙箱实例的映射
        self._last_used: Dict[str, float] = {}  # 沙箱ID到最后使用时间的映射

        # 并发控制结构
        self._locks: Dict[str, asyncio.Lock] = {}  # 每个沙箱实例的操作锁
        self._global_lock = asyncio.Lock()  # 全局锁用于共享资源的访问
        self._active_operations: Set[str] = set()  # 当前活动的操作集合

        # 清理任务相关属性
        self._cleanup_task: Optional[asyncio.Task] = None  # 自动清理任务引用
        self._is_shutting_down = False  # 标记管理器是否正在关闭

        # 启动自动清理任务
        self.start_cleanup_task()  # 启动后台清理任务

    async def ensure_image(self, image: str) -> bool:
        """确保 Docker 镜像可用。
        
        检查指定的Docker镜像是否已经存在于系统中。如果不存在，尝试从远程仓库拉取该镜像。
        这个方法是异步的，使用executor在后台线程执行拉取操作，避免阻塞主线程。

        参数:
            image: 镜像名称，格式为 "name:tag" 或类似格式。

        返回:
            bool: 镜像是否可用，True表示可用，False表示不可用或拉取失败。
            
        注意:
            如果镜像不存在且需要拉取，这个操作可能需要一定时间。
        """
        try:
            self._client.images.get(image)
            return True
        except ImageNotFound:
            try:
                logger.info(f"Pulling image {image}...")
                await asyncio.get_event_loop().run_in_executor(
                    None, self._client.images.pull, image
                )
                return True
            except (APIError, Exception) as e:
                logger.error(f"Failed to pull image {image}: {e}")
                return False

    @asynccontextmanager
    async def sandbox_operation(self, sandbox_id: str):
        """沙箱操作的异步上下文管理器。

        提供并发控制和使用时间更新。这个异步上下文管理器确保对同一沙箱实例的
        操作是串行执行的，避免竞争条件和数据不一致性。它还会自动更新沙箱的最后
        使用时间，用于闲置超时检测。

        参数:
            sandbox_id: 沙箱实例ID。

        抛出:
            KeyError: 如果沙箱实例不存在。
            
        用法:
            ```python
            async with sandbox_manager.sandbox_operation(sandbox_id) as sandbox:
                # 执行沙箱操作，例如执行命令或上传文件
                await sandbox.execute_command('echo "hello"')
            ```
        """
        if sandbox_id not in self._locks:
            self._locks[sandbox_id] = asyncio.Lock()

        async with self._locks[sandbox_id]:
            if sandbox_id not in self._sandboxes:
                raise KeyError(f"Sandbox {sandbox_id} not found")

            self._active_operations.add(sandbox_id)
            try:
                self._last_used[sandbox_id] = asyncio.get_event_loop().time()
                yield self._sandboxes[sandbox_id]
            finally:
                self._active_operations.remove(sandbox_id)

    async def create_sandbox(
        self,
        config: Optional[SandboxSettings] = None,
        volume_bindings: Optional[Dict[str, str]] = None,
    ) -> str:
        """创建一个新的沙箱实例。

        这个方法创建一个新的沙箱实例，分配一个唯一的UUID作为沙箱ID，并初始化相关的
        资源跟踪和并发控制结构。创建过程会检查最大沙箱数量限制，确保需要的Docker镜像可用，
        并向Docker引擎创建一个隔离的容器环境。

        参数:
            config: 沙箱配置对象，定义资源限制和其他设置。如果为None，将使用默认配置。
            volume_bindings: 卷映射配置，格式为{主机路径: 容器路径}。

        返回:
            str: 新创建的沙箱实例ID（UUID格式）。

        抛出:
            RuntimeError: 如果达到最大沙箱数量限制、镜像不可用或创建失败。
        """
        async with self._global_lock:
            if len(self._sandboxes) >= self.max_sandboxes:
                raise RuntimeError(
                    f"Maximum number of sandboxes ({self.max_sandboxes}) reached"
                )

            config = config or SandboxSettings()
            if not await self.ensure_image(config.image):
                raise RuntimeError(f"Failed to ensure Docker image: {config.image}")

            sandbox_id = str(uuid.uuid4())
            try:
                sandbox = DockerSandbox(config, volume_bindings)
                await sandbox.create()

                self._sandboxes[sandbox_id] = sandbox
                self._last_used[sandbox_id] = asyncio.get_event_loop().time()
                self._locks[sandbox_id] = asyncio.Lock()

                logger.info(f"Created sandbox {sandbox_id}")
                return sandbox_id

            except Exception as e:
                logger.error(f"Failed to create sandbox: {e}")
                if sandbox_id in self._sandboxes:
                    await self.delete_sandbox(sandbox_id)
                raise RuntimeError(f"Failed to create sandbox: {e}")

    async def get_sandbox(self, sandbox_id: str) -> DockerSandbox:
        """获取沙箱实例并更新使用时间。

        根据沙箱ID获取已存在的沙箱实例。这个方法使用sandbox_operation上下文管理器
        来确保线程安全的访问并自动更新沙箱的最后使用时间。

        参数:
            sandbox_id: 沙箱实例ID。

        返回:
            DockerSandbox: 沙箱实例对象。

        抛出:
            KeyError: 如果沙箱不存在。
        """
        async with self.sandbox_operation(sandbox_id) as sandbox:
            return sandbox

    def start_cleanup_task(self) -> None:
        """启动自动清理任务。
        
        创建一个异步任务，定期检查和清理闲置的沙箱实例。这个方法会启动一个后台循环，
        每隔cleanup_interval秒调用_cleanup_idle_sandboxes方法来清理闲置的沙箱。如果清理过程
        中发生异常，会将其记录到日志中并继续循环。
        
        这个方法使用asyncio.create_task创建一个异步任务，使清理操作可以在后台运行而不影响主线程。
        """

        # 定义清理循环异步函数
        async def cleanup_loop():
            # 在管理器未关闭时持续循环
            while not self._is_shutting_down:
                try:
                    # 执行闲置沙箱清理
                    await self._cleanup_idle_sandboxes()
                except Exception as e:
                    # 记录清理过程中的错误
                    logger.error(f"Error in cleanup loop: {e}")
                # 等待指定的间隔时间
                await asyncio.sleep(self.cleanup_interval)

        # 创建并启动清理任务
        self._cleanup_task = asyncio.create_task(cleanup_loop())

    async def _cleanup_idle_sandboxes(self) -> None:
        """清理闲置的沙箱实例。
        
        这个内部方法负责检测和清理长时间未使用的沙箱实例。它首先获取当前时间，
        然后选出那些自上次使用以来已经超过idle_timeout时间的沙箱。这些沙箱失败
        当前没有正在进行的操作，即它们不在_active_operations集合中。
        
        该方法使用全局锁进行保护，确保在检查过程中沙箱集合不会被修改。
        但实际的删除操作是在锁外进行的，以避免长时间占用锁。
        """
        # 获取当前时间
        current_time = asyncio.get_event_loop().time()
        # 初始化要清理的沙箱ID列表
        to_cleanup = []

        # 使用全局锁保护沙箱集合的共享访问
        async with self._global_lock:
            # 遍历所有沙箱的最后使用时间
            for sandbox_id, last_used in self._last_used.items():
                # 检查沙箱是否闲置超时，且当前没有正在进行的操作
                if (
                    sandbox_id not in self._active_operations  # 没有正在进行的操作
                    and current_time - last_used > self.idle_timeout  # 超过闲置超时时间
                ):
                    # 添加到要清理的列表中
                    to_cleanup.append(sandbox_id)

        for sandbox_id in to_cleanup:
            try:
                await self.delete_sandbox(sandbox_id)
            except Exception as e:
                logger.error(f"Error cleaning up sandbox {sandbox_id}: {e}")

    async def cleanup(self) -> None:
        """清理所有沙箱资源。
        
        这个方法在管理器关闭时调用，负责清理所有的沙箱实例和相关资源。它执行以下操作：
        1. 标记管理器正在关闭以停止自动清理循环
        2. 取消并等待后台清理任务完成
        3. 并发清理所有活动的沙箱实例
        4. 清理所有内部数据结构
        
        该方法采用并发策略来加速清理过程，但设置了超时机制以避免无限期等待。
        """
        # 记录开始清理的日志
        logger.info("Starting manager cleanup...")
        # 标记管理器正在关闭，用于停止清理循环
        self._is_shutting_down = True

        # 取消后台清理任务
        if self._cleanup_task:
            # 发送取消信号
            self._cleanup_task.cancel()
            try:
                # 等待任务取消完成，最多等待1秒
                await asyncio.wait_for(self._cleanup_task, timeout=1.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                # 忽略取消和超时异常
                pass

        # 获取所有需要清理的沙箱ID
        async with self._global_lock:
            # 复制所有沙箱ID的列表，避免在清理过程中修改字典
            sandbox_ids = list(self._sandboxes.keys())

        # 并发清理所有沙箱
        cleanup_tasks = []
        for sandbox_id in sandbox_ids:
            # 为每个沙箱创建异步清理任务
            task = asyncio.create_task(self._safe_delete_sandbox(sandbox_id))
            cleanup_tasks.append(task)

        if cleanup_tasks:
            # 等待所有清理任务完成，设置超时以避免无限期等待
            try:
                # 等待所有任务，最多30秒
                await asyncio.wait(cleanup_tasks, timeout=30.0)
            except asyncio.TimeoutError:
                # 如果超时，记录错误并继续
                logger.error("Sandbox cleanup timed out")

        # 清理所有内部数据结构的引用
        self._sandboxes.clear()  # 清空沙箱实例映射
        self._last_used.clear()  # 清空最后使用时间记录
        self._locks.clear()      # 清空锁映射
        self._active_operations.clear()  # 清空活动操作集合

        logger.info("Manager cleanup completed")

    async def _safe_delete_sandbox(self, sandbox_id: str) -> None:
        """安全地删除单个沙箱实例。

        这个内部方法提供了安全删除沙箱的机制，包含以下特性：
        1. 等待并检查沙箱上的活动操作是否完成
        2. 在清理沙箱实例资源失败时进行错误处理
        3. 清理管理器中的相关数据结构
        
        参数:
            sandbox_id: 要删除的沙箱ID。
        
        安全性考虑:
            - 对有活动操作的沙箱进行等待，避免在操作进行中删除沙箱
            - 错误容忍机制确保即使在删除过程中出现异常也不会影响整体清理
        """
        try:
            if sandbox_id in self._active_operations:
                logger.warning(
                    f"Sandbox {sandbox_id} has active operations, waiting for completion"
                )
                for _ in range(10):  # Wait at most 10 times
                    await asyncio.sleep(0.5)
                    if sandbox_id not in self._active_operations:
                        break
                else:
                    logger.warning(
                        f"Timeout waiting for sandbox {sandbox_id} operations to complete"
                    )

            # Get reference to sandbox object
            sandbox = self._sandboxes.get(sandbox_id)
            if sandbox:
                await sandbox.cleanup()

                # Remove sandbox record from manager
                async with self._global_lock:
                    self._sandboxes.pop(sandbox_id, None)
                    self._last_used.pop(sandbox_id, None)
                    self._locks.pop(sandbox_id, None)
                    logger.info(f"Deleted sandbox {sandbox_id}")
        except Exception as e:
            logger.error(f"Error during cleanup of sandbox {sandbox_id}: {e}")

    async def delete_sandbox(self, sandbox_id: str) -> None:
        """删除指定的沙箱实例。

        这个公开方法用于删除特定的沙箱实例。它是_safe_delete_sandbox方法的外部包装，
        添加了额外的错误处理和检查。如果沙箱不存在，方法将直接返回而不会抛出异常。

        参数:
            sandbox_id: 要删除的沙箱ID。
        """
        # 如果沙箱不存在，直接返回而不执行任何操作
        if sandbox_id not in self._sandboxes:
            return

        try:
            await self._safe_delete_sandbox(sandbox_id)
        except Exception as e:
            logger.error(f"Failed to delete sandbox {sandbox_id}: {e}")

    async def __aenter__(self) -> "SandboxManager":
        """异步上下文管理器入口方法。
        
        允许使用async with语法创建和管理SandboxManager实例的生命周期。
        例如：async with SandboxManager() as manager: ...
        
        返回:
            SandboxManager: 当前的沙箱管理器实例。
        """
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """异步上下文管理器退出方法。
        
        在异步上下文结束时自动调用，执行沙箱管理器的清理操作。
        这确保了即使在异常情况下，所有的沙箱资源也能被正确释放。
        
        参数:
            exc_type: 异常类型（如果有）。
            exc_val: 异常值（如果有）。
            exc_tb: 异常跟踪信息（如果有）。
        """
        await self.cleanup()

    def get_stats(self) -> Dict:
        """获取沙箱管理器的统计信息。
        
        这个方法返回当前沙箱管理器的运行状态和统计信息，包括活动的沙箱数量、
        当前正在进行的操作数量、配置参数等。这些信息可以用于监控和调试沙箱系统。

        返回:
            Dict: 包含以下字段的统计信息字典：
                - total_sandboxes: 当前活动的沙箱总数
                - active_operations: 正在进行的操作数量
                - max_sandboxes: 最大沙箱数量限制
                - idle_timeout: 闲置超时时间（秒）
                - cleanup_interval: 清理间隔（秒）
                - is_shutting_down: 管理器是否正在关闭
        """
        return {
            "total_sandboxes": len(self._sandboxes),
            "active_operations": len(self._active_operations),
            "max_sandboxes": self.max_sandboxes,
            "idle_timeout": self.idle_timeout,
            "cleanup_interval": self.cleanup_interval,
            "is_shutting_down": self._is_shutting_down,
        }
