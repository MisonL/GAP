# app/api/request_processing.py
"""
核心请求处理逻辑，包括流式和非流式处理、上下文管理、错误处理等。
"""
import asyncio # 导入 asyncio 模块
import json # 导入 json 模块
import logging # 导入 logging 模块
import time # 导入 time 模块
import pytz # 导入 pytz 模块
from datetime import datetime # 导入 datetime
import random # 导入 random 模块 # 导入 random 模块
from typing import Literal, List, Tuple, Dict, Any, Optional, Union # 导入类型提示
from fastapi import HTTPException, Request, status # 导入 FastAPI 相关组件
from fastapi.responses import StreamingResponse # 导入流式响应对象
from collections import Counter, defaultdict # Counter 用于 IP 统计
import httpx # 导入 httpx 模块

# 导入模型定义
from app.api.models import ChatCompletionRequest, ChatCompletionResponse, ResponseMessage # ResponseMessage 用于保存上下文

# 导入核心模块的类和函数
from app.core.gemini import GeminiClient # 导入 GeminiClient 类
from app.core.response_wrapper import ResponseWrapper # 导入 ResponseWrapper 类
from app.core import context_store # 导入 context_store 模块
from app.core import db_utils # 导入 db_utils 以检查内存模式
from app.core.message_converter import convert_messages # 导入消息转换函数
# key_manager_instance 不再直接导入，将通过依赖注入传入
from app.core.key_manager_class import APIKeyManager # 导入类型
from app.core.error_helpers import handle_gemini_error # 导入错误处理函数
from app.core.request_helpers import get_client_ip, protect_from_abuse # 导入请求辅助函数

# 导入 API 辅助模块的函数
from app.api.request_utils import get_current_timestamps # 导入获取当前时间戳的函数
from app.api.token_utils import estimate_token_count, truncate_context # 导入 Token 辅助函数
from app.api.rate_limit_utils import check_rate_limits_and_update_counts, update_token_counts # 导入速率限制辅助函数
from app.api.tool_call_utils import process_tool_calls # 导入工具调用辅助函数

# 导入配置
from app import config # 导入根配置
from app.config import ( # 导入具体配置项
    DISABLE_SAFETY_FILTERING, # 是否禁用安全过滤
    MAX_REQUESTS_PER_MINUTE, # 每分钟最大请求数
    STREAM_SAVE_REPLY, # 新增：导入流式保存配置
    MAX_REQUESTS_PER_DAY_PER_IP, # 每个 IP 每天最大请求数
    safety_settings, # 标准安全设置
    safety_settings_g2 # G2 安全设置
)

# 导入跟踪相关
from app.core.tracking import (
    usage_data, usage_lock, RPM_WINDOW_SECONDS, TPM_WINDOW_SECONDS, # 使用数据、锁、RPM/TPM 窗口
    ip_daily_input_token_counts, ip_input_token_counts_lock # IP 每日输入 token 计数和锁
)

# 导入日志格式化函数
from app.handlers.log_config import format_log_message # 导入日志格式化函数

logger = logging.getLogger('my_logger') # 获取日志记录器实例

# --- Core Request Processing Function ---

# --- 辅助函数 ---

def _format_api_error(http_err: httpx.HTTPStatusError, api_key: Optional[str], key_manager: APIKeyManager) -> Dict[str, Any]:
    """
    根据 HTTPStatusError 格式化 API 错误信息。

    Args:
        http_err: httpx.HTTPStatusError 异常对象。
        api_key: 当前使用的 API Key。
        key_manager: APIKeyManager 实例。

    Returns:
        包含错误消息、类型和状态码的字典。
    """
    status_code = http_err.response.status_code
    error_type = "api_error"
    error_message = f"API 请求失败，状态码: {status_code}。请检查日志获取详情。"

    if status_code == 400:
        error_message = "请求无效或格式错误，请检查您的输入。"
        error_type = "invalid_request_error"
    elif status_code == 401:
        error_message = "API 密钥无效或认证失败。"
        error_type = "authentication_error"
    elif status_code == 403:
        error_message = "API 密钥无权访问所请求的资源。"
        error_type = "permission_error"
    elif status_code == 429:
        error_message = "请求频率过高或超出配额，请稍后重试。"
        error_type = "rate_limit_error"
        # 调用辅助函数处理每日配额耗尽情况
        _handle_429_daily_quota(http_err, api_key, key_manager)
    elif status_code == 500:
        error_message = "Gemini API 服务器内部错误，请稍后重试。"
        error_type = "server_error"
    elif status_code == 503:
        error_message = "Gemini API 服务暂时不可用，请稍后重试。"
        error_type = "service_unavailable_error"
    
    return {
        "message": error_message,
        "type": error_type,
        "code": status_code
    }


