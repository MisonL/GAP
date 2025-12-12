# -*- coding: utf-8 -*-
"""
统一资源清理管理器。
提供集中式的资源清理机制，确保应用在关闭时和运行时都能正确清理各种资源。
"""
import asyncio
import logging
import signal
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger("my_logger")


class ResourcePriority(Enum):
    """资源清理优先级"""

    HIGH = auto()  # 高优先级：关键资源（数据库连接、HTTP客户端等）
    MEDIUM = auto()  # 中优先级：重要资源（缓存、锁管理器等）
    LOW = auto()  # 低优先级：一般资源（临时数据、统计信息等）


@dataclass
class ResourceCleaner:
    """资源清理器定义"""

    name: str
    cleanup_func: Callable
    priority: ResourcePriority = ResourcePriority.MEDIUM
    description: str = ""
    is_async: bool = True
    timeout: float = 30.0  # 清理超时时间（秒）
    retry_count: int = 0  # 失败重试次数
    args: tuple = field(default_factory=tuple)
    kwargs: dict = field(default_factory=dict)


class ResourceManager:
    """统一资源管理器"""

    def __init__(self):
        self._cleaners: Dict[str, ResourceCleaner] = {}
        self._cleaned_resources: Set[str] = set()
        self._failed_cleanups: Dict[str, Exception] = {}
        self._is_shutting_down = False
        self._shutdown_event = asyncio.Event()

        # 注册信号处理器
        self._register_signal_handlers()

        # 清理统计
        self._cleanup_stats = {
            "total_cleaners": 0,
            "successful_cleanups": 0,
            "failed_cleanups": 0,
            "cleanup_start_time": None,
            "cleanup_end_time": None,
        }

    def _register_signal_handlers(self):
        """注册系统信号处理器"""
        try:
            # 注册 SIGINT (Ctrl+C) 和 SIGTERM 信号
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)
            logger.debug("已注册系统信号处理器")
        except Exception as e:
            logger.warning(f"注册信号处理器失败: {e}")

    def _signal_handler(self, signum, frame):
        """信号处理器"""
        logger.info(f"接收到信号 {signum}，开始优雅关闭...")
        if not self._is_shutting_down:
            # 在新线程中执行清理，避免阻塞信号处理
            cleanup_thread = threading.Thread(
                target=self._sync_shutdown_wrapper, daemon=True
            )
            cleanup_thread.start()

    def _sync_shutdown_wrapper(self):
        """同步关闭包装器"""
        try:
            # 获取或创建事件循环
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            # 运行清理
            loop.run_until_complete(self.cleanup_all_resources())
        except Exception as e:
            logger.error(f"同步关闭包装器执行失败: {e}", exc_info=True)

    def register_cleaner(
        self,
        name: str,
        cleanup_func: Callable,
        priority: ResourcePriority = ResourcePriority.MEDIUM,
        description: str = "",
        is_async: bool = True,
        timeout: float = 30.0,
        retry_count: int = 0,
        args: tuple = (),
        kwargs: dict = None,
    ):
        """
        注册资源清理器

        Args:
            name: 清理器名称，必须唯一
            cleanup_func: 清理函数
            priority: 清理优先级
            description: 清理器描述
            is_async: 是否为异步函数
            timeout: 清理超时时间
            retry_count: 失败重试次数
            args: 清理函数的位置参数
            kwargs: 清理函数的关键字参数
        """
        if name in self._cleaners:
            logger.warning(f"清理器 '{name}' 已存在，将被覆盖")

        cleaner = ResourceCleaner(
            name=name,
            cleanup_func=cleanup_func,
            priority=priority,
            description=description,
            is_async=is_async,
            timeout=timeout,
            retry_count=retry_count,
            args=args,
            kwargs=kwargs or {},
        )

        self._cleaners[name] = cleaner
        logger.debug(f"已注册资源清理器: {name} (优先级: {priority.name})")

    def unregister_cleaner(self, name: str) -> bool:
        """取消注册清理器"""
        if name in self._cleaners:
            del self._cleaners[name]
            logger.debug(f"已取消注册清理器: {name}")
            return True
        return False

    async def cleanup_resource(self, name: str) -> bool:
        """
        清理单个资源

        Args:
            name: 清理器名称

        Returns:
            bool: 清理是否成功
        """
        if name not in self._cleaners:
            logger.warning(f"清理器 '{name}' 不存在")
            return False

        if name in self._cleaned_resources:
            logger.debug(f"资源 '{name}' 已清理过")
            return True

        cleaner = self._cleaners[name]

        for attempt in range(cleaner.retry_count + 1):
            try:
                if attempt > 0:
                    logger.info(f"重试清理资源 '{name}' (第 {attempt + 1} 次)")

                start_time = time.time()

                # 执行清理
                if cleaner.is_async:
                    await asyncio.wait_for(
                        cleaner.cleanup_func(*cleaner.args, **cleaner.kwargs),
                        timeout=cleaner.timeout,
                    )
                else:
                    # 在线程池中执行同步函数
                    await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: cleaner.cleanup_func(*cleaner.args, **cleaner.kwargs),
                    )

                duration = time.time() - start_time

                self._cleaned_resources.add(name)
                self._cleanup_stats["successful_cleanups"] += 1

                logger.info(f"资源 '{name}' 清理成功 (耗时: {duration:.3f}s)")
                return True

            except asyncio.TimeoutError:
                logger.error(f"清理资源 '{name}' 超时 ({cleaner.timeout}s)")
            except Exception as e:
                logger.error(f"清理资源 '{name}' 失败: {e}", exc_info=True)

                if attempt >= cleaner.retry_count:
                    self._failed_cleanups[name] = e
                    self._cleanup_stats["failed_cleanups"] += 1

        return False

    async def cleanup_all_resources(self):
        """清理所有注册的资源"""
        if self._is_shutting_down:
            logger.info("资源清理已在进行中...")
            return

        self._is_shutting_down = True
        self._cleanup_stats["cleanup_start_time"] = time.time()
        self._cleanup_stats["total_cleaners"] = len(self._cleaners)

        logger.info("开始统一资源清理...")

        # 按优先级排序清理器
        sorted_cleaners = sorted(
            self._cleaners.items(),
            key=lambda x: (x[1].priority.value, x[0]),  # 按名称排序作为第二条件
        )

        # 并行清理同优先级的资源
        current_priority = None
        current_batch = []

        for name, cleaner in sorted_cleaners:
            if name in self._cleaned_resources:
                continue

            # 新的优先级，先清理当前批次
            if current_priority is not None and cleaner.priority != current_priority:
                await self._cleanup_batch(current_batch)
                current_batch = []

            current_priority = cleaner.priority
            current_batch.append(name)

        # 清理最后一批
        if current_batch:
            await self._cleanup_batch(current_batch)

        self._cleanup_stats["cleanup_end_time"] = time.time()
        total_duration = (
            self._cleanup_stats["cleanup_end_time"]
            - self._cleanup_stats["cleanup_start_time"]
        )

        # 输出清理统计
        logger.info("=" * 60)
        logger.info("资源清理完成:")
        logger.info(f"  总清理器: {self._cleanup_stats['total_cleaners']}")
        logger.info(f"  成功清理: {self._cleanup_stats['successful_cleanups']}")
        logger.info(f"  失败清理: {self._cleanup_stats['failed_cleanups']}")
        logger.info(f"  总耗时: {total_duration:.3f}s")

        if self._failed_cleanups:
            logger.warning("失败的清理:")
            for name, error in self._failed_cleanups.items():
                logger.warning(f"  {name}: {error}")

        logger.info("=" * 60)

        # 设置关闭事件
        self._shutdown_event.set()

    async def _cleanup_batch(self, batch: List[str]):
        """并行清理一批资源"""
        if not batch:
            return

        logger.info(f"清理批次: {batch}")

        # 创建并行任务
        tasks = []
        for name in batch:
            task = asyncio.create_task(self.cleanup_resource(name))
            tasks.append(task)

        # 等待所有任务完成
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def wait_for_shutdown(self, timeout: Optional[float] = None):
        """等待关闭完成"""
        try:
            await asyncio.wait_for(self._shutdown_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(f"等待关闭超时 ({timeout}s)")

    def get_cleanup_stats(self) -> Dict[str, Any]:
        """获取清理统计信息"""
        stats = dict(self._cleanup_stats)

        # 计算总耗时
        if stats["cleanup_start_time"] and stats["cleanup_end_time"]:
            stats["total_duration"] = (
                stats["cleanup_end_time"] - stats["cleanup_start_time"]
            )

        # 添加当前状态
        stats["is_shutting_down"] = self._is_shutting_down
        stats["registered_cleaners"] = list(self._cleaners.keys())
        stats["cleaned_resources"] = list(self._cleaned_resources)
        stats["failed_resources"] = list(self._failed_cleanups.keys())

        return stats

    def has_failed_cleanups(self) -> bool:
        """是否有失败的清理"""
        return bool(self._failed_cleanups)

    def get_failed_cleanups(self) -> Dict[str, Exception]:
        """获取失败的清理信息"""
        return dict(self._failed_cleanups)


# 全局资源管理器实例
resource_manager = ResourceManager()


# 便捷函数
def register_resource_cleaner(
    name: str,
    cleanup_func: Callable,
    priority: ResourcePriority = ResourcePriority.MEDIUM,
    description: str = "",
    is_async: bool = True,
    timeout: float = 30.0,
    retry_count: int = 0,
    args: tuple = (),
    kwargs: dict = None,
):
    """注册资源清理器的便捷函数"""
    return resource_manager.register_cleaner(
        name=name,
        cleanup_func=cleanup_func,
        priority=priority,
        description=description,
        is_async=is_async,
        timeout=timeout,
        retry_count=retry_count,
        args=args,
        kwargs=kwargs,
    )


async def cleanup_all_resources():
    """清理所有资源的便捷函数"""
    return await resource_manager.cleanup_all_resources()


# 装饰器
def auto_cleanup(
    name: Optional[str] = None,
    priority: ResourcePriority = ResourcePriority.MEDIUM,
    description: str = "",
    timeout: float = 30.0,
):
    """
    自动清理装饰器

    用于装饰类，在类实例化时自动注册清理方法
    """

    def decorator(cls):
        original_init = cls.__init__

        def __init__(self, *args, **kwargs):
            original_init(self, *args, **kwargs)

            # 检查是否有清理方法
            if hasattr(self, "cleanup"):
                cleanup_name = name or f"{cls.__name__}.{id(self)}"
                resource_manager.register_cleaner(
                    name=cleanup_name,
                    cleanup_func=self.cleanup,
                    priority=priority,
                    description=description or f"{cls.__name__} 清理方法",
                    is_async=asyncio.iscoroutinefunction(self.cleanup),
                    timeout=timeout,
                )

        cls.__init__ = __init__
        return cls

    return decorator


# 上下文管理器
@asynccontextmanager
async def managed_resource(
    name: str,
    cleanup_func: Callable,
    priority: ResourcePriority = ResourcePriority.MEDIUM,
    description: str = "",
    timeout: float = 30.0,
):
    """
    管理资源上下文管理器

    自动注册清理器，并在退出上下文时清理资源
    """
    resource_manager.register_cleaner(
        name=name,
        cleanup_func=cleanup_func,
        priority=priority,
        description=description,
        timeout=timeout,
    )

    try:
        yield
    finally:
        await resource_manager.cleanup_resource(name)
