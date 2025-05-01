# app/core/error_helpers.py
import httpx     # 用于发送异步 HTTP 请求（例如测试密钥有效性）
import json      # 用于处理 JSON 数据
import logging   # 用于应用程序的日志记录
from typing import Optional # 类型提示

# 导入 APIKeyManager 类，需要绝对路径
from app.core.key_manager_class import APIKeyManager

# 获取名为 'my_logger' 的日志记录器实例
logger = logging.getLogger("my_logger")

# --- 错误处理辅助函数 ---
def handle_gemini_error(e: Exception, api_key: Optional[str], key_manager: APIKeyManager) -> str:
    """


    """
    key_identifier = f"Key: {api_key[:10]}..." if api_key else "Key: N/A" # 用于日志记录的 Key 标识符（部分显示）
    error_message = f"发生未知错误 ({key_identifier}): {e}" # 设置默认错误消息

    if isinstance(e, httpx.HTTPStatusError):
        status_code = e.response.status_code # 获取 HTTP 状态码
        error_body = e.response.text # 获取响应体文本
        try:
            error_json = e.response.json() # 尝试解析 JSON 响应体
            api_error_message = error_json.get("error", {}).get("message", error_body) # 提取 API 错误消息
        except json.JSONDecodeError:
            api_error_message = error_body # 如果不是 JSON，使用原始文本

        error_message = f"API 错误 (状态码 {status_code}, {key_identifier}): {api_error_message}" # 格式化错误消息
        logger.error(error_message) # 使用 ERROR 级别记录 API 返回的错误

        if status_code in [401, 403, 500, 503] and api_key:
            logger.warning(f"由于 API 错误 (状态码 {status_code})，将移除无效或有问题的 Key: {api_key[:10]}...") # 由于 API 错误，将移除无效或有问题的 Key
            key_manager.remove_key(api_key) # 移除 Key
        elif status_code == 400 and "API key not valid" in api_error_message and api_key:
             logger.warning(f"API 报告 Key 无效 (400 Bad Request)，将移除 Key: {api_key[:10]}...") # API 报告 Key 无效，将移除 Key
             key_manager.remove_key(api_key) # 移除 Key

    elif isinstance(e, httpx.TimeoutException):
        error_message = f"请求超时 ({key_identifier}): {e}" # 格式化超时错误消息
        logger.error(error_message) # 记录错误
    elif isinstance(e, httpx.RequestError):
        error_message = f"网络连接错误 ({key_identifier}): {e}" # 格式化网络错误消息
        logger.error(error_message) # 记录错误
    else:
        logger.error(error_message, exc_info=True) # 记录完整错误信息和堆栈跟踪

    return error_message