def _handle_429_daily_quota(http_error: httpx.HTTPStatusError, api_key: Optional[str], key_manager: APIKeyManager) -> bool:
    """
    处理 HTTP 429 错误，检查是否为每日配额耗尽，并标记相应的 Key。

    Args:
        http_error: httpx.HTTPStatusError 异常对象。
        api_key: 当前使用的 API Key。
        key_manager: APIKeyManager 实例。

    Returns:
        如果错误是每日配额耗尽且已处理，则返回 True，否则返回 False。
    """
    if not api_key: # 如果没有提供 API Key，则无法处理
        return False

    try:
        error_detail = http_error.response.json() # 获取 JSON 格式的错误详情
        is_daily_quota_error = False # 初始化标记
        if error_detail and "error" in error_detail and "details" in error_detail["error"]: # 检查结构
            for detail in error_detail["error"]["details"]: # 遍历详情列表
                if detail.get("@type") == "type.googleapis.com/google.rpc/QuotaFailure": # 检查类型
                    quota_id = detail.get("quotaId", "") # 获取 quotaId
                    if "PerDay" in quota_id: # 检查是否包含 "PerDay"
                        is_daily_quota_error = True # 标记为每日配额错误
                        break # 找到即停止

        if is_daily_quota_error: # 如果是每日配额错误
            key_manager.mark_key_daily_exhausted(api_key) # 标记 Key 为当天耗尽
            logger.warning(f"Key {api_key[:8]}... 因每日配额耗尽被标记为当天不可用。") # 记录日志
            return True # 返回 True 表示已处理

    except json.JSONDecodeError: # 捕获 JSON 解析错误
        logger.error(f"无法解析 429 错误的 JSON 响应体 (Key: {api_key[:8]}...)") # 无法解析 429 错误的 JSON 响应体
    except Exception as parse_e: # 捕获其他解析错误
        logger.error(f"解析 429 错误详情时发生意外异常 (Key: {api_key[:8]}...): {parse_e}") # 解析 429 错误详情时发生意外异常

    return False # 默认返回 False

async def _handle_http_error_in_attempt(
    http_err: httpx.HTTPStatusError,
    current_api_key: Optional[str],
    key_manager: APIKeyManager,
    is_stream: bool
) -> Tuple[Dict[str, Any], bool]:
    """
    处理 _attempt_api_call 中发生的 httpx.HTTPStatusError。

    Args:
        http_err: httpx.HTTPStatusError 异常对象。
        current_api_key: 当前使用的 API Key。
        key_manager: APIKeyManager 实例。
        is_stream: 是否为流式请求。

    Returns:
        Tuple: (error_info, needs_retry)
        error_info: 格式化的错误信息字典。
        needs_retry: 是否需要重试 (True 表示需要，False 表示不需要)。
    """
    logger.error(f"API HTTP 错误 ({'流式' if is_stream else '非流式'}, Key: {current_api_key[:8] if current_api_key else 'N/A'}): {http_err.response.status_code} - {http_err.response.text}", exc_info=False)
    error_info = _format_api_error(http_err, current_api_key, key_manager)
    needs_retry = False # 默认不重试

    # 对于 429 错误，检查是否为每日配额耗尽，如果是则需要重试
    if http_err.response.status_code == 429:
        if _handle_429_daily_quota(http_err, current_api_key, key_manager):
            # 如果是每日配额耗尽且已处理，则尝试下一个 Key
            needs_retry = True
            error_info["message"] = f"Key {current_api_key[:8] if current_api_key else 'N/A'} 每日配额耗尽" # 更新错误消息
        # 非每日配额的 429 错误，不需要重试 (needs_retry 保持 False)

    # 其他 HTTP 错误 (非 429)，不需要重试 (needs_retry 保持 False)

    return error_info, needs_retry

async def _handle_api_call_exception(
    exc: Exception,
    current_api_key: Optional[str],
    key_manager: APIKeyManager,
    is_stream: bool
) -> Tuple[Dict[str, Any], bool]:
    """
    处理 API 调用过程中发生的异常，格式化错误信息并判断是否需要重试。

    Args:
        exc: 发生的异常对象。
        current_api_key: 当前使用的 API Key。
        key_manager: APIKeyManager 实例。
        is_stream: 是否为流式请求。

    Returns:
        Tuple: (error_info, needs_retry)
        error_info: 格式化的错误信息字典。
        needs_retry: 是否需要重试 (True 表示需要，False 表示不需要)。
    """
    needs_retry = False
    error_info: Dict[str, Any] = {
        "message": f"API 调用中发生意外异常: {exc}",
        "type": "internal_error",
        "code": 500
    }

    if isinstance(exc, httpx.HTTPStatusError):
        # 将 HTTPStatusError 的处理委托给新的辅助函数
        error_info, needs_retry = await _handle_http_error_in_attempt(exc, current_api_key, key_manager, is_stream)
    else:
        # 非 HTTPStatusError，使用 handle_gemini_error 处理
        error_message = handle_gemini_error(exc, current_api_key, key_manager)
        logger.error(f"API 调用失败 ({'流式' if is_stream else '非流式'}, Key: {current_api_key[:8] if current_api_key else 'N/A'}): {error_message}", exc_info=True)
        error_info["message"] = error_message
        # 对于非 HTTP 错误，通常不重试，除非是特定的可重试错误类型（目前简化处理，不重试）
        needs_retry = False

    return error_info, needs_retry

