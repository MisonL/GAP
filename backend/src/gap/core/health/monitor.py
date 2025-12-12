# -*- coding: utf-8 -*-
"""
系统健康监控模块。
提供全面的健康检查功能，检查数据库连接、缓存系统、API密钥状态等。
"""
import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine

from gap import config

logger = logging.getLogger("my_logger")


class HealthMonitor:
    """系统健康监控器类"""

    def __init__(self):
        self.last_check_time: Optional[datetime] = None
        self.check_history: List[Dict[str, Any]] = []
        self.status_cache: Dict[str, Any] = {}
        self.cache_ttl = 30  # 缓存状态30秒

    async def check_system_health(
        self,
        app_state=None,
        check_depth: str = "basic",  # 'basic', 'standard', 'comprehensive'
    ) -> Dict[str, Any]:
        """
        执行完整的系统健康检查

        Args:
            app_state: FastAPI 应用状态对象
            check_depth: 检查深度

        Returns:
            包含健康状态的字典
        """
        # 兼容性处理：如果传入的是 FastAPI 应用实例，则获取其 state 属性
        if hasattr(app_state, "state"):
            app_state = app_state.state

        start_time = time.time()

        # 基础信息（使用 timezone-aware 的 UTC 时间戳）
        health_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "healthy",  # 默认健康
            "version": getattr(config, "__version__", "unknown"),
            "checks": {},
            "duration": 0,
            "environment": self._get_environment_info(),
        }

        try:
            # 并行执行各项检查
            if check_depth in ["standard", "comprehensive"]:
                checks = [
                    self._check_database(app_state),
                    self._check_api_keys(app_state),
                    self._check_cache_system(app_state),
                    self._check_external_services(app_state),
                ]
            else:  # basic
                checks = [
                    self._check_database(app_state),
                    self._check_api_keys(app_state),
                ]

            # 等待所有检查完成
            check_results = await asyncio.gather(*checks, return_exceptions=True)

            # 处理检查结果
            for i, result in enumerate(check_results):
                if isinstance(result, Exception):
                    logger.error(f"健康检查项 {i} 失败: {result}")
                    health_data["checks"][f"check_{i}"] = {
                        "status": "error",
                        "error": str(result),
                    }
                elif isinstance(result, dict):
                    health_data["checks"].update(result)

            # 计算整体状态
            health_data["status"] = self._calculate_overall_status(
                health_data["checks"]
            )

        except Exception as e:
            logger.error(f"健康检查执行失败: {e}", exc_info=True)
            health_data["status"] = "error"
            health_data["error"] = str(e)

        finally:
            health_data["duration"] = round(time.time() - start_time, 3)
            # 使用 timezone-aware 的 UTC 时间记录最后检查时间
            self.last_check_time = datetime.now(timezone.utc)

            # 保存历史记录（最多保留20条）
            self.check_history.append(
                {
                    "timestamp": health_data["timestamp"],
                    "status": health_data["status"],
                    "duration": health_data["duration"],
                }
            )
            if len(self.check_history) > 20:
                self.check_history.pop(0)

        # 更新缓存
        self.status_cache = health_data
        return health_data

    async def _check_database(self, app_state) -> Dict[str, Any]:
        """检查数据库连接"""
        check_data = {"database": {"status": "healthy", "checks": {}}}

        try:
            if not app_state or not hasattr(app_state, "db_engine"):
                check_data["database"]["status"] = "error"
                check_data["database"]["error"] = "数据库引擎未初始化"
                return check_data

            engine: AsyncEngine = app_state.db_engine
            start_time = time.time()

            # 基本连接测试
            async with engine.begin() as conn:
                result = await conn.execute(text("SELECT 1"))
                await result.fetchone()

            connection_time = round(time.time() - start_time, 3)
            check_data["database"]["checks"]["connection"] = {
                "status": "healthy",
                "response_time": connection_time,
            }

            # 表结构检查：使用 SQLAlchemy inspect 获取表列表，兼容 SQLite / Postgres 等方言
            try:
                async with engine.begin() as conn:
                    def _get_table_names(sync_conn):
                        inspector = inspect(sync_conn)
                        return inspector.get_table_names()

                    tables = await conn.run_sync(_get_table_names)

                check_data["database"]["checks"]["tables"] = {
                    "status": "healthy",
                    "table_count": len(tables),
                }
            except Exception as table_err:  # pragma: no cover - 具体方言差异在测试环境中难以完全覆盖
                logger.error(f"获取数据库表结构信息失败: {table_err}")
                check_data["database"]["checks"]["tables"] = {
                    "status": "warning",
                    "error": str(table_err),
                }

        except Exception as e:
            logger.error(f"数据库健康检查失败: {e}")
            check_data["database"]["status"] = "error"
            check_data["database"]["error"] = str(e)

        return check_data

    async def _check_api_keys(self, app_state) -> Dict[str, Any]:
        """检查API密钥状态"""
        check_data = {"api_keys": {"status": "healthy", "checks": {}}}

        try:
            if not app_state or not hasattr(app_state, "key_manager"):
                check_data["api_keys"]["status"] = "error"
                check_data["api_keys"]["error"] = "Key管理器未初始化"
                return check_data

            key_manager = app_state.key_manager

            # 检查活跃密钥数量
            active_count = key_manager.get_active_keys_count()
            check_data["api_keys"]["checks"]["active_keys"] = {
                "count": active_count,
                "status": "healthy" if active_count > 0 else "critical",
            }

            # 检查管理员密钥
            admin_key_available = bool(config.ADMIN_API_KEY)
            check_data["api_keys"]["checks"]["admin_key"] = {
                "available": admin_key_available,
                "status": "healthy" if admin_key_available else "warning",
            }

            # 更新整体状态
            if active_count == 0:
                check_data["api_keys"]["status"] = "critical"
            elif not admin_key_available:
                check_data["api_keys"]["status"] = "warning"

        except Exception as e:
            logger.error(f"API密钥健康检查失败: {e}")
            check_data["api_keys"]["status"] = "error"
            check_data["api_keys"]["error"] = str(e)

        return check_data

    async def _check_cache_system(self, app_state) -> Dict[str, Any]:
        """检查缓存系统"""
        check_data = {"cache": {"status": "healthy", "checks": {}}}

        try:
            if not app_state or not hasattr(app_state, "cache_manager"):
                check_data["cache"]["status"] = "warning"
                check_data["cache"]["message"] = "缓存管理器未初始化"
                return check_data

            cache_manager = app_state.cache_manager

            # 检查缓存可用性
            if hasattr(cache_manager, "_test_cache_health"):
                cache_health = await cache_manager._test_cache_health()
                check_data["cache"]["checks"]["connectivity"] = cache_health
            else:
                # 基础检查：尝试获取缓存统计
                try:
                    stats = await cache_manager.get_cache_stats()
                    check_data["cache"]["checks"]["statistics"] = {
                        "status": "healthy",
                        "data": stats,
                    }
                except Exception:
                    check_data["cache"]["status"] = "warning"
                    check_data["cache"]["message"] = "缓存统计信息获取失败"

        except Exception as e:
            logger.error(f"缓存系统健康检查失败: {e}")
            check_data["cache"]["status"] = "error"
            check_data["error"] = str(e)

        return check_data

    async def _check_external_services(self, app_state) -> Dict[str, Any]:
        """检查外部服务连接性"""
        check_data = {"external_services": {"status": "healthy", "checks": {}}}

        try:
            if not app_state or not hasattr(app_state, "http_client"):
                check_data["external_services"]["status"] = "warning"
                check_data["external_services"]["message"] = "HTTP客户端未初始化"
                return check_data

            http_client: httpx.AsyncClient = app_state.http_client

            # 检查Google Gemini API连接性
            start_time = time.time()
            try:
                response = await http_client.get(
                    "https://generativelanguage.googleapis.com", timeout=5  # 5秒超时
                )
                if response.status_code < 500:
                    check_data["external_services"]["checks"]["gemini_api"] = {
                        "status": "healthy",
                        "response_time": round(time.time() - start_time, 3),
                    }
                else:
                    check_data["external_services"]["checks"]["gemini_api"] = {
                        "status": "unhealthy",
                        "http_status": response.status_code,
                    }
                    check_data["external_services"]["status"] = "warning"
            except Exception as e:
                check_data["external_services"]["checks"]["gemini_api"] = {
                    "status": "error",
                    "error": str(e),
                }
                check_data["external_services"]["status"] = "warning"

        except Exception as e:
            logger.error(f"外部服务健康检查失败: {e}")
            check_data["external_services"]["status"] = "error"
            check_data["error"] = str(e)

        return check_data

    def _calculate_overall_status(self, checks: Dict[str, Any]) -> str:
        """根据各项检查结果计算整体状态"""
        statuses = []

        for check_group in checks.values():
            if isinstance(check_group, dict) and "status" in check_group:
                statuses.append(check_group["status"])

        # 优先级：critical > error > warning > healthy
        if any(status == "critical" for status in statuses):
            return "critical"
        elif any(status == "error" for status in statuses):
            return "error"
        elif any(status == "warning" for status in statuses):
            return "warning"
        elif statuses:
            return "healthy"
        else:
            return "unknown"

    def _get_environment_info(self) -> Dict[str, Any]:
        """获取环境信息"""
        return {
            "auth_enabled": getattr(config, "AUTH_ENABLED", True),
            "key_storage_mode": getattr(config, "KEY_STORAGE_MODE", "memory"),
            "context_storage_mode": getattr(config, "CONTEXT_STORAGE_MODE", "memory"),
            "enable_native_caching": getattr(config, "ENABLE_NATIVE_CACHING", False),
            "enable_context_completion": getattr(
                config, "ENABLE_CONTEXT_COMPLETION", True
            ),
        }

    def get_health_history(self, minutes: int = 60) -> List[Dict[str, Any]]:
        """获取指定分钟数内的健康检查历史"""
        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        return [
            record
            for record in self.check_history
            if datetime.fromisoformat(record["timestamp"]).astimezone(timezone.utc)
            > cutoff_time
        ]

    def get_cached_status(self) -> Optional[Dict[str, Any]]:
        """获取缓存的状态信息"""
        if not self.last_check_time:
            return None

        # 检查缓存是否过期（统一使用 timezone-aware 的 UTC 时间）
        now_utc = datetime.now(timezone.utc)
        last_check = (
            self.last_check_time
            if self.last_check_time.tzinfo is not None
            else self.last_check_time.replace(tzinfo=timezone.utc)
        )
        age = (now_utc - last_check).total_seconds()
        if age > self.cache_ttl:
            return None

        return self.status_cache


# 全局健康监控器实例
health_monitor = HealthMonitor()


# 便捷函数
async def get_system_health(
    app_state=None, check_depth: str = "basic"
) -> Dict[str, Any]:
    """获取系统健康状态"""
    return await health_monitor.check_system_health(app_state, check_depth)


def get_health_history(minutes: int = 60) -> List[Dict[str, Any]]:
    """获取健康检查历史"""
    return health_monitor.get_health_history(minutes)
