# -*- coding: utf-8 -*-
"""
安全相关工具函数，主要用于 JWT 令牌的创建和验证。
"""
from datetime import datetime, timedelta, timezone # 导入日期、时间、时区相关
from typing import Optional, Dict, Any # 导入类型提示
import logging # 导入 logging 模块

from jose import jwt, JWTError # 导入 jose 库用于 JWT 操作
from app import config # 导入配置

logger = logging.getLogger('my_logger')

# 从配置中获取 JWT 设置
# Get JWT settings from configuration
SECRET_KEY = config.SECRET_KEY # JWT 签名密钥
ALGORITHM = config.JWT_ALGORITHM # JWT 签名算法
ACCESS_TOKEN_EXPIRE_MINUTES = config.ACCESS_TOKEN_EXPIRE_MINUTES # 访问令牌过期时间（分钟）

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

    to_encode = data.copy() # 复制数据以避免修改原始字典
    if expires_delta: # 如果提供了过期时间增量
        expire = datetime.now(timezone.utc) + expires_delta # 计算过期时间
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES) # 使用默认过期时间

    to_encode.update({"exp": expire}) # 将过期时间添加到数据中
    try:
        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM) # 使用 jose 库编码 JWT
        return encoded_jwt # 返回编码后的 JWT
    except Exception as e: # 捕获编码过程中可能发生的任何异常
        logger.error(f"创建 JWT 时发生错误: {e}", exc_info=True) # 记录错误
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

    logger.debug(f"decode_access_token: 使用的 SECRET_KEY (前8位): {SECRET_KEY[:8]}...") # 添加日志打印 SECRET_KEY
    logger.debug(f"decode_access_token: 使用的 ALGORITHM: {ALGORITHM}") # 添加日志打印 ALGORITHM

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM]) # 使用 jose 库解码 JWT
        # 可选：检查 'exp' 字段是否存在且为数字类型
        if "exp" not in payload or not isinstance(payload["exp"], (int, float)):
             logger.warning(f"解码后的 JWT payload 中缺少有效的 'exp' 字段: {payload}")
             return None
        # 可选：再次检查令牌是否已过期（虽然 jwt.decode 内部会进行检查，但可以显式确认以增加健壮性）
        # exp_timestamp = payload["exp"]
        # if datetime.now(timezone.utc).timestamp() > exp_timestamp:
        #     logger.debug(f"JWT 令牌已过期: {token[:10]}...") # 记录部分 token 以供调试
        #     return None

        # 可以在此处添加额外的验证逻辑，例如检查 'sub' (subject) 字段是否存在等
        return payload # 返回解码后的 payload
    except JWTError as e: # 捕获所有 JWT 相关错误（例如过期、签名无效、格式错误等）
        logger.debug(f"JWT 验证失败: {e} (Token: {token[:10]}...)") # 记录 JWT 错误信息，但不记录完整的 token
        return None # 返回 None
    except Exception as e: # 捕获其他在解码过程中可能发生的意外错误
        logger.error(f"解码 token 时发生意外错误: {e}", exc_info=True) # 记录意外错误
        return None # 返回 None
