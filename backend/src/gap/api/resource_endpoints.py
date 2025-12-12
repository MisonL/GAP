# -*- coding: utf-8 -*-
"""
资源管理 API 端点。
提供资源状态监控和管理接口。
"""
import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status

from ..core.dependencies import get_auth_data
from ..core.resource import resource_manager

logger = logging.getLogger("my_logger")

# 创建路由器
router = APIRouter()


@router.get("/status", response_model=Dict[str, Any])
async def get_resource_status(auth_data: Dict[str, Any] = Depends(get_auth_data)):
    """
    获取资源管理状态

    需要认证访问。

    Returns:
        Dict[str, Any]: 资源状态信息
    """
    try:
        # 检查管理员权限，兼容顶层 is_admin 和 config['is_admin'] 两种结构
        is_admin = bool(
            auth_data.get("is_admin")
            or auth_data.get("config", {}).get("is_admin", False)
        )
        if not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="需要管理员权限才能访问资源状态",
            )

        # 获取资源状态
        stats = resource_manager.get_cleanup_stats()

        # 获取详细的清理器信息
        cleaners_info = {}
        for name, cleaner in resource_manager._cleaners.items():
            cleaners_info[name] = {
                "description": cleaner.description,
                "priority": cleaner.priority.name,
                "is_async": cleaner.is_async,
                "timeout": cleaner.timeout,
                "retry_count": cleaner.retry_count,
                "cleaned": name in resource_manager._cleaned_resources,
                "failed": name in resource_manager._failed_cleanups,
                "error": (
                    str(resource_manager._failed_cleanups.get(name))
                    if name in resource_manager._failed_cleanups
                    else None
                ),
            }

        result = {
            "resource_manager": {
                "is_shutting_down": stats["is_shutting_down"],
                "total_cleaners": stats["total_cleaners"],
                "successful_cleanups": stats["successful_cleanups"],
                "failed_cleanups": stats["failed_cleanups"],
                "total_duration": stats.get("total_duration", 0),
                "registered_cleaners": stats["registered_cleaners"],
                "cleaned_resources": stats["cleaned_resources"],
                "failed_resources": stats["failed_resources"],
            },
            "cleaners": cleaners_info,
            "has_failures": resource_manager.has_failed_cleanups(),
        }

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取资源状态API错误: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取资源状态时发生内部错误",
        )


@router.post("/cleanup", response_model=Dict[str, Any])
async def trigger_resource_cleanup(auth_data: Dict[str, Any] = Depends(get_auth_data)):
    """
    手动触发资源清理

    需要管理员权限。

    Returns:
        Dict[str, Any]: 清理结果
    """
    try:
        # 检查管理员权限，兼容顶层 is_admin 和 config['is_admin'] 两种结构
        is_admin = bool(
            auth_data.get("is_admin")
            or auth_data.get("config", {}).get("is_admin", False)
        )
        if not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="需要管理员权限才能触发资源清理",
            )

        # 如果已经在关闭中，返回状态
        if resource_manager._is_shutting_down:
            return {
                "status": "already_in_progress",
                "message": "资源清理已在进行中",
                "stats": resource_manager.get_cleanup_stats(),
            }

        # 触发清理
        logger.info("手动触发资源清理")
        await resource_manager.cleanup_all_resources()

        # 返回清理结果
        stats = resource_manager.get_cleanup_stats()

        return {
            "status": "completed",
            "message": "资源清理完成",
            "stats": stats,
            "has_failures": resource_manager.has_failed_cleanups(),
            "failed_cleanups": (
                resource_manager.get_failed_cleanups()
                if resource_manager.has_failed_cleanups()
                else {}
            ),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"手动资源清理API错误: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="手动资源清理时发生内部错误",
        )


