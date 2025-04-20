# -*- coding: utf-8 -*-
"""
Web UI 认证相关的依赖项。
"""
import logging
from typing import Optional, Dict, Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.core.security import decode_access_token

logger = logging.getLogger('my_logger')

# 创建一个 HTTP Bearer scheme 实例
# auto_error=False 意味着如果 Authorization 头不存在或格式不正确，不会自动抛出错误，
# 我们将在函数内部处理这种情况，以便可以返回更具体的错误或重定向。
# 但是，对于需要强制认证的依赖项，通常设置为 True 或在函数内检查 credentials 是否为 None。
# 考虑到我们要保护管理页面，如果没 token 就应该拒绝访问，所以 auto_error=True 更合适，
# 或者在函数内显式检查并抛出 401/403。我们选择后者以提供更清晰的日志和错误信息。
bearer_scheme = HTTPBearer(auto_error=False) # 先不自动报错，手动检查

async def verify_jwt_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme)
) -> Dict[str, Any]:
    """
    FastAPI 依赖项，用于验证 JWT Bearer Token。

    从 Authorization 头获取 Bearer Token，解码并验证它。

    Args:
        credentials: 由 FastAPI 从请求头中提取的认证凭证。

    Returns:
        解码后的 JWT payload 字典。

    Raises:
        HTTPException:
            - 403 Forbidden: 如果没有提供 Authorization 头或 scheme 不是 Bearer。
            - 401 Unauthorized: 如果 Token 无效、过期或解码失败。
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        logger.debug("缺少有效的 Bearer token 或 scheme 不正确。")
        # 对于 Web UI 页面访问，重定向到登录页可能更用户友好，但这通常在路由或中间件中处理。
        # 对于 API 依赖项，返回 403 或 401 是标准的。这里用 403 表示“禁止访问”（因为缺少凭证）。
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要提供有效的 Bearer token",
            headers={"WWW-Authenticate": "Bearer"}, # 按标准建议包含此头
        )

    token = credentials.credentials
    payload = decode_access_token(token)

    if payload is None:
        logger.debug(f"JWT token 无效或已过期 (Token: {token[:10]}...)")
        # 使用 401 表示“未授权”（因为提供的凭证无效）。
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效或已过期的 token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 可以在这里添加基于 payload 内容的额外检查
    user_key = payload.get("sub")
    is_admin = payload.get("admin", False) # 从 payload 获取 admin 状态，默认为 False
    if not user_key:
        logger.warning(f"JWT token 有效，但缺少 'sub' (用户标识符) 字段。Payload: {payload}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的 token (缺少用户信息)",
            headers={"WWW-Authenticate": "Bearer"},
        )

    logger.debug(f"JWT token 验证成功. User Key: {user_key[:8]}..., Is Admin: {is_admin}")
    return payload # 返回完整的 payload，路由函数可以从中提取 'sub' 和 'admin'