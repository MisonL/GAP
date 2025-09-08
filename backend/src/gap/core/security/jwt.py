# -*- coding: utf-8 -*-
"""
安全相关工具函数，主要用于 JWT (JSON Web Token) 令牌的创建和验证。
使用 python-jose 库进行 JWT 操作。
"""
from datetime import datetime, timedelta, timezone # 导入日期时间处理相关模块
from typing import Optional, Dict, Any # 导入类型提示
import logging # 导入日志模块

from jose import jwt, JWTError # 从 jose 库导入 jwt 编码/解码函数和 JWT 错误类
from gap import config # 导入应用配置模块

logger = logging.getLogger('my_logger') # 获取日志记录器实例

# --- 从配置中加载 JWT 相关设置 ---
# SECRET_KEY: 用于签名和验证 JWT 的密钥。必须保密！
SECRET_KEY = config.SECRET_KEY
# ALGORITHM: 用于签名 JWT 的算法，例如 "HS256"。
ALGORITHM = config.JWT_ALGORITHM
# ACCESS_TOKEN_EXPIRE_MINUTES: 访问令牌的默认过期时间（分钟）。
ACCESS_TOKEN_EXPIRE_MINUTES = config.ACCESS_TOKEN_EXPIRE_MINUTES

def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """
    创建 JWT 访问令牌。

    Args:
        data (Dict[str, Any]): 需要编码到令牌 payload 中的数据字典 (例如包含用户 ID 'sub')。
        expires_delta (Optional[timedelta]): 可选参数，指定令牌的有效时长。
                                             如果未提供，则使用配置中的 `ACCESS_TOKEN_EXPIRE_MINUTES`。

    Returns:
        str: 编码后的 JWT 访问令牌字符串。

    Raises:
        ValueError: 如果配置中未设置 `SECRET_KEY`。
        Exception: 如果在 JWT 编码过程中发生其他错误。
    """
    # 检查密钥是否存在
    if not SECRET_KEY:
        logger.error("JWT SECRET_KEY 未配置，无法创建令牌。") # 记录严重错误
        raise ValueError("JWT SECRET_KEY 未在环境变量中设置") # 抛出值错误

    to_encode = data.copy() # 创建数据字典的副本，避免修改原始数据
    # 计算过期时间
    if expires_delta: # 如果提供了自定义的过期时长
        expire = datetime.now(timezone.utc) + expires_delta # 使用当前 UTC 时间加上指定时长
    else: # 如果未提供自定义时长
        # 使用配置中定义的默认分钟数计算过期时间
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    # 将过期时间 ('exp' claim) 添加到要编码的数据中
    to_encode.update({"exp": expire})
    try:
        # 使用 jose.jwt.encode 函数生成 JWT
        # - to_encode: 要编码的 payload 数据
        # - SECRET_KEY: 签名密钥
        # - algorithm: 签名算法
        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        logger.debug(f"成功创建 JWT 令牌，过期时间: {expire}") # 记录调试日志
        return encoded_jwt # 返回编码后的 JWT 字符串
    except Exception as e: # 捕获编码过程中可能发生的任何异常
        logger.error(f"创建 JWT 时发生错误: {e}", exc_info=True) # 记录错误日志
        raise # 重新抛出异常，让上层调用者处理

def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """
    解码并验证 JWT 访问令牌。
    验证内容包括：签名、过期时间。

    Args:
        token (str): 需要解码和验证的 JWT 字符串。

    Returns:
        Optional[Dict[str, Any]]: 如果令牌有效且未过期，返回解码后的 payload 字典；
                                  否则返回 None。

    Raises:
        ValueError: 如果配置中未设置 `SECRET_KEY`。
    """
    # 检查密钥是否存在
    if not SECRET_KEY:
        logger.error("JWT SECRET_KEY 未配置，无法解码令牌。") # 记录严重错误
        raise ValueError("JWT SECRET_KEY 未在环境变量中设置") # 抛出值错误

    # 记录调试信息，显示使用的密钥前缀和算法
    logger.debug(f"decode_access_token: 使用的 SECRET_KEY (前8位): {SECRET_KEY[:8]}...")
    logger.debug(f"decode_access_token: 使用的 ALGORITHM: {ALGORITHM}")

    try:
        # 使用 jose.jwt.decode 函数解码并验证 JWT
        # - token: 要解码的 JWT 字符串
        # - SECRET_KEY: 用于验证签名的密钥
        # - algorithms: 指定允许的签名算法列表
        # decode 函数会自动验证签名和过期时间 ('exp' claim)
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

        # --- 可选的额外验证 ---
        # 1. 检查 'exp' 字段是否存在且类型正确 (虽然 jose 库通常会处理)
        if "exp" not in payload or not isinstance(payload["exp"], (int, float)):
             logger.warning(f"解码后的 JWT payload 中缺少有效的 'exp' 字段: {payload}") # 记录警告
             return None # 视为无效

        # 2. 可以再次显式检查过期时间 (双重保险)
        # exp_timestamp = payload["exp"]
        # if datetime.now(timezone.utc).timestamp() > exp_timestamp:
        #     logger.debug(f"JWT 令牌已过期 (显式检查): {token[:10]}...")
        #     return None

        # 3. 可以在这里添加其他业务逻辑相关的验证，例如检查 payload 中是否包含必要的字段 ('sub' 等)
        # if "sub" not in payload:
        #     logger.warning(f"解码后的 JWT payload 中缺少 'sub' 字段: {payload}")
        #     return None

        # 如果所有验证通过，返回解码后的 payload
        return payload
    except JWTError as e: # 捕获 jose 库抛出的所有 JWT 相关错误
        # JWTError 包括签名无效、令牌过期、格式错误等多种情况
        logger.debug(f"JWT 验证失败: {e} (Token: {token[:10]}...)") # 记录 JWT 验证失败的调试信息，不暴露完整 token
        return None # 返回 None 表示令牌无效
    except Exception as e: # 捕获解码过程中可能发生的其他意外错误
        logger.error(f"解码 token 时发生意外错误: {e}", exc_info=True) # 记录错误日志
        return None # 返回 None