@router.get("/cleaners", response_model=Dict[str, Any])
async def list_resource_cleaners(auth_data: Dict[str, Any] = Depends(get_auth_data)):
    """
    列出所有注册的资源清理器

    需要认证访问。

    Returns:
        Dict[str, Any]: 清理器列表信息
    """
    try:
        # 检查管理员权限，兼容顶层 is_admin 和 config['is_admin'] 两种结构
        is_admin = bool(
            auth_data.get("is_admin")
            or auth_data.get("config", {}).get("is_admin", False)
        )
        if not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="需要管理员权限才能列出资源清理器",
            )

        # 按优先级分组清理器
        grouped_cleaners = {"HIGH": [], "MEDIUM": [], "LOW": []}

        for name, cleaner in resource_manager._cleaners.items():
            cleaner_info = {
                "name": name,
                "description": cleaner.description,
                "priority": cleaner.priority.name,
                "is_async": cleaner.is_async,
                "timeout": cleaner.timeout,
                "retry_count": cleaner.retry_count,
                "status": (
                    "cleaned"
                    if name in resource_manager._cleaned_resources
                    else (
                        "failed"
                        if name in resource_manager._failed_cleanups
                        else "pending"
                    )
                ),
                "error": (
                    str(resource_manager._failed_cleanups.get(name))
                    if name in resource_manager._failed_cleanups
                    else None
                ),
            }
            grouped_cleaners[cleaner.priority.name].append(cleaner_info)

        result = {
            "total_cleaners": len(resource_manager._cleaners),
            "grouped_cleaners": grouped_cleaners,
            "cleaned_count": len(resource_manager._cleaned_resources),
            "failed_count": len(resource_manager._failed_cleanups),
            "pending_count": len(resource_manager._cleaners)
            - len(resource_manager._cleaned_resources)
            - len(resource_manager._failed_cleanups),
        }

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"列出资源清理器API错误: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="列出资源清理器时发生内部错误",
        )


@router.post("/register", response_model=Dict[str, Any])
async def register_custom_cleaner(
    name: str,
    cleanup_func_name: str,
    priority: str = "MEDIUM",
    description: str = "",
    timeout: float = 30.0,
    retry_count: int = 0,
    auth_data: Dict[str, Any] = Depends(get_auth_data),
):
    """
    注册自定义资源清理器（仅用于测试和调试）

    需要管理员权限。

    Args:
        name: 清理器名称
        cleanup_func_name: 清理函数名称（必须是全局可访问的函数）
        priority: 优先级 (HIGH/MEDIUM/LOW)
        description: 描述
        timeout: 超时时间
        retry_count: 重试次数

    Returns:
        Dict[str, Any]: 注册结果
    """
    try:
        # 检查管理员权限，兼容顶层 is_admin 和 config['is_admin'] 两种结构
        is_admin = bool(
            auth_data.get("is_admin")
            or auth_data.get("config", {}).get("is_admin", False)
        )
        if not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="需要管理员权限才能注册自定义清理器",
            )

        # 获取优先级枚举
        from ..core.resource.manager import ResourcePriority

        try:
            priority_enum = ResourcePriority[priority.upper()]
        except KeyError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"无效的优先级: {priority}，必须是 HIGH、MEDIUM 或 LOW",
            )

        # 查找清理函数（仅允许特定的安全函数）
        safe_functions = {
            "noop_cleanup": lambda: None,
            "log_cleanup": lambda: logger.info(f"自定义清理器 {name} 执行完成"),
        }

        if cleanup_func_name not in safe_functions:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"不允许的清理函数: {cleanup_func_name}，仅允许: {list(safe_functions.keys())}",
            )

        cleanup_func = safe_functions[cleanup_func_name]

        # 注册清理器
        resource_manager.register_cleaner(
            name=name,
            cleanup_func=cleanup_func,
            priority=priority_enum,
            description=description or f"自定义清理器: {name}",
            is_async=False,
            timeout=timeout,
            retry_count=retry_count,
        )

        logger.info(f"已注册自定义清理器: {name}")

        return {
            "status": "success",
            "message": f"成功注册自定义清理器: {name}",
            "cleaner_info": {
                "name": name,
                "description": description,
                "priority": priority,
                "timeout": timeout,
                "retry_count": retry_count,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"注册自定义清理器API错误: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="注册自定义清理器时发生内部错误",
        )
