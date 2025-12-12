# -*- coding: utf-8 -*-
"""
调试信息 API 端点
提供系统调试信息接口
"""
import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends

from gap.core.dependencies import verify_admin_token

logger = logging.getLogger("my_logger")

router = APIRouter()


@router.get("/config")
async def get_debug_config(auth_data: Dict[str, Any] = Depends(verify_admin_token)):
    """
    获取调试配置信息

    仅管理员可访问

    Args:
        auth_data: 认证数据

    Returns:
        Dict[str, Any]: 调试配置信息
    """
    return {
        "environment": "development",
        "debug_mode": True,
        "api_keys": ["***masked***"],
        "database": "connected",
        "redis": "connected",
    }
