# -*- coding: utf-8 -*-
"""
Web UI 认证相关的依赖项。
"""
import logging # 导入 logging 模块
from typing import Optional, Dict, Any # 导入类型提示

from fastapi import Depends, HTTPException, status, Request # 导入 FastAPI 相关组件，增加 Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials # 导入 HTTPBearer 和 HTTPAuthorizationCredentials

from app.core.security import decode_access_token # 导入解码访问令牌函数

logger = logging.getLogger('my_logger')

# 创建一个 HTTP Bearer scheme 实例
# auto_error=False 意味着如果 Authorization 头不存在或格式不正确，不会自动抛出错误，
# 我们将在函数内部处理这种情况，以便可以返回更具体的错误或重定向。
# 但是，对于需要强制认证的依赖项，通常设置为 True 或在函数内检查 credentials 是否为 None。
# 考虑到我们要保护管理页面，如果没 token 就应该拒绝访问，所以 auto_error=True 更合适，
# 或者在函数内显式检查并抛出 401/403。我们选择后者以提供更清晰的日志和错误信息。
bearer_scheme = HTTPBearer(auto_error=False) # 先不自动报错，手动检查

async def verify_jwt_token(
    request: Request, # 添加 Request 参数以便访问 Cookie
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme) # 依赖 HTTP Bearer scheme 并获取凭证
) -> Dict[str, Any]:
    """
    FastAPI 依赖项，用于验证 JWT 令牌。
    尝试从 Authorization 头 (Bearer scheme) 获取令牌。

    Args:
        request: FastAPI 请求对象。
        credentials: 由 FastAPI 从 Authorization 头提取的认证凭证 (如果存在)。

    Returns:
        解码后的 JWT payload 字典。

    Raises:
        HTTPException:
            - 401 Unauthorized: 如果没有提供有效的令牌（Bearer Header）或令牌无效/过期。
    """
    logger.debug("verify_jwt_token: 开始验证 JWT token (仅从 Bearer Header 获取)")

    token = None
    # 仅从 Authorization 头获取 Bearer token
    # Only get Bearer token from Authorization header
    if credentials and credentials.scheme.lower() == "bearer":
        logger.debug("verify_jwt_token: 从 Authorization 头中找到 Bearer token。")
        token = credentials.credentials

    # 如果没有 token，则认证失败
    # If no token, authentication fails
    if not token:
        logger.debug("verify_jwt_token: 未找到有效的认证令牌 (仅检查 Bearer Header)。")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少有效的认证令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )

    logger.debug(f"verify_jwt_token: 提取到 token (前10位): {token[:10]}...")

    # 解码并验证 token
    # Decode and verify token
    payload = decode_access_token(token)

    if payload is None:
        logger.debug(f"verify_jwt_token: JWT token 无效或已过期 (Token: {token[:10]}...)")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效或已过期的 token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    logger.debug(f"verify_jwt_token: JWT payload 解码成功: {payload}")

    # 检查 payload 内容
    # Check payload content
    user_key = payload.get("sub")
    is_admin = payload.get("admin", False)
    if not user_key:
        logger.warning(f"JWT token 有效，但缺少 'sub' (用户标识符) 字段。Payload: {payload}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的 token (缺少用户信息)",
            headers={"WWW-Authenticate": "Bearer"},
        )

    logger.debug(f"verify_jwt_token: JWT token 验证成功. User Key: {user_key[:8]}..., Is Admin: {is_admin}")
    return payload # 返回完整的 payload，路由函数可以从中提取 'sub' 和 'admin'
