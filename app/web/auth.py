# -*- coding: utf-8 -*-
"""
Web UI 认证相关的依赖项。
Web UI authentication related dependencies.
"""
import logging # 导入 logging 模块 (Import logging module)
from typing import Optional, Dict, Any # 导入类型提示 (Import type hints)

from fastapi import Depends, HTTPException, status # 导入 FastAPI 相关组件 (Import FastAPI related components)
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials # 导入 HTTPBearer 和 HTTPAuthorizationCredentials (Import HTTPBearer and HTTPAuthorizationCredentials)

from app.core.security import decode_access_token # 导入解码访问令牌函数 (Import decode_access_token function)

logger = logging.getLogger('my_logger') # 获取日志记录器实例 (Get logger instance)

# 创建一个 HTTP Bearer scheme 实例
# Create an HTTP Bearer scheme instance
# auto_error=False 意味着如果 Authorization 头不存在或格式不正确，不会自动抛出错误，
# auto_error=False means that if the Authorization header is missing or has an incorrect format, it will not automatically raise an error,
# 我们将在函数内部处理这种情况，以便可以返回更具体的错误或重定向。
# we will handle this case inside the function so that a more specific error or redirection can be returned.
# 但是，对于需要强制认证的依赖项，通常设置为 True 或在函数内检查 credentials 是否为 None。
# However, for dependencies that require mandatory authentication, it is usually set to True or credentials is checked for None inside the function.
# 考虑到我们要保护管理页面，如果没 token 就应该拒绝访问，所以 auto_error=True 更合适，
# Considering that we want to protect the management page, access should be denied if there is no token, so auto_error=True is more appropriate,
# 或者在函数内显式检查并抛出 401/403。我们选择后者以提供更清晰的日志和错误信息。
# or explicitly check and raise 401/403 inside the function. We choose the latter to provide clearer logs and error messages.
bearer_scheme = HTTPBearer(auto_error=False) # 先不自动报错，手动检查 (Do not auto-error initially, check manually)

async def verify_jwt_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme) # 依赖 HTTP Bearer scheme 并获取凭证 (Depends on HTTP Bearer scheme and gets credentials)
) -> Dict[str, Any]:
    """
    FastAPI 依赖项，用于验证 JWT Bearer Token。
    FastAPI dependency for verifying JWT Bearer Tokens.

    从 Authorization 头获取 Bearer Token，解码并验证它。
    Gets the Bearer Token from the Authorization header, decodes, and verifies it.

    Args:
        credentials: 由 FastAPI 从请求头中提取的认证凭证。Authentication credentials extracted by FastAPI from the request header.

    Returns:
        解码后的 JWT payload 字典。The decoded JWT payload dictionary.

    Raises:
        HTTPException:
            - 403 Forbidden: 如果没有提供 Authorization 头或 scheme 不是 Bearer。If the Authorization header is not provided or the scheme is not Bearer.
            - 401 Unauthorized: 如果 Token 无效、过期或解码失败。If the Token is invalid, expired, or decoding fails.
    """
    if credentials is None or credentials.scheme.lower() != "bearer": # 检查凭证是否存在或 scheme 不正确 (Check if credentials exist or scheme is incorrect)
        logger.debug("缺少有效的 Bearer token 或 scheme 不正确。") # 记录 debug 信息 (Log debug message)
        # 对于 Web UI 页面访问，重定向到登录页可能更用户友好，但这通常在路由或中间件中处理。
        # For Web UI page access, redirecting to the login page might be more user-friendly, but this is usually handled in routes or middleware.
        # 对于 API 依赖项，返回 403 或 401 是标准的。这里用 403 表示“禁止访问”（因为缺少凭证）。
        # For API dependencies, returning 403 or 401 is standard. Here 403 is used to indicate "Forbidden" (due to missing credentials).
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, # 禁止访问状态码 (Forbidden status code)
            detail="需要提供有效的 Bearer token", # 错误详情 (Error detail)
            headers={"WWW-Authenticate": "Bearer"}, # 按标准建议包含此头 (Include this header as per standard recommendation)
        )

    token = credentials.credentials # 获取令牌字符串 (Get the token string)
    payload = decode_access_token(token) # 解码访问令牌 (Decode the access token)

    if payload is None: # 如果 payload 为 None (If payload is None)
        logger.debug(f"JWT token 无效或已过期 (Token: {token[:10]}...)") # 记录 debug 信息 (Log debug message)
        # 使用 401 表示“未授权”（因为提供的凭证无效）。
        # Use 401 to indicate "Unauthorized" (because the provided credentials are invalid).
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, # 未授权状态码 (Unauthorized status code)
            detail="无效或已过期的 token", # 错误详情 (Error detail)
            headers={"WWW-Authenticate": "Bearer"}, # WWW-Authenticate 头 (WWW-Authenticate header)
        )

    # 可以在这里添加基于 payload 内容的额外检查
    # Additional checks based on payload content can be added here
    user_key = payload.get("sub") # 从 payload 获取用户 Key (Get user key from payload)
    is_admin = payload.get("admin", False) # 从 payload 获取 admin 状态，默认为 False (Get admin status from payload, default is False)
    if not user_key: # 如果缺少用户 Key (If user key is missing)
        logger.warning(f"JWT token 有效，但缺少 'sub' (用户标识符) 字段。Payload: {payload}") # 记录警告 (Log warning)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, # 未授权状态码 (Unauthorized status code)
            detail="无效的 token (缺少用户信息)", # 错误详情 (Error detail)
            headers={"WWW-Authenticate": "Bearer"}, # WWW-Authenticate 头 (WWW-Authenticate header)
        )

    logger.debug(f"JWT token 验证成功. User Key: {user_key[:8]}..., Is Admin: {is_admin}") # 记录验证成功信息 (Log successful verification info)
    return payload # 返回完整的 payload，路由函数可以从中提取 'sub' 和 'admin' (Return the full payload, route functions can extract 'sub' and 'admin' from it)
