# -*- coding: utf-8 -*-
"""
Web UI 认证相关的 FastAPI 依赖项。
定义了用于验证 JWT 令牌的依赖函数。
"""
import logging  # 导入日志模块
from typing import Any, Dict, Optional  # 导入类型提示

from fastapi import Depends, HTTPException, Request, status  # 导入 FastAPI 相关组件
from fastapi.security import (  # 导入用于处理 Bearer Token 的安全工具
    HTTPAuthorizationCredentials,
    HTTPBearer,
)

# 导入 JWT 解码函数
from gap.core.security.jwt import decode_access_token  # (新路径)

logger = logging.getLogger("my_logger")  # 获取日志记录器实例

# 创建一个 HTTP Bearer scheme 实例
# HTTPBearer 是 FastAPI 提供的一个安全工具类，用于从请求的 Authorization 头中提取 Bearer Token。
# auto_error=False: 表示如果请求头中没有 Authorization 或格式不正确，FastAPI 不会自动抛出 401 错误。
# 我们将在依赖函数 `verify_jwt_token` 内部手动检查 `credentials` 是否为 None，并抛出更具体的错误。
# 这允许我们提供更详细的日志记录或自定义错误响应。
bearer_scheme = HTTPBearer(auto_error=False)


async def verify_jwt_token(
    request: Request,  # 注入 FastAPI 请求对象，虽然当前未使用，但保留可能用于未来扩展（如记录请求信息）
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(
        bearer_scheme
    ),  # 依赖注入：尝试从请求头获取 Bearer Token 凭证
) -> Dict[str, Any]:
    """
    FastAPI 依赖项函数，用于验证通过 HTTP Bearer 方案提供的 JWT 令牌。
    此函数会检查 Authorization 请求头，提取 Bearer Token，然后解码并验证它。

    Args:
        request (Request): FastAPI 请求对象 (当前未使用)。
        credentials (Optional[HTTPAuthorizationCredentials]): FastAPI 从 Authorization 头提取的凭证对象。
                                                              如果请求头不存在或格式不正确，此值为 None。

    Returns:
        Dict[str, Any]: 如果令牌有效，返回解码后的 JWT payload (包含用户信息，如 'sub' 和 'admin')。

    Raises:
        HTTPException:
            - 401 Unauthorized: 如果没有提供有效的 Bearer Token，或者 Token 无效、过期、或缺少必要信息。
    """
    logger.debug(
        "verify_jwt_token: 开始验证 JWT token (仅从 Bearer Header 获取)"
    )  # 记录开始验证日志

    token = None  # 初始化 token 变量
    # 检查 credentials 是否存在，并且 scheme 是否为 'bearer' (不区分大小写)
    if credentials and credentials.scheme.lower() == "bearer":
        logger.debug(
            "verify_jwt_token: 从 Authorization 头中找到 Bearer token。"
        )  # 记录找到 Token 日志
        token = credentials.credentials  # 获取实际的 token 字符串

    # 如果未能从请求头中获取到 token
    if not token:
        logger.warning(
            "verify_jwt_token: 未找到有效的认证令牌 (仅检查 Bearer Header)。"
        )  # 记录警告日志
        # 抛出 401 未授权错误
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,  # 设置状态码
            detail="缺少有效的认证令牌",  # 设置错误详情
            headers={"WWW-Authenticate": "Bearer"},  # 添加响应头，指示需要 Bearer 认证
        )

    # 记录提取到的 token (部分隐藏)
    logger.debug(f"verify_jwt_token: 提取到 token (前10位): {token[:10]}...")

    # --- 解码并验证 token ---
    # 调用 jwt.py 中的 decode_access_token 函数
    payload = decode_access_token(token)  # 解码 token

    # 如果解码失败或 token 无效/过期，decode_access_token 会返回 None
    if payload is None:
        logger.warning(
            f"verify_jwt_token: JWT token 无效或已过期 (Token: {token[:10]}...)"
        )  # 记录警告日志
        # 抛出 401 未授权错误
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,  # 设置状态码
            detail="无效或已过期的 token",  # 设置错误详情
            headers={"WWW-Authenticate": "Bearer"},  # 添加响应头
        )

    # 记录解码成功的 payload (用于调试)
    logger.debug(f"verify_jwt_token: JWT payload 解码成功: {payload}")

    # --- 检查 payload 内容 ---
    # 验证 payload 中是否包含必要的用户信息 (例如 'sub' 字段)
    user_key = payload.get("sub")  # 获取 'sub' 字段 (通常是用户标识符)
    is_admin = payload.get("admin", False)  # 获取 'admin' 字段 (布尔值)，默认为 False
    if not user_key:  # 如果缺少 'sub' 字段
        logger.warning(
            f"JWT token 有效，但缺少 'sub' (用户标识符) 字段。Payload: {payload}"
        )  # 记录警告日志
        # 抛出 401 未授权错误
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,  # 设置状态码
            detail="无效的 token (缺少用户信息)",  # 设置错误详情
            headers={"WWW-Authenticate": "Bearer"},  # 添加响应头
        )

    # 如果所有验证通过
    logger.debug(
        f"verify_jwt_token: JWT token 验证成功. User Key: {user_key[:8]}..., Is Admin: {is_admin}"
    )  # 记录成功日志
    # 返回解码后的 payload 字典，路由处理函数可以从中获取用户信息
    return payload


async def verify_jwt_token_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> Optional[Dict[str, Any]]:
    """
    FastAPI 依赖项函数，可选地验证通过 HTTP Bearer 方案提供的 JWT 令牌。
    如果令牌有效，返回解码后的 payload；如果无效、过期或未提供，则返回 None。

    Args:
        credentials (Optional[HTTPAuthorizationCredentials]): FastAPI 从 Authorization 头提取的凭证对象。

    Returns:
        Optional[Dict[str, Any]]: 如果令牌有效，返回解码后的 JWT payload，否则返回 None。
    """
    logger.debug("verify_jwt_token_optional: 开始可选的 JWT token 验证")
    token = None
    if credentials and credentials.scheme.lower() == "bearer":
        token = credentials.credentials
        logger.debug(
            f"verify_jwt_token_optional: 提取到 token (前10位): {token[:10]}..."
        )

    if not token:
        logger.debug("verify_jwt_token_optional: 未找到 Bearer token。")
        return None

    payload = decode_access_token(
        token
    )  # decode_access_token 内部处理无效/过期情况并返回 None

    if payload is None:
        logger.debug(
            f"verify_jwt_token_optional: JWT token 无效或已过期 (Token: {token[:10]}...)"
        )
        return None

    user_key = payload.get("sub")
    if not user_key:
        logger.warning(
            f"verify_jwt_token_optional: JWT token 有效，但缺少 'sub' 字段。Payload: {payload}"
        )
        return None  # 视为无效

    logger.debug(
        f"verify_jwt_token_optional: JWT token 验证成功. User Key: {user_key[:8]}..."
    )
    return payload
