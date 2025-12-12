# -*- coding: utf-8 -*-
"""
配置验证API端点。
提供配置验证和诊断的HTTP接口。
"""
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, status

from gap.core.config.validation import validate_config
from gap.core.dependencies import get_auth_data

logger = logging.getLogger("my_logger")

# 创建路由器
router = APIRouter()


@router.get("/validation", response_model=Dict[str, Any])
async def validate_system_config(auth_data: Dict[str, Any] = Depends(get_auth_data)):
    """
    验证系统配置

    需要认证访问。

    Returns:
        Dict[str, Any]: 验证结果，包含状态、错误和警告
    """
    try:
        # 检查用户权限
        is_admin = auth_data.get("config", {}).get("is_admin", False)
        if not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="需要管理员权限才能访问配置验证",
            )

        # 执行配置验证
        is_valid, errors, warnings = validate_config()

        result = {
            "valid": is_valid,
            "errors": errors,
            "warnings": warnings,
            "error_count": len(errors),
            "warning_count": len(warnings),
            "timestamp": "2025-01-28T00:00:00Z",  # 这里应该使用实际时间戳
        }

        # 根据验证结果设置HTTP状态码
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"配置验证失败，发现 {len(errors)} 个错误和 {len(warnings)} 个警告",
            )

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"配置验证API错误: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="配置验证过程中发生内部错误",
        )


@router.post("/fix", response_model=Dict[str, Any])
async def auto_fix_config(auth_data: Dict[str, Any] = Depends(get_auth_data)):
    """
    尝试自动修复配置问题

    需要管理员权限。

    注意：此功能目前仅提供诊断信息，不会自动修改配置。

    Returns:
        Dict[str, Any]: 修复建议结果
    """
    try:
        # 检查管理员权限
        is_admin = auth_data.get("config", {}).get("is_admin", False)
        if not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="需要管理员权限才能执行配置修复",
            )

        # 执行配置验证
        is_valid, errors, warnings = validate_config()

        # 生成修复建议
        suggestions: List[Dict[str, Any]] = []

        for error in errors:
            if "SECRET_KEY" in error:
                suggestions.append(
                    {
                        "type": "critical",
                        "issue": error,
                        "suggestion": "设置环境变量 SECRET_KEY 为强随机字符串",
                        "command": "export SECRET_KEY=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')",
                    }
                )
            elif "DATABASE_URL" in error:
                suggestions.append(
                    {
                        "type": "critical",
                        "issue": error,
                        "suggestion": "正确配置数据库连接字符串",
                        "example": "postgresql://user:password@localhost:5432/dbname",
                    }
                )
            elif "必须为正" in error:
                suggestions.append(
                    {
                        "type": "error",
                        "issue": error,
                        "suggestion": "检查相关配置值，确保为正数",
                    }
                )

        for warning in warnings:
            if "密码" in warning:
                suggestions.append(
                    {
                        "type": "security",
                        "issue": warning,
                        "suggestion": "使用更强的密码，至少8个字符，包含大小写字母、数字和特殊字符",
                    }
                )
            elif "时间" in warning or "timeout" in warning.lower():
                suggestions.append(
                    {
                        "type": "performance",
                        "issue": warning,
                        "suggestion": "调整超时设置以获得更好的性能和稳定性",
                    }
                )
            else:
                suggestions.append(
                    {
                        "type": "recommendation",
                        "issue": warning,
                        "suggestion": "根据警告信息调整配置",
                    }
                )

        result = {
            "auto_fix_enabled": False,  # 当前版本不启用自动修复
            "suggestions": suggestions,
            "issues_found": len(errors) + len(warnings),
            "critical_issues": len([s for s in suggestions if s["type"] == "critical"]),
            "can_auto_fix": False,  # 大多数配置需要手动设置
            "message": "当前版本仅提供诊断信息，请根据建议手动修复配置问题",
        }

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"配置修复API错误: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="配置修复诊断过程中发生内部错误",
        )


