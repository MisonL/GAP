# -*- coding: utf-8 -*-
"""
API 请求处理中的错误处理辅助函数。
"""
import httpx     # 导入 HTTP 客户端库，用于处理 HTTP 异常
import json      # 导入 JSON 库，用于解析错误响应体
import logging   # 导入日志库
from typing import Optional, Dict, Any, Tuple # 导入类型提示

# 导入 APIKeyManager 类，用于标记 Key 状态
from gap.core.keys.manager import APIKeyManager # (新路径)

# 获取日志记录器实例
logger = logging.getLogger("my_logger")

# --- 错误处理辅助函数 ---

def _format_api_error(http_err: httpx.HTTPStatusError) -> Tuple[str, int]:
    """
    (内部辅助函数) 根据 httpx.HTTPStatusError 格式化 API 错误消息和状态码。
    尝试从响应体中解析更具体的错误信息。

    Args:
        http_err (httpx.HTTPStatusError): httpx 抛出的 HTTP 状态错误异常。

    Returns:
        Tuple[str, int]: 包含错误消息字符串和 HTTP 状态码的元组。
    """
    status_code = http_err.response.status_code # 获取 HTTP 状态码
    error_message = f"API 请求失败，状态码: {status_code}。" # 默认错误消息

    try:
        # 尝试解析响应体为 JSON
        error_detail = http_err.response.json()
        # 尝试提取 Google API 标准错误格式中的 message 字段
        if isinstance(error_detail, dict) and "error" in error_detail and "message" in error_detail["error"]:
            error_message = f"API 错误 (状态码 {status_code}): {error_detail['error']['message']}"
        else:
            # 如果不是标准格式，使用原始响应体作为错误信息的一部分
            error_message = f"API 请求失败，状态码: {status_code}。响应体: {http_err.response.text[:200]}" # 限制响应体长度
    except json.JSONDecodeError:
        # 如果响应体不是有效的 JSON，使用原始响应体文本
        error_message = f"API 请求失败，状态码: {status_code}。响应体: {http_err.response.text[:200]}" # 限制响应体长度
    except Exception as e:
        # 捕获解析过程中其他可能的错误
        logger.error(f"解析 API 错误响应体时发生意外错误: {e}", exc_info=True)
        error_message = f"API 请求失败，状态码: {status_code}，且无法解析错误详情。"

    return error_message, status_code

def _handle_429_daily_quota(http_error: httpx.HTTPStatusError, api_key: Optional[str], key_manager: APIKeyManager) -> bool:
    """
    (内部辅助函数) 处理 HTTP 429 错误，专门检查是否为每日配额耗尽。
    如果是每日配额耗尽，则调用 Key 管理器标记该 Key。

    Args:
        http_error (httpx.HTTPStatusError): 429 错误异常对象。
        api_key (Optional[str]): 当前使用的 API Key。
        key_manager (APIKeyManager): Key 管理器实例。

    Returns:
        bool: 如果确定是每日配额耗尽错误，返回 True；否则返回 False。
    """
    if not api_key: # 如果没有提供 api_key，无法标记，直接返回 False
        return False

    try:
        # 尝试解析 429 错误的 JSON 响应体
        error_detail = http_error.response.json()
        is_daily_quota_error = False # 初始化标志
        # 检查 Google API 标准错误结构中是否包含指示配额失败的详情
        if error_detail and "error" in error_detail and "details" in error_detail["error"]:
            for detail in error_detail["error"]["details"]:
                # 检查详情类型是否为 QuotaFailure
                if detail.get("@type") == "type.googleapis.com/google.rpc.QuotaFailure":
                    # 检查 quotaId 是否包含 "PerDay" 字样来判断是否为每日配额
                    quota_id = detail.get("quotaId", "")
                    if "PerDay" in quota_id:
                        is_daily_quota_error = True # 确认是每日配额错误
                        break # 找到后即可退出循环

        if is_daily_quota_error: # 如果确认是每日配额错误
            # 调用 Key 管理器的方法标记该 Key 当天已耗尽
            key_manager.mark_key_daily_exhausted(api_key)
            logger.warning(f"Key {api_key[:8]}... 因每日配额耗尽被标记为当天不可用。") # 记录警告日志
            return True # 返回 True 表示已处理每日配额错误

    except json.JSONDecodeError: # 处理 JSON 解析失败的情况
        logger.error(f"无法解析 429 错误的 JSON 响应体 (Key: {api_key[:8]}...)") # 记录错误
    except Exception as parse_e: # 处理解析过程中其他可能的异常
        logger.error(f"解析 429 错误详情时发生意外异常 (Key: {api_key[:8]}...): {parse_e}") # 记录错误

    return False # 如果不是每日配额错误或处理失败，返回 False

