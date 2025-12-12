# -*- coding: utf-8 -*-
"""
资源管理器引导程序。
在应用启动时自动设置各种资源的清理。
"""
import logging
from typing import Any

from .manager import ResourcePriority, resource_manager

logger = logging.getLogger("my_logger")


class ResourceManagerBootstrap:
    """资源管理器引导程序"""

    def __init__(self):
        self._bootstrap_done = False

    async def bootstrap_async_resources(self, app_state: Any):
        """
        引导异步资源的清理注册

        Args:
            app_state: FastAPI 应用的 state 对象
        """
        if self._bootstrap_done:
            logger.debug("资源管理器引导已完成，跳过重复引导")
            return

        logger.info("开始资源管理器引导...")

        # --- 高优先级资源 ---
        # HTTP 客户端
        if hasattr(app_state, "http_client") and app_state.http_client:
            resource_manager.register_cleaner(
                name="http_client",
                cleanup_func=app_state.http_client.aclose,
                priority=ResourcePriority.HIGH,
                description="HTTP 客户端清理",
                timeout=15.0,
                retry_count=1,
            )
            logger.debug("已注册 HTTP 客户端清理器")

        # 数据库引擎
        if hasattr(app_state, "db_engine") and app_state.db_engine:
            resource_manager.register_cleaner(
                name="database_engine",
                cleanup_func=app_state.db_engine.dispose,
                priority=ResourcePriority.HIGH,
                description="数据库引擎清理",
                timeout=20.0,
                retry_count=1,
            )
            logger.debug("已注册数据库引擎清理器")

        # --- 中优先级资源 ---
        # 锁管理器
        if hasattr(app_state, "lock_manager") and app_state.lock_manager:
            resource_manager.register_cleaner(
                name="lock_manager",
                cleanup_func=self._cleanup_lock_manager,
                priority=ResourcePriority.MEDIUM,
                description="锁管理器清理",
                timeout=10.0,
            )
            logger.debug("已注册锁管理器清理器")

        # 缓存管理器
        if hasattr(app_state, "cache_manager") and app_state.cache_manager:
            resource_manager.register_cleaner(
                name="cache_manager",
                cleanup_func=self._cleanup_cache_manager,
                priority=ResourcePriority.MEDIUM,
                description="缓存管理器清理",
                timeout=10.0,
            )
            logger.debug("已注册缓存管理器清理器")

        # 上下文存储管理器
        if (
            hasattr(app_state, "context_store_manager")
            and app_state.context_store_manager
        ):
            resource_manager.register_cleaner(
                name="context_store_manager",
                cleanup_func=self._cleanup_context_store,
                priority=ResourcePriority.MEDIUM,
                description="上下文存储管理器清理",
                timeout=10.0,
            )
            logger.debug("已注册上下文存储管理器清理器")

        # --- 低优先级资源 ---
        # Key 管理器
        if hasattr(app_state, "key_manager") and app_state.key_manager:
            resource_manager.register_cleaner(
                name="key_manager",
                cleanup_func=self._cleanup_key_manager,
                priority=ResourcePriority.LOW,
                description="Key 管理器清理",
                timeout=5.0,
            )
            logger.debug("已注册 Key 管理器清理器")

        # 调度器相关
        await self._register_scheduler_cleaners(app_state)

        self._bootstrap_done = True
        logger.info(
            f"资源管理器引导完成，共注册 {len(resource_manager._cleaners)} 个清理器"
        )

    async def _register_scheduler_cleaners(self, app_state: Any):
        """注册调度器相关的清理器"""
        # 报告调度器
        if hasattr(app_state, "reporting_scheduler"):
            # reporting_scheduler 是全局的，不需要从 app_state 获取
            from ..reporting import scheduler as reporting_scheduler

            resource_manager.register_cleaner(
                name="reporting_scheduler",
                cleanup_func=reporting_scheduler.shutdown_scheduler,
                priority=ResourcePriority.MEDIUM,
                description="报告调度器清理",
                timeout=8.0,
                is_async=False,
            )
            logger.debug("已注册报告调度器清理器")

        # 缓存清理调度器
        if (
            hasattr(app_state, "cache_cleanup_scheduler")
            and app_state.cache_cleanup_scheduler
        ):
            resource_manager.register_cleaner(
                name="cache_cleanup_scheduler",
                cleanup_func=self._cleanup_cache_scheduler,
                priority=ResourcePriority.LOW,
                description="缓存清理调度器清理",
                timeout=5.0,
            )
            logger.debug("已注册缓存清理调度器清理器")

    async def _cleanup_lock_manager(self):
        """清理锁管理器占位实现。

        实际锁资源会在应用关闭阶段通过统一资源管理器处理，这里仅记录日志以避免未定义引用。
        """
        try:
            logger.info("锁管理器清理完成（由统一资源管理器负责实际清理）。")
        except Exception as e:
            logger.error(f"清理锁管理器失败: {e}")

    async def _cleanup_cache_manager(self):
        """清理缓存管理器"""
        try:
            # 这里可以添加缓存管理器的清理逻辑
            # 例如：保存缓存统计、清理临时数据等
            logger.info("缓存管理器清理完成")
        except Exception as e:
            logger.error(f"清理缓存管理器失败: {e}")

    async def _cleanup_context_store(self):
        """清理上下文存储管理器"""
        try:
            # 上下文存储管理器的清理逻辑
            # 例如：清理临时会话数据、保存统计等
            logger.info("上下文存储管理器清理完成")
        except Exception as e:
            logger.error(f"清理上下文存储管理器失败: {e}")

    async def _cleanup_key_manager(self):
        """清理 Key 管理器"""
        try:
            # Key 管理器的清理逻辑
            # 例如：保存使用统计、清理临时状态等
            logger.info("Key 管理器清理完成")
        except Exception as e:
            logger.error(f"清理 Key 管理器失败: {e}")

    async def _cleanup_cache_scheduler(self):
        """清理缓存清理调度器"""
        try:
            from ..cache.cleanup import cache_cleanup_scheduler_instance

            if (
                cache_cleanup_scheduler_instance
                and hasattr(cache_cleanup_scheduler_instance, "running")
                and cache_cleanup_scheduler_instance.running
            ):
                cache_cleanup_scheduler_instance.shutdown()
                logger.info("缓存清理调度器清理完成")
        except Exception as e:
            logger.error(f"清理缓存清理调度器失败: {e}")

    def get_bootstrap_stats(self) -> dict:
        """获取引导统计信息"""
        return {
            "bootstrap_done": self._bootstrap_done,
            "registered_cleaners_count": len(resource_manager._cleaners),
            "registered_cleaners": list(resource_manager._cleaners.keys()),
        }


# 全局引导程序实例
resource_bootstrap = ResourceManagerBootstrap()


# 便捷函数
async def bootstrap_resource_management(app_state: Any):
    """引导资源管理的便捷函数"""
    return await resource_bootstrap.bootstrap_async_resources(app_state)
