# -*- coding: utf-8 -*-
"""
配置管理接口
提供查看和修改系统配置参数的API端点
"""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from gap import config as app_config
from gap.api.middleware import verify_proxy_key
from gap.core.database.utils import IS_MEMORY_DB
from gap.core.dependencies import verify_admin_token

logger = logging.getLogger("my_logger")

router = APIRouter(prefix="/api/v1/config", tags=["配置管理"])


def _get_gemini_api_keys_count() -> int:
    """安全地计算 GEMINI_API_KEYS 的数量。

    支持以下几种形态：
    - 未设置或为 None: 返回 0
    - 字符串: 按逗号分割并统计非空条目
    - 可迭代对象: 尝试使用 len() 获取长度
    """
    raw = getattr(app_config, "GEMINI_API_KEYS", None)
    if not raw:
        return 0

    # 环境变量模式: 逗号分隔的字符串
    if isinstance(raw, str):
        return len([item.strip() for item in raw.split(",") if item.strip()])

    # 其它可迭代对象 (向后兼容)
    try:
        return len(raw)  # type: ignore[arg-type]
    except TypeError:
        return 0


class ConfigResponse(BaseModel):
    """配置信息响应模型"""

    storage_mode: str
    key_storage_mode: str
    context_storage_mode: str
    enable_native_caching: bool
    max_requests_per_minute: int
    max_requests_per_day_per_ip: int
    web_ui_passwords_count: int
    gemini_api_keys_count: int
    is_memory_mode: bool
    current_configs: Dict[str, Any]
    is_admin: bool
    user_key_info: Optional[Dict[str, Any]] = None


class ConfigUpdateRequest(BaseModel):
    """配置更新请求模型"""

    max_requests_per_minute: Optional[int] = None
    max_requests_per_day_per_ip: Optional[int] = None
    enable_native_caching: Optional[bool] = None


@router.get("/info", response_model=ConfigResponse)
async def get_config_info(
    auth_data: Dict[str, Any] = Depends(verify_proxy_key), request: Request = None
):
    """
    获取当前系统配置信息
    管理员可以看到所有信息，普通用户只能看到全局配置和自己的key信息
    """
    try:
        # 检查是否为管理员
        current_key = auth_data.get("key", "")
        is_admin = False
        user_key_info = None

        # 检查是否是管理员密钥
        if hasattr(request.app.state, "key_manager"):
            key_manager = request.app.state.key_manager
            is_admin = key_manager.is_admin_key(current_key)

            # 如果是普通用户，获取该key的相关信息
            if not is_admin and not IS_MEMORY_DB:
                # 数据库模式下，获取该key的详细信息
                from sqlalchemy.future import select

                from gap.core.database.models import ApiKey

                AsyncSessionFactory = request.app.state.AsyncSessionFactory
                async with AsyncSessionFactory() as session:
                    stmt = select(ApiKey).where(ApiKey.key_string == current_key)
                    result = await session.execute(stmt)
                    key_obj = result.scalar_one_or_none()
                    if key_obj:
                        user_key_info = {
                            "key_string": key_obj.key_string[:8] + "...",
                            "is_active": key_obj.is_active,
                            "created_at": str(key_obj.created_at),
                            "usage_count": key_obj.usage_count or 0,
                        }

        # 构建响应
        if is_admin:
            # 管理员可以看到所有信息
            config_info = ConfigResponse(
                storage_mode="memory" if IS_MEMORY_DB else "database",
                key_storage_mode=getattr(app_config, "KEY_STORAGE_MODE", "memory"),
                context_storage_mode=getattr(
                    app_config, "CONTEXT_STORAGE_MODE", "memory"
                ),
                enable_native_caching=getattr(
                    app_config, "ENABLE_NATIVE_CACHING", False
                ),
                max_requests_per_minute=getattr(
                    app_config, "MAX_REQUESTS_PER_MINUTE", 60
                ),
                max_requests_per_day_per_ip=getattr(
                    app_config, "MAX_REQUESTS_PER_DAY_PER_IP", 600
                ),
                web_ui_passwords_count=len(getattr(app_config, "WEB_UI_PASSWORDS", [])),
                gemini_api_keys_count=_get_gemini_api_keys_count(),
                is_memory_mode=IS_MEMORY_DB,
                current_configs={
                    "max_requests_per_minute": getattr(
                        app_config, "MAX_REQUESTS_PER_MINUTE", 60
                    ),
                    "max_requests_per_day_per_ip": getattr(
                        app_config, "MAX_REQUESTS_PER_DAY_PER_IP", 600
                    ),
                    "enable_native_caching": getattr(
                        app_config, "ENABLE_NATIVE_CACHING", False
                    ),
                    "key_storage_mode": getattr(
                        app_config, "KEY_STORAGE_MODE", "memory"
                    ),
                    "context_storage_mode": getattr(
                        app_config, "CONTEXT_STORAGE_MODE", "memory"
                    ),
                },
                is_admin=True,
                user_key_info=None,
            )
        else:
            # 普通用户只能看到全局配置和自己的key信息
            config_info = ConfigResponse(
                storage_mode="memory" if IS_MEMORY_DB else "database",
                key_storage_mode=getattr(app_config, "KEY_STORAGE_MODE", "memory"),
                context_storage_mode=getattr(
                    app_config, "CONTEXT_STORAGE_MODE", "memory"
                ),
                enable_native_caching=getattr(
                    app_config, "ENABLE_NATIVE_CACHING", False
                ),
                max_requests_per_minute=getattr(
                    app_config, "MAX_REQUESTS_PER_MINUTE", 60
                ),
                max_requests_per_day_per_ip=getattr(
                    app_config, "MAX_REQUESTS_PER_DAY_PER_IP", 600
                ),
                web_ui_passwords_count=0,  # 普通用户看不到密码数量
                gemini_api_keys_count=0,  # 普通用户看不到密钥总数
                is_memory_mode=IS_MEMORY_DB,
                current_configs={
                    "max_requests_per_minute": getattr(
                        app_config, "MAX_REQUESTS_PER_MINUTE", 60
                    ),
                    "max_requests_per_day_per_ip": getattr(
                        app_config, "MAX_REQUESTS_PER_DAY_PER_IP", 600
                    ),
                    "enable_native_caching": getattr(
                        app_config, "ENABLE_NATIVE_CACHING", False
                    ),
                    "key_storage_mode": getattr(
                        app_config, "KEY_STORAGE_MODE", "memory"
                    ),
                    "context_storage_mode": getattr(
                        app_config, "CONTEXT_STORAGE_MODE", "memory"
                    ),
                },
                is_admin=False,
                user_key_info=user_key_info,
            )

        logger.info(
            f"配置信息查询成功，用户类型: {'管理员' if is_admin else '普通用户'}"
        )
        return config_info

    except Exception as e:
        logger.error(f"获取配置信息失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取配置信息失败"
        )