async def _handle_http_error_in_attempt(
    http_err: httpx.HTTPStatusError,
    current_api_key: Optional[str],
    key_manager: APIKeyManager,
    is_stream: bool, # 标记是否为流式请求 (用于日志)
    request_id: Optional[str] = None # 请求 ID (用于日志)
) -> Tuple[Dict[str, Any], bool]:
    """
    (内部辅助函数) 处理在单次 API 调用尝试 (`_attempt_api_call`) 中发生的 `httpx.HTTPStatusError`。
    根据 HTTP 状态码判断错误类型，格式化错误信息，并决定是否需要重试（通常意味着尝试其他 Key）。
    对于特定错误（如 429 每日配额、400 Key 无效、401/403），会调用 Key 管理器标记 Key 状态。

    Args:
        http_err (httpx.HTTPStatusError): 捕获到的 HTTP 状态错误异常。
        current_api_key (Optional[str]): 当前尝试使用的 API Key。
        key_manager (APIKeyManager): Key 管理器实例。
        is_stream (bool): 当前请求是否为流式请求。
        request_id (Optional[str]): 当前请求的 ID。

    Returns:
        Tuple[Dict[str, Any], bool]:
            - 第一个元素 (Dict): 包含格式化错误信息的字典 ('message', 'type', 'code')。
            - 第二个元素 (bool): 指示是否需要重试 (True 表示需要，False 表示不需要)。
    """
    # 格式化错误消息和状态码
    error_message, status_code = _format_api_error(http_err)
    # 记录包含状态码和 Key 前缀的错误日志
    logger.error(f"API HTTP 错误 ({'流式' if is_stream else '非流式'}, Key: {current_api_key[:8] if current_api_key else 'N/A'}, Request: {request_id}): {status_code} - {error_message}", exc_info=False) # exc_info=False 避免重复记录堆栈

    # 初始化错误信息字典和重试标志
    error_info: Dict[str, Any] = {
        "message": error_message,
        "type": "api_error", # 默认错误类型
        "code": status_code
    }
    needs_retry = False # 默认不需要重试

    # --- 根据 HTTP 状态码判断错误类型和是否需要重试 ---
    if status_code in [500, 503]: # 服务器内部错误或服务不可用
        error_info["type"] = "server_error" if status_code == 500 else "service_unavailable_error"
        needs_retry = True # 这些通常是临时性问题，需要重试 (尝试其他 Key 或稍后重试)
        logger.warning(f"HTTP 状态码 {status_code} 表示服务器临时错误，标记需要重试。")
        # 标记 Key 临时不可用
        if current_api_key:
            key_manager.mark_key_temporarily_unavailable(current_api_key, duration_seconds=60, issue_type=f"HTTP {status_code}")

    elif status_code == 429: # 请求过多 (速率限制或配额)
        error_info["type"] = "rate_limit_error"
        # 检查是否为每日配额耗尽
        if _handle_429_daily_quota(http_err, current_api_key, key_manager):
            needs_retry = True # 如果是每日配额耗尽，需要重试（尝试其他 Key）
            error_info["message"] = f"Key {current_api_key[:8] if current_api_key else 'N/A'} 每日配额耗尽，尝试其他 Key。"
        else:
             # 如果是普通的速率限制 (RPM/TPM)，通常不需要立即重试当前请求（因为是针对当前 Key 的限制）
             # Key 选择逻辑应该在下次选择时避开此 Key 一段时间
             needs_retry = False # 不需要外部重试循环立即尝试其他 Key
             logger.warning(f"HTTP 状态码 429 (非每日配额) 表示当前 Key 速率限制，标记无需重试。")
             # 仍然标记 Key 临时不可用，以便 Key 选择器避开
             if current_api_key:
                 key_manager.mark_key_temporarily_unavailable(current_api_key, duration_seconds=60, issue_type="Rate Limit (429)")

    elif status_code in [401, 403]: # 未授权或禁止访问
        error_info["type"] = "authentication_error" if status_code == 401 else "permission_error"
        needs_retry = False # 认证/权限问题通常是永久性的，不需要重试
        logger.warning(f"HTTP 状态码 {status_code} 表示认证/权限问题，标记无需重试。")
        # 标记 Key 临时不可用（可能需要较长时间，例如 5 分钟）
        if current_api_key:
            key_manager.mark_key_temporarily_unavailable(current_api_key, duration_seconds=300, issue_type=f"Auth/Permission ({status_code})")

    elif status_code == 400: # 错误请求
        error_info["type"] = "invalid_request_error"
        needs_retry = False # 通常是请求本身的问题，不需要重试
        # 检查是否为明确的 Key 无效错误
        if "API key not valid" in error_message:
             logger.warning(f"HTTP 状态码 400 (明确 Key 无效) 表示 Key 无效，标记无需重试。")
             # 标记 Key 临时不可用（可能需要较长时间）
             if current_api_key:
                 key_manager.mark_key_temporarily_unavailable(current_api_key, duration_seconds=300, issue_type="Invalid API Key (400)")
        else:
             logger.warning(f"HTTP 状态码 400 (非 Key 无效) 表示请求体问题，标记无需重试。")

    else: # 其他未明确处理的 4xx 或其他错误
        needs_retry = False # 默认不重试
        logger.warning(f"HTTP 状态码 {status_code} 表示其他错误，标记无需重试。")

    return error_info, needs_retry

