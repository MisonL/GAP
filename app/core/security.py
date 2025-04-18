# -*- coding: utf-8 -*-
"""
安全相关工具函数，主要用于 JWT 令牌的创建和验证。
"""
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
import logging

from jose import jwt, JWTError
from app import config # 导入配置

logger = logging.getLogger('my_logger')

# 从配置中获取 JWT 设置
SECRET_KEY = config.SECRET_KEY
ALGORITHM = config.JWT_ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = config.ACCESS_TOKEN_EXPIRE_MINUTES

def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """
    创建 JWT 访问令牌。

    Args:
        data: 要编码到令牌中的数据字典。
        expires_delta: 可选的令牌过期时间增量。如果未提供，则使用配置中的默认值。

    Returns:
        编码后的 JWT 字符串。

    Raises:
        ValueError: 如果 SECRET_KEY 未设置。
    """
    if not SECRET_KEY:
        logger.error("JWT SECRET_KEY 未配置，无法创建令牌。")
        raise ValueError("JWT SECRET_KEY 未在环境变量中设置")

    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire})
    try:
        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        return encoded_jwt
    except Exception as e:
        logger.error(f"创建 JWT 时发生错误: {e}", exc_info=True)
        raise # 重新抛出异常，以便上层处理

def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """
    解码并验证 JWT 访问令牌。

    Args:
        token: 要解码的 JWT 字符串。

    Returns:
        解码后的令牌 payload 字典，如果令牌无效或过期则返回 None。

    Raises:
        ValueError: 如果 SECRET_KEY 未设置。
    """
    if not SECRET_KEY:
        logger.error("JWT SECRET_KEY 未配置，无法解码令牌。")
        raise ValueError("JWT SECRET_KEY 未在环境变量中设置")

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        # 可选：检查 'exp' 是否存在且是数字
        if "exp" not in payload or not isinstance(payload["exp"], (int, float)):
             logger.warning(f"解码的 JWT payload 中缺少有效的 'exp' 字段: {payload}")
             return None
        # 可选：检查令牌是否已过期 (虽然 jwt.decode 会检查，但可以显式确认)
        # exp_timestamp = payload["exp"]
        # if datetime.now(timezone.utc).timestamp() > exp_timestamp:
        #     logger.debug(f"JWT 已过期: {token}")
        #     return None

        # 可以在这里添加额外的验证，例如检查 'sub' 是否存在等
        return payload
    except JWTError as e: # 捕获所有 JWT 相关错误 (过期、签名无效等)
        logger.debug(f"JWT 验证失败: {e} (Token: {token[:10]}...)") # 记录 JWT 错误，但不记录完整 token
        return None
    except Exception as e: # 捕获其他可能的解码错误
        logger.error(f"解码 token 时发生意外错误: {e}", exc_info=True)
        return None