# -*- coding: utf-8 -*-
"""
统一的异步锁管理器。
提供集中式的锁管理，支持各种类型的并发控制需求。
"""
import asyncio
import logging
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional
from weakref import WeakValueDictionary

logger = logging.getLogger("my_logger")


@dataclass
class LockConfig:
    """锁配置"""

    timeout: Optional[float] = None
    max_waiters: Optional[int] = None
    retry_interval: float = 0.01
    max_retries: int = 100


class LockManager:
    """统一锁管理器"""

    def __init__(self):
        # 异步锁存储
        self._async_locks: Dict[str, asyncio.Lock] = {}
        # 线程锁存储
        self._thread_locks: Dict[str, threading.Lock] = {}
        # 读写锁存储
        self._async_rw_locks: Dict[str, AsyncRWLock] = {}
        # 信号量存储
        self._semaphores: Dict[str, asyncio.Semaphore] = {}
        # 弱引用缓存，自动清理未使用的锁
        self._weak_async_locks: WeakValueDictionary = WeakValueDictionary()
        self._weak_thread_locks: WeakValueDictionary = WeakValueDictionary()

        # 锁统计信息
        self._lock_stats: Dict[str, Dict[str, Any]] = {}
        self._cleanup_task: Optional[asyncio.Task] = None
        self._cleanup_interval = 300  # 5分钟清理一次

    async def start_cleanup_task(self):
        """启动清理任务"""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())

    async def stop_cleanup_task(self):
        """停止清理任务"""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

    async def _periodic_cleanup(self):
        """定期清理未使用的锁"""
        while True:
            try:
                await asyncio.sleep(self._cleanup_interval)
                await self._cleanup_unused_locks()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"锁清理任务错误: {e}")

    async def _cleanup_unused_locks(self):
        """清理未使用的锁"""
        cleaned_count = 0

        # 清理异步锁
        unused_async = [
            name
            for name in self._async_locks.keys()
            if name not in self._weak_async_locks
        ]
        for name in unused_async:
            del self._async_locks[name]
            cleaned_count += 1

        # 清理线程锁
        unused_thread = [
            name
            for name in self._thread_locks.keys()
            if name not in self._weak_thread_locks
        ]
        for name in unused_thread:
            del self._thread_locks[name]
            cleaned_count += 1

        if cleaned_count > 0:
            logger.debug(f"清理了 {cleaned_count} 个未使用的锁")

    # === 异步锁管理 ===

    def get_async_lock(
        self, name: str, config: Optional[LockConfig] = None
    ) -> asyncio.Lock:
        """获取或创建异步锁"""
        if name in self._async_locks:
            lock = self._async_locks[name]
        else:
            lock = asyncio.Lock()
            self._async_locks[name] = lock
            self._weak_async_locks[name] = lock

        self._update_lock_stats(name, "async_lock")
        return lock

    @asynccontextmanager
    async def acquire_async_lock(self, name: str, config: Optional[LockConfig] = None):
        """获取异步锁的上下文管理器"""
        lock = self.get_async_lock(name, config)

        stats = self._lock_stats.setdefault(name, {})

        try:
            if config and config.timeout:
                try:
                    await asyncio.wait_for(lock.acquire(), timeout=config.timeout)
                except asyncio.TimeoutError:
                    stats["timeouts"] = stats.get("timeouts", 0) + 1
                    raise TimeoutError(f"获取锁 '{name}' 超时")
            else:
                await lock.acquire()

            stats["acquisitions"] = stats.get("acquisitions", 0) + 1
            stats["last_acquire_time"] = time.time()

            logger.debug(f"获取异步锁: {name}")
            yield lock

        finally:
            if lock.locked():
                lock.release()
                stats["releases"] = stats.get("releases", 0) + 1
                logger.debug(f"释放异步锁: {name}")

    # === 线程锁管理 ===

    def get_thread_lock(self, name: str) -> threading.Lock:
        """获取或创建线程锁"""
        if name in self._thread_locks:
            lock = self._thread_locks[name]
        else:
            lock = threading.Lock()
            self._thread_locks[name] = lock
            self._weak_thread_locks[name] = lock

        self._update_lock_stats(name, "thread_lock")
        return lock

    @contextmanager
    def acquire_thread_lock(self, name: str):
        """获取线程锁的上下文管理器"""
        lock = self.get_thread_lock(name)

        stats = self._lock_stats.setdefault(name, {})
        start_time = time.time()

        try:
            lock.acquire()
            stats["acquisitions"] = stats.get("acquisitions", 0) + 1
            stats["last_acquire_time"] = time.time()

            logger.debug(f"获取线程锁: {name}")
            yield lock

        finally:
            lock.release()
            stats["releases"] = stats.get("releases", 0) + 1
            duration = time.time() - start_time
            stats["total_hold_time"] = stats.get("total_hold_time", 0) + duration
            logger.debug(f"释放线程锁: {name}")

    # === 读写锁管理 ===

    def get_async_rw_lock(self, name: str) -> "AsyncRWLock":
        """获取或创建异步读写锁"""
        if name in self._async_rw_locks:
            rw_lock = self._async_rw_locks[name]
        else:
            rw_lock = AsyncRWLock()
            self._async_rw_locks[name] = rw_lock

        self._update_lock_stats(name, "async_rw_lock")
        return rw_lock

    @asynccontextmanager
    async def acquire_read_lock(self, name: str, timeout: Optional[float] = None):
        """获取读锁"""
        rw_lock = self.get_async_rw_lock(name)

        stats = self._lock_stats.setdefault(name, {})

        try:
            await rw_lock.acquire_read(timeout)
            stats["read_acquisitions"] = stats.get("read_acquisitions", 0) + 1
            logger.debug(f"获取读锁: {name}")
            yield rw_lock

        finally:
            await rw_lock.release_read()
            stats["read_releases"] = stats.get("read_releases", 0) + 1
            logger.debug(f"释放读锁: {name}")

    @asynccontextmanager
    async def acquire_write_lock(self, name: str, timeout: Optional[float] = None):
        """获取写锁"""
        rw_lock = self.get_async_rw_lock(name)

        stats = self._lock_stats.setdefault(name, {})

        try:
            await rw_lock.acquire_write(timeout)
            stats["write_acquisitions"] = stats.get("write_acquisitions", 0) + 1
            logger.debug(f"获取写锁: {name}")
            yield rw_lock

        finally:
            await rw_lock.release_write()
            stats["write_releases"] = stats.get("write_releases", 0) + 1
            logger.debug(f"释放写锁: {name}")

    # === 信号量管理 ===

    def get_semaphore(self, name: str, value: int = 1) -> asyncio.Semaphore:
        """获取或创建信号量"""
        if name in self._semaphores:
            semaphore = self._semaphores[name]
        else:
            semaphore = asyncio.Semaphore(value)
            self._semaphores[name] = semaphore

        self._update_lock_stats(name, "semaphore")
        return semaphore

    @asynccontextmanager
    async def acquire_semaphore(
        self, name: str, value: int = 1, timeout: Optional[float] = None
    ):
        """获取信号量的上下文管理器"""
        semaphore = self.get_semaphore(name, value)

        stats = self._lock_stats.setdefault(name, {})
        stats["max_concurrent"] = max(stats.get("max_concurrent", 0), value)

        try:
            if timeout:
                await asyncio.wait_for(semaphore.acquire(), timeout=timeout)
            else:
                await semaphore.acquire()

            stats["acquisitions"] = stats.get("acquisitions", 0) + 1
            logger.debug(f"获取信号量: {name} (值: {value})")
            yield semaphore

        finally:
            semaphore.release()
            stats["releases"] = stats.get("releases", 0) + 1
            logger.debug(f"释放信号量: {name}")

    # === 统计和监控 ===

    def _update_lock_stats(self, name: str, lock_type: str):
        """更新锁统计信息"""
        stats = self._lock_stats.setdefault(name, {})
        stats["type"] = lock_type
        stats["created_at"] = stats.get("created_at", time.time())

    def get_lock_stats(self, name: Optional[str] = None) -> Dict[str, Any]:
        """获取锁统计信息"""
        if name:
            return self._lock_stats.get(name, {})
        return dict(self._lock_stats)

    def get_active_locks_count(self) -> Dict[str, int]:
        """获取活跃锁数量"""
        return {
            "async_locks": len(self._async_locks),
            "thread_locks": len(self._thread_locks),
            "async_rw_locks": len(self._async_rw_locks),
            "semaphores": len(self._semaphores),
        }

    async def cleanup_lock(self, name: str) -> bool:
        """清理指定锁"""
        cleaned = False

        if name in self._async_locks:
            del self._async_locks[name]
            cleaned = True

        if name in self._thread_locks:
            del self._thread_locks[name]
            cleaned = True

        if name in self._async_rw_locks:
            del self._async_rw_locks[name]
            cleaned = True

        if name in self._semaphores:
            del self._semaphores[name]
            cleaned = True

        if name in self._lock_stats:
            del self._lock_stats[name]
            cleaned = True

        return cleaned

    async def cleanup_all_locks(self):
        """清理所有锁"""
        self._async_locks.clear()
        self._thread_locks.clear()
        self._async_rw_locks.clear()
        self._semaphores.clear()
        self._lock_stats.clear()
        logger.info("已清理所有锁")