async def _handle_api_call_exception(
    exc: Exception,
    current_api_key: Optional[str],
    key_manager: APIKeyManager,
    is_stream: bool,
    request_id: Optional[str] = None
) -> Tuple[Dict[str, Any], bool]:
    """
    (内部辅助函数) 统一处理在 `_attempt_api_call` 中捕获到的各类异常。
    根据异常类型调用不同的处理逻辑，格式化错误信息，并决定是否需要重试。

    Args:
        exc (Exception): 捕获到的异常对象。
        current_api_key (Optional[str]): 当前尝试使用的 API Key。
        key_manager (APIKeyManager): Key 管理器实例。
        is_stream (bool): 当前请求是否为流式请求。
        request_id (Optional[str]): 当前请求的 ID。

    Returns:
        Tuple[Dict[str, Any], bool]:
            - 第一个元素 (Dict): 包含格式化错误信息的字典 ('message', 'type', 'code')。
            - 第二个元素 (bool): 指示是否需要重试 (True 表示需要，False 表示不需要)。
    """
    needs_retry = False # 初始化重试标志
    error_info: Dict[str, Any] = { # 初始化默认错误信息
        "message": f"API 调用中发生意外异常: {exc}",
        "type": "internal_error",
        "code": 500 # 默认为 500 内部错误
    }

    if isinstance(exc, httpx.HTTPStatusError): # --- 处理 HTTP 状态错误 ---
        # 调用专门处理 HTTP 错误的函数
        error_info, needs_retry = await _handle_http_error_in_attempt(
            exc, current_api_key, key_manager, is_stream, request_id
        )
    elif isinstance(exc, httpx.TimeoutException): # --- 处理请求超时 ---
        error_message = f"请求超时 (Key: {current_api_key[:8] if current_api_key else 'N/A'}, Request: {request_id}): {exc}"
        logger.error(error_message) # 记录错误
        error_info["message"] = "请求 Gemini API 超时，请稍后重试。"
        error_info["type"] = "timeout_error"
        error_info["code"] = 504 # Gateway Timeout
        needs_retry = True # 超时通常是临时问题，需要重试
        # 标记 Key 临时不可用
        if current_api_key:
            key_manager.mark_key_temporarily_unavailable(current_api_key, duration_seconds=60, issue_type="Timeout")
    elif isinstance(exc, httpx.RequestError): # --- 处理其他网络请求错误 ---
        error_message = f"网络连接错误 (Key: {current_api_key[:8] if current_api_key else 'N/A'}, Request: {request_id}): {exc}"
        logger.error(error_message) # 记录错误
        error_info["message"] = "连接 Gemini API 时发生网络错误。"
        error_info["type"] = "connection_error"
        error_info["code"] = 503 # Service Unavailable
        needs_retry = True # 网络问题通常是临时的，需要重试
        # 标记 Key 临时不可用
        if current_api_key:
            key_manager.mark_key_temporarily_unavailable(current_api_key, duration_seconds=60, issue_type="Connection Error")
    else: # --- 处理其他所有未预料到的异常 ---
        error_message = f"API 调用中发生未知内部错误 (Key: {current_api_key[:8] if current_api_key else 'N/A'}, Request: {request_id}): {exc}"
        logger.error(error_message, exc_info=True) # 记录包含堆栈的错误日志
        error_info["message"] = "处理请求时发生意外的内部错误。"
        error_info["type"] = "internal_error"
        error_info["code"] = 500
        needs_retry = False # 未知内部错误通常不建议自动重试

    return error_info, needs_retry

# handle_gemini_error 函数的功能已被 _handle_api_call_exception 覆盖和细化，可以考虑移除
# def handle_gemini_error(e: Exception, api_key: Optional[str], key_manager: APIKeyManager) -> str: ...