async def _save_context_after_success(
    proxy_key: str,
    contents_to_send: List[Dict[str, Any]],
    model_reply_content: str,
    model_name: str,
    enable_context: bool,
    final_tool_calls: Optional[List[Dict[str, Any]]] = None
):
    """
    在 API 调用成功后保存上下文。

    Args:
        proxy_key: 原始代理 Key。
        contents_to_send: 发送到 API 的消息内容 (已截断)。
        model_reply_content: 模型返回的回复内容。
        model_name: 使用的模型名称。
        enable_context: 是否启用了上下文。
        final_tool_calls: 模型返回的工具调用 (可选)。
    """
    if not enable_context:
        logger.debug(f"Key {proxy_key[:8]}... 的上下文补全已禁用，跳过上下文保存。")
        return

    logger.debug(f"准备为 Key '{proxy_key[:8]}...' 保存上下文 (内存模式: {db_utils.IS_MEMORY_DB})")

    # 1. 构建模型回复部分
    model_reply_part = {"role": "model", "parts": [{"text": model_reply_content}]}
    # 如果有工具调用，也添加到模型回复中
    if final_tool_calls:
        model_reply_part["tool_calls"] = final_tool_calls

    # 2. 合并上下文
    final_contents_to_save = contents_to_send + [model_reply_part]

    # 3. 再次截断
    truncated_contents_to_save, still_over_limit_final = truncate_context(final_contents_to_save, model_name)

    # 4. 保存 (如果不超限)
    if not still_over_limit_final:
        try:
            await context_store.save_context(proxy_key, truncated_contents_to_save)
            logger.info(f"上下文保存成功 for Key {proxy_key[:8]}...")
        except Exception as e:
            logger.error(f"保存上下文失败 (Key: {proxy_key[:8]}...): {str(e)}")
    else:
        # 这种情况应该很少见，如果初始截断正确的话
        logger.error(f"上下文在添加回复并再次截断后仍然超限 (Key: {proxy_key[:8]}...). 上下文未保存。")

async def _handle_stream_end(
    response_id: str,
    assistant_message_yielded: bool,
    actual_finish_reason: str,
    safety_issue_detail_received: Optional[Dict[str, Any]]
):
    """
    处理流式响应结束时的逻辑，发送结束块或错误块。

    Args:
        response_id: 响应 ID。
        assistant_message_yielded: 是否已产生助手消息。
        actual_finish_reason: 实际完成原因。
        safety_issue_detail_received: 接收到的安全问题详情 (可选)。
    """
    if not assistant_message_yielded: # 如果没有产生任何助手消息
        if actual_finish_reason == "STOP":
            # 如果完成原因是 STOP 但没有内容，根据是否有安全问题发送不同错误块
            if safety_issue_detail_received:
                error_message_detail = f"模型因安全策略停止生成内容。详情: {safety_issue_detail_received}" # 提供更具体的安全提示
                logger.warning(f"流结束时未产生助手内容，完成原因是 STOP，但检测到安全问题。向客户端发送安全提示。详情: {safety_issue_detail_received}") # 记录安全提示日志
                error_code = "safety_block" # 特定错误代码
                error_type = "model_error" # 类型
            else:
                error_message_detail = f"模型返回 STOP 但未生成任何内容。可能是由于输入问题或模型内部错误。完成原因: {actual_finish_reason}"
                logger.error(f"流结束时未产生助手内容，但完成原因是 STOP。向客户端发送错误。") # 记录通用错误日志
                error_code = "empty_response" # 通用错误代码
                error_type = "model_error" # 类型

            error_payload = {
                "error": {
                    "message": error_message_detail,
                    "type": error_type,
                    "code": error_code
                }
            }
            yield f"data: {json.dumps(error_payload)}\n\n"
        else:
            # 对于其他 finish_reason (如 SAFETY, RECITATION 等)，发送正常的结束块
            logger.warning(f"流结束时未产生助手内容 (完成原因: {actual_finish_reason})。发送结束块。") # 流结束时未产生助手内容
            end_chunk = { # 构建结束块
                "id": response_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": "ignored", # 模型名称在此处不重要，客户端使用 chunk 中的模型名称
                "choices": [{"delta": {}, "index": 0, "finish_reason": actual_finish_reason}] # delta 为空
            }
            yield f"data: {json.dumps(end_chunk)}\n\n" # Yield 结束块
    else:
        # 如果已产生内容，发送一个只有 finish_reason 的结束块
        end_chunk = { # 构建结束块
            "id": response_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": "ignored", # 模型名称在此处不重要
            "choices": [{"delta": {}, "index": 0, "finish_reason": actual_finish_reason}]
        }
        yield f"data: {json.dumps(end_chunk)}\n\n" # Yield 结束块

    yield "data: [DONE]\n\n" # Yield DONE 标记


