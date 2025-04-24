# -*- coding: utf-8 -*-
"""
安全相关工具函数，主要用于 JWT 令牌的创建和验证。
Security related utility functions, mainly for JWT token creation and verification.
"""
from datetime import datetime, timedelta, timezone # 导入日期、时间、时区相关 (Import date, time, timezone related)
from typing import Optional, Dict, Any # 导入类型提示 (Import type hints)
import logging # 导入 logging 模块 (Import logging module)

from jose import jwt, JWTError # 导入 jose 库用于 JWT 操作 (Import jose library for JWT operations)
from app import config # 导入配置 (Import config)

logger = logging.getLogger('my_logger') # 获取日志记录器实例 (Get logger instance)

# 从配置中获取 JWT 设置
# Get JWT settings from configuration
SECRET_KEY = config.SECRET_KEY # JWT 签名密钥 (JWT signing key)
ALGORITHM = config.JWT_ALGORITHM # JWT 签名算法 (JWT signing algorithm)
ACCESS_TOKEN_EXPIRE_MINUTES = config.ACCESS_TOKEN_EXPIRE_MINUTES # 访问令牌过期时间（分钟） (Access token expiration time in minutes)

def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """
    创建 JWT 访问令牌。
    Creates a JWT access token.

    Args:
        data: 要编码到令牌中的数据字典。The dictionary of data to encode into the token.
        expires_delta: 可选的令牌过期时间增量。如果未提供，则使用配置中的默认值。Optional token expiration time delta. If not provided, the default value from configuration is used.

    Returns:
        编码后的 JWT 字符串。The encoded JWT string.

    Raises:
        ValueError: 如果 SECRET_KEY 未设置。If SECRET_KEY is not set.
    """
    if not SECRET_KEY: # 如果 SECRET_KEY 未设置 (If SECRET_KEY is not set)
        logger.error("JWT SECRET_KEY 未配置，无法创建令牌。") # 记录错误 (Log error)
        raise ValueError("JWT SECRET_KEY 未在环境变量中设置") # 引发 ValueError (Raise ValueError)

    to_encode = data.copy() # 复制数据以避免修改原始字典 (Copy data to avoid modifying the original dictionary)
    if expires_delta: # 如果提供了过期时间增量 (If expiration time delta is provided)
        expire = datetime.now(timezone.utc) + expires_delta # 计算过期时间 (Calculate expiration time)
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES) # 使用默认过期时间 (Use default expiration time)

    to_encode.update({"exp": expire}) # 将过期时间添加到数据中 (Add expiration time to data)
    try:
        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM) # 使用 jose 库编码 JWT (Encode JWT using jose library)
        return encoded_jwt # 返回编码后的 JWT (Return the encoded JWT)
    except Exception as e: # 捕获编码过程中可能发生的任何异常 (Catch any exception that might occur during encoding)
        logger.error(f"创建 JWT 时发生错误: {e}", exc_info=True) # 记录错误 (Log error)
        raise # 重新抛出异常，以便上层处理 (Re-raise the exception for upper layer handling)

def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """
    解码并验证 JWT 访问令牌。
    Decodes and verifies a JWT access token.

    Args:
        token: 要解码的 JWT 字符串。The JWT string to decode.

    Returns:
        解码后的令牌 payload 字典，如果令牌无效或过期则返回 None。The decoded token payload dictionary, or None if the token is invalid or expired.

    Raises:
        ValueError: 如果 SECRET_KEY 未设置。If SECRET_KEY is not set.
    """
    if not SECRET_KEY: # 如果 SECRET_KEY 未设置 (If SECRET_KEY is not set)
        logger.error("JWT SECRET_KEY 未配置，无法解码令牌。") # 记录错误 (Log error)
        raise ValueError("JWT SECRET_KEY 未在环境变量中设置") # 引发 ValueError (Raise ValueError)

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM]) # 使用 jose 库解码 JWT (Decode JWT using jose library)
        # 可选：检查 'exp' 字段是否存在且为数字类型
        # Optional: Check if the 'exp' field exists and is of numeric type
        if "exp" not in payload or not isinstance(payload["exp"], (int, float)): # 如果缺少 exp 字段或类型不正确 (If exp field is missing or type is incorrect)
             logger.warning(f"解码后的 JWT payload 中缺少有效的 'exp' 字段: {payload}") # 记录警告 (Log warning)
             return None # 返回 None (Return None)
        # 可选：再次检查令牌是否已过期（虽然 jwt.decode 内部会进行检查，但可以显式确认以增加健壮性）
        # Optional: Check again if the token has expired (although jwt.decode checks internally, explicit confirmation can increase robustness)
        # exp_timestamp = payload["exp"]
        # if datetime.now(timezone.utc).timestamp() > exp_timestamp:
        #     logger.debug(f"JWT 令牌已过期: {token[:10]}...") # 记录部分 token 以供调试 (Log partial token for debugging)
        #     return None

        # 可以在此处添加额外的验证逻辑，例如检查 'sub' (subject) 字段是否存在等
        # Additional validation logic can be added here, such as checking if the 'sub' (subject) field exists, etc.
        return payload # 返回解码后的 payload (Return the decoded payload)
    except JWTError as e: # 捕获所有 JWT 相关错误（例如过期、签名无效、格式错误等） (Catch all JWT related errors (e.g., expired, invalid signature, format errors, etc.))
        logger.debug(f"JWT 验证失败: {e} (Token: {token[:10]}...)") # 记录 JWT 错误信息，但不记录完整的 token (Log JWT error message, but not the full token)
        return None # 返回 None (Return None)
    except Exception as e: # 捕获其他在解码过程中可能发生的意外错误 (Catch other unexpected errors that might occur during decoding)
        logger.error(f"解码 token 时发生意外错误: {e}", exc_info=True) # 记录意外错误 (Log unexpected error)
        return None # 返回 None (Return None)