@router.get("/diagnostics", response_model=Dict[str, Any])
async def get_config_diagnostics(auth_data: Dict[str, Any] = Depends(get_auth_data)):
    """
    获取详细的配置诊断信息

    需要认证访问。

    Returns:
        Dict[str, Any]: 详细的诊断信息
    """
    try:
        # 检查用户权限
        is_admin = auth_data.get("config", {}).get("is_admin", False)
        if not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="需要管理员权限才能访问配置诊断",
            )

        from gap import config

        # 收集配置信息（隐藏敏感数据）
        diagnostics = {
            "version": getattr(config, "__version__", "unknown"),
            "environment": {
                "auth_enabled": getattr(config, "AUTH_ENABLED", False),
                "key_storage_mode": getattr(config, "KEY_STORAGE_MODE", "unknown"),
                "context_storage_mode": getattr(
                    config, "CONTEXT_STORAGE_MODE", "unknown"
                ),
                "enable_native_caching": getattr(
                    config, "ENABLE_NATIVE_CACHING", False
                ),
                "enable_docs": getattr(config, "ENABLE_DOCS", True),
            },
            "security": {
                "jwt_algorithm": getattr(config, "JWT_ALGORITHM", "unknown"),
                "token_expire_minutes": getattr(
                    config, "ACCESS_TOKEN_EXPIRE_MINUTES", 0
                ),
                "admin_api_key_configured": bool(
                    getattr(config, "ADMIN_API_KEY", False)
                ),
                "web_ui_passwords_configured": bool(
                    getattr(config, "WEB_UI_PASSWORDS", False)
                ),
                "disable_safety_filtering": getattr(
                    config, "DISABLE_SAFETY_FILTERING", False
                ),
            },
            "timeouts": {
                "http_connect": getattr(config, "HTTP_TIMEOUT_CONNECT", 0),
                "http_read": getattr(config, "HTTP_TIMEOUT_READ", 0),
                "http_write": getattr(config, "HTTP_TIMEOUT_WRITE", 0),
                "http_pool": getattr(config, "HTTP_TIMEOUT_POOL", 0),
                "api_models_list": getattr(config, "API_TIMEOUT_MODELS_LIST", 0),
                "api_key_test": getattr(config, "API_TIMEOUT_KEY_TEST", 0),
            },
            "model_limits": {
                "available_models": list(getattr(config, "MODEL_LIMITS", {}).keys()),
                "model_count": len(getattr(config, "MODEL_LIMITS", {})),
                "has_limits": bool(getattr(config, "MODEL_LIMITS", {})),
            },
            "cache_settings": {
                "cache_refresh_interval": getattr(
                    config, "CACHE_REFRESH_INTERVAL_SECONDS", 0
                ),
                "enable_context_completion": getattr(
                    config, "ENABLE_CONTEXT_COMPLETION", True
                ),
                "enable_sticky_session": getattr(
                    config, "ENABLE_STICKY_SESSION", False
                ),
                "context_ttl_days": getattr(config, "DEFAULT_CONTEXT_TTL_DAYS", 0),
                "memory_cleanup_interval": getattr(
                    config, "MEMORY_CONTEXT_CLEANUP_INTERVAL_SECONDS", 0
                ),
            },
            "rate_limits": {
                "max_requests_per_minute": getattr(
                    config, "MAX_REQUESTS_PER_MINUTE", 0
                ),
                "max_requests_per_day_per_ip": getattr(
                    config, "MAX_REQUESTS_PER_DAY_PER_IP", 0
                ),
            },
        }

        # 执行验证并添加结果
        is_valid, errors, warnings = validate_config()
        diagnostics["validation"] = {
            "is_valid": is_valid,
            "errors": errors,
            "warnings": warnings,
            "error_count": len(errors),
            "warning_count": len(warnings),
        }

        return diagnostics

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"配置诊断API错误: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取配置诊断信息时发生内部错误",
        )