async def _attempt_api_call(
    chat_request: ChatCompletionRequest,
    contents: List[Dict[str, Any]],
    system_instruction: Optional[str],
    current_api_key: str,
    http_client: httpx.AsyncClient,
    http_request: Request,
    key_manager: APIKeyManager,
    model_name: str,
    limits: Optional[Dict[str, Any]],
    client_ip: str,
    today_date_str_pt: str,
    proxy_key: str,
    enable_context: bool,
    attempt: int,
    retry_attempts: int
) -> Tuple[Optional[Union[StreamingResponse, ChatCompletionResponse]], Optional[str], bool]:
    """
    尝试使用给定的 API Key 进行一次 API 调用。

    Args:
        chat_request: 聊天请求数据。
        contents: 准备发送到 API 的消息内容。
        system_instruction: 系统指令。
        current_api_key: 当前尝试使用的 API Key。
        http_client: httpx 异步客户端。
        http_request: FastAPI 请求对象。
        key_manager: APIKeyManager 实例。
        model_name: 请求的模型名称。
        limits: 模型的速率限制配置。
        client_ip: 客户端 IP 地址。
        today_date_str_pt: 当天日期字符串。
        proxy_key: 原始代理 Key。
        enable_context: 是否启用上下文。
        attempt: 当前尝试次数。
        retry_attempts: 总重试次数。

    Returns:
        Tuple: (response, last_error, needs_retry)
        response: 成功时的响应对象 (StreamingResponse 或 ChatCompletionResponse)
        last_error: 发生错误时的错误消息
        needs_retry: 是否需要重试 (True 表示需要，False 表示不需要)
    """
    last_error = None
    response = None
    needs_retry = False

    try:
        # 确定安全设置
        current_safety_settings = safety_settings_g2 if config.DISABLE_SAFETY_FILTERING or 'gemini-2.0-flash-exp' in chat_request.model else safety_settings # 根据配置和模型选择安全设置
        # 创建 GeminiClient 实例，传入共享的 http_client
        gemini_client_instance = GeminiClient(current_api_key, http_client) # 创建 GeminiClient 实例

        # --- Streaming vs Non-streaming ---
        if chat_request.stream: # 如果是流式请求
            # --- Streaming Handling ---
            async def stream_generator(): # 定义流式生成器
                # nonlocal last_error, current_api_key, model_name, client_ip, today_date_str_pt, limits, proxy_key, enable_context # 引用外部变量
                stream_error_occurred = False # 标记流错误是否发生
                assistant_message_yielded = False # 标记是否已产生助手消息
                full_reply_content = "" # 新增：用于累积回复内容
                usage_metadata_received = None # 存储接收到的使用情况元数据
                actual_finish_reason = "stop" # 存储实际完成原因
                safety_issue_detail_received = None # 新增：存储接收到的安全问题详情
                response_id = f"chatcmpl-{int(time.time() * 1000)}" # 更唯一的 ID

                try:
                    async for chunk in gemini_client_instance.stream_chat(chat_request, contents, current_safety_settings, system_instruction): # 异步迭代流式响应块
                        if isinstance(chunk, dict): # 如果是字典块
                            if '_usage_metadata' in chunk:
                                usage_metadata_received = chunk['_usage_metadata'] # 提取使用情况元数据
                                logger.debug(f"流接收到 usage metadata: {usage_metadata_received}") # 流接收到 usage metadata
                                continue # 继续处理下一个块
                            elif '_final_finish_reason' in chunk:
                                actual_finish_reason = chunk['_final_finish_reason'] # 提取最终完成原因
                                logger.debug(f"流接收到最终完成原因: {actual_finish_reason}") # 流接收到最终完成原因
                                continue # 继续处理下一个块
                            elif '_safety_issue' in chunk: # 新增：处理安全问题详情块
                                safety_issue_detail_received = chunk['_safety_issue'] # 存储安全问题详情
                                logger.warning(f"流接收到安全问题详情: {safety_issue_detail_received}") # 流接收到安全问题详情
                                continue # 继续处理下一个块
                            # 可以添加对其他元数据块的处理

                        # 检查是否是错误信息（例如内部处理错误）
                        elif isinstance(chunk, str) and chunk.startswith("[ERROR]"): # 如果是错误字符串
                            logger.error(f"流处理内部错误: {chunk}") # 流处理内部错误
                            # last_error = chunk # 记录错误供外部重试判断
                            stream_error_occurred = True # 标记流错误发生
                            break # 停止处理此流

                        # 格式化标准文本块
                        formatted_chunk = { # 构建格式化块
                            "id": response_id,
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": chat_request.model,
                            "choices": [{
                                "delta": {"role": "assistant", "content": chunk if isinstance(chunk, str) else ""}, # 确保 content 是字符串
                                "index": 0,
                                "finish_reason": None
                            }]
                        }
                        yield f"data: {json.dumps(formatted_chunk)}\n\n" # Yield 格式化块
                        if isinstance(chunk, str) and chunk: # 仅在有实际文本时标记
                            assistant_message_yielded = True # 标记已产生助手消息
                            full_reply_content += chunk # 累积回复内容

                    # --- 流结束处理 ---
                    if not stream_error_occurred: # 如果没有发生流错误
                        # 调用辅助函数处理流结束逻辑
                        async for end_chunk_data in _handle_stream_end(
                            response_id,
                            assistant_message_yielded,
                            actual_finish_reason,
                            safety_issue_detail_received
                        ):
                            yield end_chunk_data

                        # --- 处理 Token 计数（成功情况）---
                        if usage_metadata_received: # 如果接收到使用情况元数据
                            prompt_tokens = usage_metadata_received.get('promptTokenCount') # 获取 prompt_tokens
                            update_token_counts(current_api_key, model_name, limits, prompt_tokens, client_ip, today_date_str_pt) # 更新 token 计数
                        else:
                            logger.warning(f"Stream response successful but no usage metadata received (Key: {current_api_key[:8]}...). Token counts not updated.") # 流式响应成功但未接收到 usage metadata

                        # --- 成功流式传输后保存上下文（可配置）---
                        # 调用新的辅助函数保存上下文
                        await _save_context_after_success(
                            proxy_key=proxy_key,
                            contents_to_send=contents, # 原始发送的内容
                            model_reply_content=full_reply_content, # 累积的回复内容
                            model_name=chat_request.model,
                            enable_context=enable_context,
                            final_tool_calls=None # 流式通常没有工具调用在流中返回
                        )

                except asyncio.CancelledError: # 捕获 asyncio.CancelledError
                    logger.info(f"客户端连接已中断 (IP: {client_ip})") # 客户端连接已中断
                    # No need to yield [DONE]
                except httpx.HTTPStatusError as http_err: # 捕获 stream_chat 可能抛出的 HTTP 错误
                    logger.error(f"流式 API 错误: {http_err.response.status_code} - {http_err.response.text}", exc_info=False) # 记录错误
                    stream_error_occurred = True # 标记流错误发生

                    # 使用辅助函数格式化错误信息
                    error_info = _format_api_error(http_err, current_api_key, key_manager)

                    # 发送错误信息给客户端并结束流
                    yield f"data: {json.dumps({'error': error_info})}\n\n" # Yield 错误信息
                    yield "data: [DONE]\n\n" # Yield DONE 标记
                    return # 中断生成器

                except Exception as stream_e: # 捕获流处理中捕获到的意外异常
                    # last_error = f"流处理中捕获到意外异常: {stream_e}" # 设置最后错误
                    logger.error(f"流处理中捕获到意外异常: {stream_e}", exc_info=True) # 记录错误
                    stream_error_occurred = True # 标记流错误发生

            response = StreamingResponse(stream_generator(), media_type="text/event-stream") # 创建 StreamingResponse
            # 对于流式响应，我们假设它成功启动，直接返回。错误处理在生成器内部进行。
            # 如果 stream_generator 内部发生错误导致无法生成数据，客户端会收到中断的流。
            # 重试逻辑主要处理 API 调用本身的失败（例如密钥无效、网络问题）。
            # 如果流成功启动但中途因模型原因（如安全）中断，这不算是需要重试的错误。
            logger.info(f"流式响应已启动 (Key: {current_api_key[:8]})") # 流式响应已启动
            return response, None, False # 流式成功，不重试

        else: # 如果是非流式请求
            # --- Non-streaming Handling ---
            async def run_gemini_completion(): # 定义运行 Gemini 补全的异步函数
                return await gemini_client_instance.complete_chat(chat_request, contents, current_safety_settings, system_instruction) # 运行 Gemini 补全

            async def check_client_disconnect(): # 定义检查客户端断开连接的异步函数
                while True:
                    if await http_request.is_disconnected(): # 检查是否断开连接
                        logger.warning(f"客户端连接中断 detected (IP: {client_ip})") # 客户端连接中断
                        return True # 返回 True
                    await asyncio.sleep(0.5) # 等待 0.5 秒

            gemini_task = asyncio.create_task(run_gemini_completion()) # 创建 Gemini任务
            disconnect_task = asyncio.create_task(check_client_disconnect()) # 创建断开连接检查任务

            done, pending = await asyncio.wait( # 等待任务完成
                [gemini_task, disconnect_task], return_when=asyncio.FIRST_COMPLETED
            )

            if disconnect_task in done: # 如果断开连接任务先完成
                gemini_task.cancel() # 取消 Gemini 任务
                try: await gemini_task
                except asyncio.CancelledError: logger.info("非流式 API 任务已成功取消") # 非流式 API 任务已成功取消
                logger.error(f"客户端连接中断 (IP: {client_ip})，终止请求处理。") # 客户端连接中断，终止请求处理
                return None, "客户端连接中断", False # 客户端中断，不重试

            # Gemini 任务完成
            disconnect_task.cancel() # 取消断开连接检查任务
            try: await disconnect_task
            except asyncio.CancelledError: pass

            if gemini_task.exception(): # 如果 Gemini 任务抛出异常
                # 如果 Gemini 任务本身抛出异常（例如 API 调用失败）
                exc = gemini_task.exception() # 获取异常

                # 检查是否为 HTTPStatusError
                if isinstance(exc, httpx.HTTPStatusError):
                    # 将 HTTPStatusError 的处理委托给新的辅助函数
                    error_info, needs_retry = await _handle_http_error_in_attempt(exc, current_api_key, key_manager, False) # 非流式请求，is_stream=False
                    return None, error_info['message'], needs_retry # 返回错误信息和是否重试
                else:
                    # 非 HTTPStatusError，使用 handle_gemini_error 处理
                    error_message = handle_gemini_error(exc, current_api_key, key_manager)
                    logger.error(f"非流式 API 调用失败 (Key: {current_api_key[:8] if current_api_key else 'N/A'}): {error_message}", exc_info=True)
                    return None, error_message, False # 不重试

            else: # Gemini 任务成功完成
                result = gemini_task.result() # 获取结果
                response_wrapper = ResponseWrapper(result) # 创建 ResponseWrapper 实例

                # --- 处理 Token 计数（成功情况）---
                prompt_tokens = response_wrapper.get_prompt_token_count() # 获取 prompt_tokens
                completion_tokens = response_wrapper.get_completion_token_count() # 获取 completion_tokens
                update_token_counts(current_api_key, model_name, limits, prompt_tokens, client_ip, today_date_str_pt, completion_tokens) # 更新 token 计数

                # --- 处理工具调用 ---
                tool_calls = response_wrapper.get_tool_calls() # 获取工具调用
                final_tool_calls = None
                if tool_calls:
                    logger.info(f"模型返回工具调用: {tool_calls}") # 记录工具调用
                    # 调用辅助函数处理工具调用
                    tool_call_results = await process_tool_calls(tool_calls, proxy_key, chat_request.model, enable_context) # 处理工具调用
                    # 将工具调用结果添加到 contents 中，以便下次请求使用
                    contents_with_tool_results = contents + response_wrapper.get_message_parts() + tool_call_results # 合并内容和工具调用结果
                    # 再次尝试 API 调用，将工具调用结果发送给模型
                    logger.info(f"发送工具调用结果给模型 (Key: {current_api_key[:8]}...)") # 发送工具调用结果给模型
                    # 在这里递归调用 _attempt_api_call 可能会导致无限循环，更好的方式是在 process_request 中处理重试和工具调用链
                    # 暂时简化处理，只返回工具调用结果，不自动进行下一步 API 调用
                    # TODO: 实现完整的工具调用链处理逻辑
                    # For now, just return the tool calls as part of the response message
                    final_tool_calls = tool_calls # 将原始工具调用添加到最终响应中

                # --- 成功非流式传输后保存上下文 ---
                # 调用新的辅助函数保存上下文
                await _save_context_after_success(
                    proxy_key=proxy_key,
                    contents_to_send=contents, # 原始发送的内容
                    model_reply_content=response_wrapper.get_text(), # 模型回复内容
                    model_name=chat_request.model,
                    enable_context=enable_context,
                    final_tool_calls=final_tool_calls # 包含工具调用
                )

                # --- 构建并返回响应 ---
                response_message = ResponseMessage(
                    role="assistant",
                    content=response_wrapper.get_text(),
                    tool_calls=final_tool_calls # 包含工具调用
                )
                response = ChatCompletionResponse(
                    id=f"chatcmpl-{int(time.time() * 1000)}", # 生成一个唯一的 ID
                    object="chat.completion",
                    created=int(time.time()),
                    model=chat_request.model,
                    choices=[{
                        "index": 0,
                        "message": response_message,
                        "finish_reason": response_wrapper.get_finish_reason()
                    }],
                    usage={
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": prompt_tokens + completion_tokens
                    } if prompt_tokens is not None and completion_tokens is not None else None # 仅在获取到 token 数时包含 usage
                )
                logger.info(f"非流式响应成功 (Key: {current_api_key[:8]})") # 非流式响应成功
                return response, None, False # 非流式成功，不重试

    except Exception as e: # 捕获 API 调用过程中的任何其他异常
        # 使用辅助函数处理其他异常
        error_info, needs_retry = await _handle_api_call_exception(e, current_api_key, key_manager, chat_request.stream)
        last_error = error_info['message'] # 设置最后错误
        # needs_retry 由 _handle_api_call_exception 决定

    return response, last_error, needs_retry # 返回结果、错误和是否重试