@router.post("/update", dependencies=[Depends(verify_admin_token)])
async def update_config(update_request: ConfigUpdateRequest, request: Request):
    """
    更新配置参数（仅内存模式下有效）
    需要管理员令牌认证
    """
    if not IS_MEMORY_DB:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="数据库模式下不支持通过API修改配置，请通过环境变量或配置文件修改",
        )

    try:
        updated_fields = []

        # 更新配置
        if update_request.max_requests_per_minute is not None:
            app_config.MAX_REQUESTS_PER_MINUTE = update_request.max_requests_per_minute
            updated_fields.append("max_requests_per_minute")

        if update_request.max_requests_per_day_per_ip is not None:
            app_config.MAX_REQUESTS_PER_DAY_PER_IP = (
                update_request.max_requests_per_day_per_ip
            )
            updated_fields.append("max_requests_per_day_per_ip")

        if update_request.enable_native_caching is not None:
            app_config.ENABLE_NATIVE_CACHING = update_request.enable_native_caching
            updated_fields.append("enable_native_caching")

        # 更新速率限制器（如果存在）
        if hasattr(request.app.state, "rate_limiter"):
            rate_limiter = request.app.state.rate_limiter
            if hasattr(rate_limiter, "update_limits"):
                rate_limiter.update_limits(
                    max_requests_per_minute=app_config.MAX_REQUESTS_PER_MINUTE,
                    max_requests_per_day_per_ip=app_config.MAX_REQUESTS_PER_DAY_PER_IP,
                )

        logger.info(f"配置更新成功: {updated_fields}")
        return {
            "message": "配置更新成功（仅当前会话有效）",
            "updated_fields": updated_fields,
            "warning": "内存模式下配置修改不会持久化，重启服务后将恢复原始配置",
        }

    except Exception as e:
        logger.error(f"配置更新失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="配置更新失败"
        )


@router.get("/memory-warning")
async def get_memory_mode_warning():
    """
    获取内存模式的警告信息
    """
    if IS_MEMORY_DB:
        return {
            "warning": "当前运行在纯内存模式下，所有配置和数据仅在当前会话中有效，重启服务后将丢失",
            "storage_mode": "memory",
            "persistent_storage": False,
            "memory_mode": "memory",
        }
    else:
        return {
            "message": "当前运行在数据库模式下，配置和数据会持久化存储",
            "storage_mode": "database",
            "persistent_storage": True,
            "memory_mode": "database",
        }


@router.get("/validation")
async def validate_system_config():
    """
    验证系统配置的完整性和正确性
    """
    issues = []
    warnings = []

    # 检查必要的配置
    if not hasattr(app_config, "SECRET_KEY") or app_config.SECRET_KEY is None:
        issues.append("SECRET_KEY 未配置")

    # GEMINI_API_KEYS 可能未设置或为 None/空字符串
    if _get_gemini_api_keys_count() == 0:
        issues.append("GEMINI_API_KEYS 未配置")

    # 检查数据库配置
    if not hasattr(app_config, "DATABASE_URL") or app_config.DATABASE_URL is None:
        warnings.append("DATABASE_URL 未配置，将使用内存模式")

    return {"valid": len(issues) == 0, "issues": issues, "warnings": warnings}


@router.get("/diagnostics")
async def get_config_diagnostics():
    """
    获取系统诊断信息
    """
    return {
        "system_status": "normal",  # TODO: 实际状态检测
        "configuration": {
            "storage_mode": "database" if not IS_MEMORY_DB else "memory",
            "native_caching_enabled": getattr(
                app_config, "ENABLE_NATIVE_CACHING", False
            ),
            "auth_enabled": getattr(app_config, "AUTH_ENABLED", False),
        },
        "resources": {
            "api_keys_loaded": _get_gemini_api_keys_count(),
            "current_requests": 0,  # TODO: 获取实际请求数
            "memory_usage": 0,  # TODO: 获取实际内存使用
        },
    }