class AsyncRWLock:
    """异步读写锁"""

    def __init__(self):
        self._readers = 0
        self._writers = 0
        self._read_ready = asyncio.Condition()
        self._write_ready = asyncio.Condition()

    async def acquire_read(self, timeout: Optional[float] = None):
        """获取读锁"""
        async with self._write_ready:
            while self._writers > 0:
                try:
                    await asyncio.wait_for(self._write_ready.wait(), timeout=timeout)
                    break
                except asyncio.TimeoutError:
                    raise TimeoutError("获取读锁超时")

        async with self._read_ready:
            self._readers += 1

    async def release_read(self):
        """释放读锁"""
        async with self._read_ready:
            self._readers -= 1
            if self._readers == 0:
                self._read_ready.notify_all()

    async def acquire_write(self, timeout: Optional[float] = None):
        """获取写锁"""
        async with self._write_ready:
            self._writers += 1

        async with self._read_ready:
            while self._readers > 0 or self._writers > 1:
                try:
                    await asyncio.wait_for(self._read_ready.wait(), timeout=timeout)
                    break
                except asyncio.TimeoutError:
                    async with self._write_ready:
                        self._writers -= 1
                    raise TimeoutError("获取写锁超时")

    async def release_write(self):
        """释放写锁"""
        async with self._write_ready:
            self._writers -= 1
            if self._writers == 0:
                self._write_ready.notify_all()

        async with self._read_ready:
            self._read_ready.notify_all()


# 全局锁管理器实例
lock_manager = LockManager()


# 便捷函数
def get_lock_manager() -> LockManager:
    """获取锁管理器实例"""
    return lock_manager


# 装饰器：为函数添加锁保护
def with_async_lock(lock_name: str, config: Optional[LockConfig] = None):
    """异步锁装饰器"""

    def decorator(func: Callable):
        async def wrapper(*args, **kwargs):
            async with lock_manager.acquire_async_lock(lock_name, config):
                return await func(*args, **kwargs)

        return wrapper

    return decorator


def with_thread_lock(lock_name: str):
    """线程锁装饰器"""

    def decorator(func: Callable):
        def wrapper(*args, **kwargs):
            with lock_manager.acquire_thread_lock(lock_name):
                return func(*args, **kwargs)

        return wrapper

    return decorator