async def process_request(
    chat_request: ChatCompletionRequest,
    http_request: Request,
    key_manager: APIKeyManager,
    http_client: httpx.AsyncClient # 接收共享的 http_client
) -> Union[StreamingResponse, ChatCompletionResponse, Dict[str, Any]]:
    """
    处理传入的聊天请求。

    Args:
        chat_request: 聊天请求数据。
        http_request: FastAPI 请求对象。
        key_manager: APIKeyManager 实例。
        http_client: httpx 异步客户端。

    Returns:
        StreamingResponse, ChatCompletionResponse 或包含错误信息的字典。
    """
    client_ip = get_client_ip(http_request) # 获取客户端 IP
    logger.info(f"收到来自 IP {client_ip} 的请求") # 记录收到的请求

    # 1. 保护免受滥用
    abuse_check_error = protect_from_abuse(client_ip) # 检查滥用
    if abuse_check_error: # 如果存在滥用错误
        logger.warning(f"IP {client_ip} 触发滥用保护: {abuse_check_error}") # 记录滥用警告
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail={"error": {"message": abuse_check_error, "type": "rate_limit_error", "code": "abuse_protection"}}) # 抛出 429 异常

    proxy_key = chat_request.api_key # 获取请求中的代理 Key
    if not proxy_key: # 如果没有提供代理 Key
        logger.warning(f"来自 IP {client_ip} 的请求未提供代理 Key") # 记录警告
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"error": {"message": "请求中未提供代理 Key", "type": "invalid_request_error", "code": "missing_api_key"}}) # 抛出 400 异常

    # 2. 验证代理 Key 并获取配置
    key_config = key_manager.get_key_config(proxy_key) # 获取 Key 配置
    if not key_config: # 如果 Key 无效
        logger.warning(f"来自 IP {client_ip} 的请求使用了无效的代理 Key: {proxy_key[:8]}...") # 记录警告
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"error": {"message": "无效的代理 Key", "type": "authentication_error", "code": "invalid_api_key"}}) # 抛出 401 异常

    # 检查 Key 是否过期
    if key_config.get("expiry_date") and datetime.now(pytz.utc) > datetime.fromisoformat(key_config["expiry_date"]).replace(tzinfo=pytz.utc): # 检查过期日期
         logger.warning(f"来自 IP {client_ip} 的请求使用了过期的代理 Key: {proxy_key[:8]}...") # 记录警告
         raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"error": {"message": "代理 Key 已过期", "type": "authentication_error", "code": "expired_api_key"}}) # 抛出 401 异常

    # 检查 Key 是否被禁用
    if key_config.get("disabled", False): # 检查是否被禁用
        logger.warning(f"来自 IP {client_ip} 的请求使用了被禁用的代理 Key: {proxy_key[:8]}...") # 记录警告
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": {"message": "代理 Key 已被禁用", "type": "permission_error", "code": "key_disabled"}}) # 抛出 403 异常

    # 检查 Key 的每日配额是否耗尽
    if key_manager.is_key_daily_exhausted(proxy_key): # 检查每日配额是否耗尽
        logger.warning(f"来自 IP {client_ip} 的请求使用了每日配额已耗尽的代理 Key: {proxy_key[:8]}...") # 记录警告
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail={"error": {"message": "代理 Key 每日配额已耗尽，请明天再试", "type": "rate_limit_error", "code": "daily_quota_exhausted"}}) # 抛出 429 异常

    model_name = chat_request.model # 获取请求中的模型名称
    limits = config.MODEL_LIMITS.get(model_name) # 获取模型的速率限制配置

    # 3. 检查并更新速率限制和 Token 计数
    current_minute, today_date_str_pt = get_current_timestamps() # 获取当前分钟和日期
    rate_limit_error = check_rate_limits_and_update_counts(
        proxy_key, client_ip, model_name, limits, current_minute, today_date_str_pt
    ) # 检查并更新速率限制和计数

    if rate_limit_error: # 如果存在速率限制错误
        logger.warning(f"来自 IP {client_ip} 的请求触发速率限制 (Key: {proxy_key[:8]}...): {rate_limit_error}") # 记录警告
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail={"error": {"message": rate_limit_error, "type": "rate_limit_error", "code": "rate_limited"}}) # 抛出 429 异常

    # 4. 上下文管理
    enable_context = key_config.get("enable_context", False) # 从 Key 配置中获取是否启用上下文
    context_messages = [] # 初始化上下文消息列表
    if enable_context: # 如果启用了上下文
        logger.debug(f"Key {proxy_key[:8]}... 启用了上下文补全。尝试加载上下文...") # 记录日志
        try:
            # 根据是否为内存数据库选择加载方式
            if db_utils.IS_MEMORY_DB: # 如果是内存数据库
                 context_messages = context_store.load_context_from_memory(proxy_key) # 从内存加载上下文
            else: # 如果是文件数据库
                 context_messages = await context_store.load_context(proxy_key) # 从文件加载上下文
            logger.debug(f"为 Key {proxy_key[:8]}... 加载到 {len(context_messages)} 条上下文消息。") # 记录加载到的上下文消息数量
        except Exception as e: # 捕获加载上下文时的异常
            logger.error(f"加载上下文失败 (Key: {proxy_key[:8]}...): {str(e)}") # 记录错误
            # 加载失败不应中断请求，继续处理当前请求消息

    # 5. 合并上下文和当前请求消息
    # 将当前请求的消息添加到上下文消息中
    all_messages = context_messages + chat_request.messages # 合并上下文和当前消息

    # 6. 转换消息格式并截断
    # 将消息转换为 Gemini API 所需的格式
    contents_to_send = convert_messages(all_messages) # 转换消息格式

    # 估算 Token 数量并截断上下文
    truncated_contents, is_over_limit = truncate_context(contents_to_send, model_name) # 截断上下文

    if is_over_limit: # 如果截断后仍然超限
        logger.warning(f"为 Key {proxy_key[:8]}... 截断上下文后仍然超限。发送空消息列表。") # 记录警告
        # 这种情况下，发送一个只包含用户最新消息的请求，或者直接返回错误
        # 这里选择发送一个只包含用户最新消息的请求（即 chat_request.messages 转换后的内容）
        # 重新转换并截断仅包含用户最新消息的内容
        user_only_contents = convert_messages(chat_request.messages) # 仅转换用户消息
        truncated_contents, is_over_limit_user_only = truncate_context(user_only_contents, model_name) # 再次截断
        if is_over_limit_user_only:
             # 如果用户消息本身就超限，返回错误
             error_message = f"您的请求消息 ({estimate_token_count(user_only_contents, model_name)} tokens) 超过了模型 {model_name} 的最大输入限制 ({limits.get('max_input_tokens')} tokens)。" # 错误消息
             logger.warning(f"来自 IP {client_ip} 的请求消息本身超限 (Key: {proxy_key[:8]}...): {error_message}") # 记录警告
             raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"error": {"message": error_message, "type": "invalid_request_error", "code": "context_length_exceeded"}}) # 抛出 400 异常
        else:
             # 用户消息未超限，使用用户消息作为发送内容
             contents_to_send = truncated_contents # 更新发送内容为仅用户消息
             logger.warning(f"为 Key {proxy_key[:8]}... 截断上下文后仍然超限，但用户消息未超限。仅发送用户消息。") # 记录警告
    else:
        contents_to_send = truncated_contents # 使用截断后的内容

    # 7. 选择最佳 API Key 并尝试调用
    # 在这里，我们不再直接选择 Key，而是在尝试调用函数中处理 Key 的选择和重试
    # 循环尝试 Key 直到成功或达到最大重试次数
    max_attempts = key_manager.get_total_keys() # 最大尝试次数等于可用 Key 的数量
    last_error = None # 初始化最后错误
    response = None # 初始化响应

    for attempt in range(max_attempts): # 循环尝试
        current_api_key = key_manager.select_best_key(chat_request.model, config.MODEL_LIMITS) # 选择最佳 Key
        if not current_api_key: # 如果没有可用 Key
            error_message = "当前没有可用的 API 密钥，请稍后再试或联系管理员。" # 错误消息
            logger.error(f"来自 IP {client_ip} 的请求没有可用 Key (Proxy Key: {proxy_key[:8]}...): {error_message}") # 记录错误
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail={"error": {"message": error_message, "type": "server_error", "code": "no_available_keys"}}) # 抛出 503 异常

        logger.debug(f"尝试使用 Key {current_api_key[:8]}... 进行 API 调用 (尝试 {attempt + 1}/{max_attempts})") # 记录尝试日志

        # 尝试进行 API 调用
        response, last_error, needs_retry = await _attempt_api_call(
            chat_request=chat_request,
            contents=contents_to_send,
            system_instruction=chat_request.system_instruction,
            current_api_key=current_api_key,
            http_client=http_client,
            http_request=http_request,
            key_manager=key_manager,
            model_name=model_name,
            limits=limits,
            client_ip=client_ip,
            today_date_str_pt=today_date_str_pt,
            proxy_key=proxy_key,
            enable_context=enable_context,
            attempt=attempt,
            retry_attempts=max_attempts # 将总尝试次数作为重试次数参数
        )

        if response: # 如果成功获取到响应
            return response # 返回响应
        elif not needs_retry: # 如果不需要重试（例如，非 429 错误或每日配额已处理）
            break # 停止尝试

        # 如果需要重试，等待一小段时间再尝试下一个 Key
        await asyncio.sleep(random.uniform(0.5, 2.0)) # 随机等待 0.5 到 2 秒

    # 如果所有尝试都失败
    final_error_message = last_error if last_error else "所有 API 密钥尝试均失败，请稍后再试或联系管理员。" # 最终错误消息
    logger.error(f"来自 IP {client_ip} 的请求所有 API 尝试均失败 (Proxy Key: {proxy_key[:8]}...): {final_error_message}") # 记录错误

    # 根据最后一次错误的状态码决定返回的 HTTP 状态码
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR # 默认内部错误
    error_type = "server_error" # 默认错误类型
    error_code = "api_call_failed" # 默认错误代码

    # 尝试从 last_error 中解析状态码和错误类型（如果可能）
    if isinstance(last_error, str):
        # 简单的文本解析，可能需要更健壮的错误对象传递
        if "每日配额耗尽" in last_error:
            status_code = status.HTTP_429_TOO_MANY_REQUESTS
            error_type = "rate_limit_error"
            error_code = "daily_quota_exhausted"
        elif "请求频率过高" in last_error:
             status_code = status.HTTP_429_TOO_MANY_REQUESTS
             error_type = "rate_limit_error"
             error_code = "rate_limited"
        elif "无效的代理 Key" in last_error or "API 密钥无效" in last_error:
             status_code = status.HTTP_401_UNAUTHORIZED
             error_type = "authentication_error"
             error_code = "invalid_api_key"
        elif "无权访问" in last_error or "已被禁用" in last_error:
             status_code = status.HTTP_403_FORBIDDEN
             error_type = "permission_error"
             error_code = "permission_denied"
        elif "请求无效" in last_error or "格式错误" in last_error or "超限" in last_error:
             status_code = status.HTTP_400_BAD_REQUEST
             error_type = "invalid_request_error"
             error_code = "invalid_request"
        elif "服务暂时不可用" in last_error or "没有可用 Key" in last_error:
             status_code = status.HTTP_503_SERVICE_UNAVAILABLE
             error_type = "service_unavailable_error"
             error_code = "service_unavailable"

    raise HTTPException(status_code=status_code, detail={"error": {"message": final_error_message, "type": error_type, "code": error_code}}) # 抛出异常
