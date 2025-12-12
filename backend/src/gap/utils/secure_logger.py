# -*- coding: utf-8 -*-
"""
安全日志工具模块。
提供安全的日志记录功能，避免记录敏感信息如API密钥。
"""

import hashlib
import logging
import re
from functools import wraps
from typing import Any, Dict, Optional


def mask_api_key(api_key: str, mask_length: int = 8) -> str:
    """
    安全地遮蔽API密钥，返回可安全记录的标识。

    Args:
        api_key: 原始API密钥
        mask_length: 要显示的字符数，默认8个字符

    Returns:
        安全的密钥标识，格式：[前N字符]...[后4字符]
    """
    if not api_key or len(api_key) <= mask_length + 4:
        return "[INVALID_KEY]"

    # 取前N个字符和后4个字符
    prefix = api_key[:mask_length]
    suffix = api_key[-4:]
    return f"{prefix}...{suffix}"


def hash_key_for_logging(api_key: str) -> str:
    """
    为API密钥生成唯一的哈希标识，用于日志跟踪。

    Args:
        api_key: 原始API密钥

    Returns:
        密钥的SHA256哈希值前8位
    """
    if not api_key:
        return "[NO_KEY]"

    return hashlib.sha256(api_key.encode()).hexdigest()[:8]


def sanitize_log_data(data: Any, mask_keys: bool = True) -> Any:
    """
    清理日志数据，移除或遮蔽敏感信息。

    Args:
        data: 要清理的数据
        mask_keys: 是否遮蔽密钥相关的字段

    Returns:
        清理后的数据
    """
    if isinstance(data, str):
        # 遮蔽字符串中的API密钥模式
        if mask_keys:
            # 匹配可能的API密钥模式（字母数字组合，长度>=20）
            key_pattern = r"([a-zA-Z0-9]{20,})"
            return re.sub(key_pattern, lambda m: mask_api_key(m.group(1)), data)
        return data

    elif isinstance(data, dict):
        # 递归处理字典
        sanitized = {}
        for key, value in data.items():
            # 遮蔽包含敏感字段名的值
            if any(
                sensitive in key.lower()
                for sensitive in ["key", "token", "password", "secret"]
            ):
                sanitized[key] = (
                    mask_api_key(str(value)) if isinstance(value, str) else "[REDACTED]"
                )
            else:
                sanitized[key] = sanitize_log_data(value, mask_keys)
        return sanitized

    elif isinstance(data, list):
        # 递归处理列表
        return [sanitize_log_data(item, mask_keys) for item in data]

    else:
        return data


class SecureLogger:
    """安全日志记录器包装器"""

    def __init__(self, logger_name: str):
        self.logger = logging.getLogger(logger_name)
        self.logger_name = logger_name

    def _format_message(
        self, message: str, extra: Optional[Dict[str, Any]] = None
    ) -> str:
        """格式化日志消息，清理敏感信息"""
        if extra:
            extra = sanitize_log_data(extra, mask_keys=True)
        return sanitize_log_data(message, mask_keys=True)

    def debug(self, message: str, **kwargs):
        """安全调试日志"""
        sanitized_message = self._format_message(message, kwargs)
        self.logger.debug(sanitized_message)

    def info(self, message: str, **kwargs):
        """安全信息日志"""
        sanitized_message = self._format_message(message, kwargs)
        self.logger.info(sanitized_message)

    def warning(self, message: str, **kwargs):
        """安全警告日志"""
        sanitized_message = self._format_message(message, kwargs)
        self.logger.warning(sanitized_message)

    def error(self, message: str, **kwargs):
        """安全错误日志"""
        sanitized_message = self._format_message(message, kwargs)
        self.logger.error(sanitized_message)

    def critical(self, message: str, **kwargs):
        """安全严重错误日志"""
        sanitized_message = self._format_message(message, kwargs)
        self.logger.critical(sanitized_message)


def secure_logger(logger_name: str) -> SecureLogger:
    """创建安全日志记录器"""
    return SecureLogger(logger_name)


def secure_log_decorator(mask_key_param: str = "api_key"):
    """
    装饰器：自动清理函数调用中的敏感信息

    Args:
        mask_key_param: 需要遮蔽的参数名
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # 遮蔽指定参数
            if mask_key_param in kwargs:
                key_value = kwargs[mask_key_param]
                if isinstance(key_value, str):
                    kwargs[mask_key_param] = mask_api_key(key_value)

            # 调用原函数
            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                # 确保异常信息也不包含敏感数据
                error_msg = str(e)
                error_msg = sanitize_log_data(error_msg, mask_keys=True)
                raise Exception(error_msg) from e

        return wrapper

    return decorator


# 预定义的安全日志记录器
secure_main_logger = secure_logger("gap.main")
secure_auth_logger = secure_logger("gap.auth")
secure_key_logger = secure_logger("gap.keys")
secure_processing_logger = secure_logger("gap.processing")
secure_cache_logger = secure_logger("gap.cache")
secure_api_logger = secure_logger("gap.api")


# 安全日志上下文管理器
class SecureLogContext:
    """安全的日志上下文，在指定范围内应用安全的日志记录"""

    def __init__(self, logger: SecureLogger, context: Dict[str, Any]):
        self.logger = logger
        self.context = sanitize_log_data(context)

    def __enter__(self):
        # 可以在这里设置日志上下文
        return self.logger

    def __exit__(self, exc_type, exc_val, exc_tb):
        # 清理日志上下文
        pass


# 便捷函数
def log_request_start(
    request_id: str,
    request_type: str,
    model_name: Optional[str] = None,
    user_id: Optional[str] = None,
    **kwargs,
):
    """记录请求开始，自动遮蔽敏感信息"""
    message_parts = [f"开始处理请求 {request_id}"]

    if request_type:
        message_parts.append(f"类型: {request_type}")

    if model_name:
        message_parts.append(f"模型: {model_name}")

    if user_id:
        # 对用户ID进行哈希处理
        user_hash = (
            hash_key_for_logging(user_id) if len(user_id) > 10 else user_id[:3] + "..."
        )
        message_parts.append(f"用户: {user_hash}")

    message = " (".join(message_parts) + ")"
    secure_processing_logger.info(message, **kwargs)


def log_key_usage(key_id: str, action: str, **kwargs):
    """记录API密钥使用情况，使用安全的标识"""
    safe_key_id = mask_api_key(key_id, mask_length=6)
    message = f"Key {safe_key_id}: {action}"
    secure_key_logger.info(message, **kwargs)


def log_error_with_context(error: Exception, context: Optional[Dict[str, Any]] = None):
    """记录错误，清理敏感信息"""
    safe_context = sanitize_log_data(context or {})
    secure_main_logger.error(f"Error: {str(error)}", context=safe_context)


# 默认导出
__all__ = [
    "secure_logger",
    "SecureLogger",
    "mask_api_key",
    "hash_key_for_logging",
    "sanitize_log_data",
    "secure_log_decorator",
    "SecureLogContext",
    "secure_main_logger",
    "secure_auth_logger",
    "secure_key_logger",
    "secure_processing_logger",
    "secure_cache_logger",
    "secure_api_logger",
    "log_request_start",
    "log_key_usage",
    "log_error_with_context",
]
