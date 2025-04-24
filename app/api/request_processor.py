# -*- coding: utf-8 -*-
"""
核心请求处理逻辑，包括流式和非流式处理、上下文管理（待实现）、错误处理等。
Core request processing logic, including streaming and non-streaming handling, context management (to be implemented), error handling, etc.
"""
import asyncio # 导入 asyncio 模块 (Import asyncio module)
import json # 导入 json 模块 (Import json module)
import logging # 导入 logging 模块 (Import logging module)
import time # 导入 time 模块 (Import time module)
import pytz # 导入 pytz 模块 (Import pytz module)
from datetime import datetime # 导入 datetime (Import datetime)
from typing import Literal, List, Tuple, Dict, Any, Optional, Union # 导入类型提示 (Import type hints)
from fastapi import HTTPException, Request, status # 导入 FastAPI 相关组件 (Import FastAPI related components)
from fastapi.responses import StreamingResponse # 导入流式响应对象 (Import StreamingResponse object)
from collections import Counter, defaultdict # Counter 用于 IP 统计 (Counter used for IP statistics)
import httpx # 导入 httpx 模块 (Import httpx module)

# 相对导入
# Relative imports
from .models import ChatCompletionRequest, ChatCompletionResponse, ResponseMessage # ResponseMessage 用于保存上下文 (ResponseMessage used for saving context)
from ..core.gemini import GeminiClient # 导入 GeminiClient 类 (Import GeminiClient class)
from ..core.response_wrapper import ResponseWrapper # 导入 ResponseWrapper 类 (Import ResponseWrapper class)
# 导入上下文存储和请求工具
# Import context storage and request utilities
from ..core import context_store # 导入 context_store 模块 (Import context_store module)
from ..core import db_utils # 导入 db_utils 以检查内存模式 (Import db_utils to check memory mode)
from .request_utils import get_client_ip, get_current_timestamps, estimate_token_count, truncate_context, process_tool_calls, check_rate_limits_and_update_counts, update_token_counts # 导入新的工具函数, 添加 process_tool_calls, check_rate_limits_and_update_counts 和 update_token_counts (Import new utility functions, added process_tool_calls, check_rate_limits_and_update_counts, and update_token_counts)
from ..core.message_converter import convert_messages # 导入消息转换函数 (Import message conversion function)
from ..core.utils import handle_gemini_error, protect_from_abuse # 移除 StreamProcessingError (Removed StreamProcessingError)
from ..core.utils import key_manager_instance as key_manager # 导入共享实例 (Import shared instance)
from .. import config # 导入根配置 (Import root config)
from ..config import ( # 导入具体配置项 (Import specific configuration items)
    DISABLE_SAFETY_FILTERING, # 是否禁用安全过滤 (Whether safety filtering is disabled)
    MAX_REQUESTS_PER_MINUTE, # 每分钟最大请求数 (Maximum requests per minute)
    STREAM_SAVE_REPLY, # 新增：导入流式保存配置 (New: Import streaming save configuration)
    MAX_REQUESTS_PER_DAY_PER_IP, # 每个 IP 每天最大请求数 (Maximum requests per day per IP)
    safety_settings, # 标准安全设置 (Standard safety settings)
    safety_settings_g2 # G2 安全设置 (G2 safety settings)
)
from ..core.tracking import ( # 导入跟踪相关 (Import tracking related)
    usage_data, usage_lock, RPM_WINDOW_SECONDS, TPM_WINDOW_SECONDS, # 使用数据、锁、RPM/TPM 窗口 (Usage data, locks, RPM/TPM windows)
    ip_daily_input_token_counts, ip_input_token_counts_lock # IP 每日输入 token 计数和锁 (IP daily input token counts and lock)
)
from ..handlers.log_config import format_log_message # 导入日志格式化函数 (Import log formatting function)

logger = logging.getLogger('my_logger') # 获取日志记录器实例 (Get logger instance)

# --- 核心请求处理函数 ---
# --- Core Request Processing Function ---

async def process_request(
    chat_request: ChatCompletionRequest,
    http_request: Request,
    request_type: Literal['stream', 'non-stream'],
    proxy_key: str # 新增参数，由认证依赖注入 (New parameter, injected by authentication dependency)
) -> Optional[Union[StreamingResponse, ChatCompletionResponse]]:
    """
    聊天补全（流式和非流式）的核心请求处理函数。
    包括密钥选择、速率限制检查、API 调用尝试和响应处理。
    未来将加入上下文管理逻辑。
    Core request processing function for chat completions (streaming and non-streaming).
    Includes key selection, rate limit checking, API call attempts, and response handling.
    Context management logic will be added in the future.

    Args:
        chat_request: 包含聊天请求数据的 Pydantic 模型。Pydantic model containing chat request data.
        http_request: FastAPI Request 对象，用于获取 IP 和检查断开连接。FastAPI Request object, used to get IP and check for disconnects.
        request_type: 'stream' 或 'non-stream'。'stream' or 'non-stream'.
        proxy_key: 验证通过的代理 Key。The validated proxy key.

    Returns:
        流式请求返回 StreamingResponse，
        Streaming requests return StreamingResponse,
        非流式请求返回 ChatCompletionResponse，
        non-streaming requests return ChatCompletionResponse,
        如果客户端断开连接或早期发生不可重试的错误，则返回 None。
        returns None if the client disconnects or an early non-retryable error occurs.

    Raises:
        HTTPException: For user errors (e.g., bad input) or final processing errors.
    """
    # --- 获取客户端 IP 和时间戳 ---
    # --- Get Client IP and Timestamps ---
    client_ip = get_client_ip(http_request) # 获取客户端 IP (Get client IP)
    cst_time_str, today_date_str_pt = get_current_timestamps() # 获取当前时间戳 (Get current timestamps)

    # --- 记录请求入口日志 ---
    # --- Log Request Entry ---
    logger.info(f"处理来自 IP: {client_ip} 的请求 ({request_type})，模型: {chat_request.model}，时间: {cst_time_str}") # Log request entry

    # --- 防滥用保护 ---
    # --- Abuse Protection ---
    try:
        protect_from_abuse(http_request, MAX_REQUESTS_PER_MINUTE, MAX_REQUESTS_PER_DAY_PER_IP) # 执行防滥用检查 (Perform abuse protection check)
    except HTTPException as e:
        logger.warning(f"IP {client_ip} 的请求被阻止 (防滥用): {e.detail}") # Log blocked request
        raise e # 重新抛出防滥用异常 (Re-raise abuse protection exception)

    if not chat_request.messages: # 检查消息列表是否为空 (Check if message list is empty)
        logger.warning(f"Request from IP: {client_ip} (Key: {proxy_key[:8]}...) has empty messages list") # Log warning for empty message list
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="消息列表不能为空") # 引发 400 异常 (Raise 400 exception)

    # --- 模型列表检查 (如果需要) ---
    # --- Model List Check (if needed) ---
    # 保持在 endpoints.py 中，因为它更像是路由级别的检查
    # Kept in endpoints.py as it's more of a route-level check
    # 此处假设模型已验证
    # Assume model is already validated here

    # --- 上下文管理 ---
    # --- Context Management ---
    # 1. 加载历史上下文
    # 1. Load historical context
    history_contents: Optional[List[Dict[str, Any]]] = await context_store.load_context(proxy_key) # 添加 await (Added await) # 加载历史上下文 (Load historical context)
    logger.info(f"Loaded {len(history_contents) if history_contents else 0} historical messages for Key {proxy_key[:8]}...") # Log number of historical messages loaded

    # 2. 转换当前请求中的新消息
    # 2. Convert new messages in the current request
    conversion_result = convert_messages(chat_request.messages, use_system_prompt=True) # 转换消息 (Convert messages)
    if isinstance(conversion_result, list): # 转换错误 (Conversion error)
        error_msg = "; ".join(conversion_result) # 拼接错误消息 (Join error messages)
        logger.error(f"消息转换失败 (Key: {proxy_key[:8]}...): {error_msg}") # 记录转换失败错误 (Log conversion failure error)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"消息转换失败: {error_msg}") # 引发 400 异常 (Raise 400 exception)
    new_contents, system_instruction = conversion_result # system_instruction 仅来自当前请求 (system_instruction only comes from the current request)

    # 3. 合并历史记录和新消息
    # 3. Merge history and new messages
    merged_contents = (history_contents or []) + new_contents # 合并历史和新内容 (Merge history and new contents)
    if not merged_contents: # 如果合并后内容为空 (If merged content is empty)
         logger.error(f"Merged message list is empty (Key: {proxy_key[:8]}...)") # Log empty merged list
         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot process empty message list") # 引发 400 异常 (Raise 400 exception)

    # 4. 在发送到 API 之前截断合并后的上下文
    # 4. Truncate the merged context before sending to the API
    contents_to_send, is_over_limit_after_truncate = truncate_context(merged_contents, chat_request.model) # 截断上下文 (Truncate context)

    # 处理截断后仍超限的情况（例如单个长消息）
    # Handle case where it's still over limit after truncation (e.g., a single long message)
    if is_over_limit_after_truncate:
         logger.error(f"Context exceeds token limit for model {chat_request.model} even after truncation (Key: {proxy_key[:8]}...)") # Log context exceeding limit after truncation
         raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=f"Request content exceeds processing capacity for model {chat_request.model}. Please shorten the input.") # 引发 413 异常 (Raise 413 exception)

    # 处理截断后列表为空的情况（如果输入验证正确则不应发生）
    # Handle case where the list is empty after truncation (should not happen if input validation is correct)
    if not contents_to_send:
         logger.error(f"Message list became empty after truncation (Key: {proxy_key[:8]}...)") # Log empty list after truncation
         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Processed message list is empty") # 引发 400 异常 (Raise 400 exception)

    # 使用可能被截断的上下文进行 API 调用
    # Use the potentially truncated context for the API call
    contents = contents_to_send # 重命名以便在函数其余部分使用 (Rename for use in the rest of the function)

    # --- 请求处理循环 ---
    # --- Request Processing Loop ---
    key_manager.reset_tried_keys_for_request() # 重置已尝试的 Key 集合 (Reset the set of tried keys)
    last_error = None # 初始化最后错误 (Initialize last error)
    response = None # 初始化响应 (Initialize response)
    current_api_key = None # 初始化当前 API Key (Initialize current API Key)
    gemini_client_instance = None # 在循环外初始化 (Initialize outside the loop)

    active_keys_count = key_manager.get_active_keys_count() # 获取活跃 Key 数量 (Get active key count)
    retry_attempts = active_keys_count if active_keys_count > 0 else 1 # 设置重试次数 (Set number of retry attempts)

    for attempt in range(1, retry_attempts + 1): # 遍历重试次数 (Iterate through retry attempts)
        # --- 智能 Key 选择 ---
        # --- Smart Key Selection ---
        current_api_key = key_manager.select_best_key(chat_request.model, config.MODEL_LIMITS) # 选择最佳 Key (Select the best key)

        if current_api_key is None: # 如果无法选择 Key (If no key can be selected)
            log_msg_no_key = format_log_message('WARNING', f"尝试 {attempt}/{retry_attempts}：无法选择合适的 API 密钥，结束重试。", extra={'request_type': request_type, 'model': chat_request.model, 'ip': client_ip}) # 格式化日志消息 (Format log message)
            logger.warning(log_msg_no_key) # 记录警告 (Log warning)
            break # 结束重试循环 (Break the retry loop)

        key_manager.tried_keys_for_request.add(current_api_key) # 将当前 Key 添加到已尝试集合 (Add current key to tried set)
        extra_log = {'key': current_api_key[:8], 'request_type': request_type, 'model': chat_request.model, 'ip': client_ip, 'attempt': attempt} # 构建额外日志信息 (Build extra log info)
        log_msg = format_log_message('INFO', f"第 {attempt}/{retry_attempts} 次尝试，选择密钥: {current_api_key[:8]}...", extra=extra_log) # 格式化日志消息 (Format log message)
        logger.info(log_msg) # 记录信息 (Log info)

        # --- 模型速率限制预检查 (移至 request_utils.check_rate_limits_and_update_counts) ---
        # --- Model Rate Limit Pre-check (Moved to request_utils.check_rate_limits_and_update_counts) ---
        model_name = chat_request.model # 获取模型名称 (Get model name)
        limits = config.MODEL_LIMITS.get(model_name) # 获取模型限制 (Get model limits)
        # 调用新的检查函数
        # Call the new check function
        if not check_rate_limits_and_update_counts(current_api_key, model_name, limits): # 检查并更新速率限制计数 (Check and update rate limit counts)
            continue # 如果检查失败 (达到限制)，跳过此 Key，尝试下一个 (If check fails (limit reached), skip this key and try the next one)

        # --- API 调用尝试 ---
        # --- API Call Attempt ---
        try:
            # 确定安全设置
            # Determine safety settings
            current_safety_settings = safety_settings_g2 if DISABLE_SAFETY_FILTERING or 'gemini-2.0-flash-exp' in chat_request.model else safety_settings # 根据配置和模型选择安全设置 (Select safety settings based on config and model)
            # 创建 GeminiClient 实例
            # Create GeminiClient instance
            gemini_client_instance = GeminiClient(current_api_key) # 创建 GeminiClient 实例 (Create GeminiClient instance)

            # --- 流式 vs 非流式 ---
            # --- Streaming vs Non-streaming ---
            if chat_request.stream: # 如果是流式请求 (If it's a streaming request)
                # --- 流式处理 ---
                # --- Streaming Handling ---
                async def stream_generator(): # 定义流式生成器 (Define streaming generator)
                    nonlocal last_error, current_api_key, model_name, client_ip, today_date_str_pt, limits # 引用外部变量 (Reference outer variables)
                    stream_error_occurred = False # 标记流错误是否发生 (Flag indicating if a stream error occurred)
                    assistant_message_yielded = False # 标记是否已产生助手消息 (Flag indicating if an assistant message has been yielded)
                    full_reply_content = "" # 新增：用于累积回复内容 (New: Used to accumulate reply content)
                    usage_metadata_received = None # 存储接收到的使用情况元数据 (Stores received usage metadata)
                    actual_finish_reason = "stop" # 存储实际完成原因 (Stores the actual finish reason)
                    response_id = f"chatcmpl-{int(time.time() * 1000)}" # 更唯一的 ID (More unique ID)

                    try:
                        async for chunk in gemini_client_instance.stream_chat(chat_request, contents, current_safety_settings, system_instruction): # 异步迭代流式响应块 (Asynchronously iterate over streaming response chunks)
                            if isinstance(chunk, dict): # 如果是字典块 (If it's a dictionary chunk)
                                if '_usage_metadata' in chunk:
                                    usage_metadata_received = chunk['_usage_metadata'] # 提取使用情况元数据 (Extract usage metadata)
                                    logger.debug(f"流接收到 usage metadata: {usage_metadata_received}") # 记录使用情况元数据 (Log usage metadata)
                                    continue # 继续处理下一个块 (Continue processing the next chunk)
                                if '_final_finish_reason' in chunk:
                                    actual_finish_reason = chunk['_final_finish_reason'] # 提取最终完成原因 (Extract final finish reason)
                                    logger.debug(f"流接收到最终完成原因: {actual_finish_reason}") # 记录最终完成原因 (Log final finish reason)
                                    continue # 继续处理下一个块 (Continue processing the next chunk)
                                # 可以添加对其他元数据块的处理
                                # Can add handling for other metadata chunks

                            # 检查是否是错误信息（例如内部处理错误）
                            # Check if it's an error message (e.g., internal processing error)
                            if isinstance(chunk, str) and chunk.startswith("[ERROR]"): # 如果是错误字符串 (If it's an error string)
                                logger.error(f"流处理内部错误: {chunk}") # 记录内部错误 (Log internal error)
                                last_error = chunk # 记录错误供外部重试判断 (Record error for external retry judgment)
                                stream_error_occurred = True # 标记流错误发生 (Mark stream error occurred)
                                break # 停止处理此流 (Stop processing this stream)

                            # 格式化标准文本块
                            # Format standard text chunk
                            formatted_chunk = { # 构建格式化块 (Build formatted chunk)
                                "id": response_id,
                                "object": "chat.completion.chunk",
                                "created": int(time.time()),
                                "model": chat_request.model,
                                "choices": [{
                                    "delta": {"role": "assistant", "content": chunk if isinstance(chunk, str) else ""}, # 确保 content 是字符串 (Ensure content is a string)
                                    "index": 0,
                                    "finish_reason": None
                                }]
                            }
                            yield f"data: {json.dumps(formatted_chunk)}\n\n" # Yield 格式化块 (Yield formatted chunk)
                            if isinstance(chunk, str) and chunk: # 仅在有实际文本时标记 (Mark only if there is actual text)
                                assistant_message_yielded = True # 标记已产生助手消息 (Mark assistant message yielded)
                                full_reply_content += chunk # 累积回复内容 (Accumulate reply content)

                        # --- 流结束处理 ---
                        # --- Stream End Handling ---
                        if not stream_error_occurred: # 如果没有发生流错误 (If no stream error occurred)
                            # 如果没有产生任何助手消息，根据完成原因发送结束块
                            # If no assistant message was generated, send end chunk based on finish reason
                            if not assistant_message_yielded: # 如果没有产生助手消息 (If no assistant message was yielded)
                                logger.warning(f"流结束时未产生助手内容 (完成原因: {actual_finish_reason})。发送结束块。") # Log warning and send end chunk
                                end_chunk = { # 构建结束块 (Build end chunk)
                                    "id": response_id,
                                    "object": "chat.completion.chunk",
                                    "created": int(time.time()),
                                    "model": chat_request.model,
                                    "choices": [{"delta": {}, "index": 0, "finish_reason": actual_finish_reason}] # delta 为空 (delta is empty)
                                }
                                yield f"data: {json.dumps(end_chunk)}\n\n" # Yield 结束块 (Yield end chunk)
                            else:
                                # 如果已产生内容，发送一个只有 finish_reason 的结束块
                                # If content has been generated, send an end chunk with only finish_reason
                                end_chunk = { # 构建结束块 (Build end chunk)
                                    "id": response_id,
                                    "object": "chat.completion.chunk",
                                    "created": int(time.time()),
                                    "model": chat_request.model,
                                    "choices": [{"delta": {}, "index": 0, "finish_reason": actual_finish_reason}]
                                }
                                yield f"data: {json.dumps(end_chunk)}\n\n" # Yield 结束块 (Yield end chunk)

                            yield "data: [DONE]\n\n" # Yield DONE 标记 (Yield DONE marker)

                            # --- 处理 Token 计数（成功情况，移至 request_utils.update_token_counts）---
                            # --- Handle Token Counts (Success Case, Moved to request_utils.update_token_counts) ---
                            if usage_metadata_received: # 如果接收到使用情况元数据 (If usage metadata is received)
                                prompt_tokens = usage_metadata_received.get('promptTokenCount') # 获取 prompt_tokens (Get prompt_tokens)
                                update_token_counts(current_api_key, model_name, limits, prompt_tokens, client_ip, today_date_str_pt) # 更新 token 计数 (Update token counts)
                            else:
                                logger.warning(f"Stream response successful but no usage metadata received (Key: {current_api_key[:8]}...). Token counts not updated.") # Log warning if no usage metadata received

                            # --- 成功流式传输后保存上下文（可配置）---
                            # --- Save Context After Successful Streaming (Configurable) ---
                            if not config.STREAM_SAVE_REPLY: # 如果配置为不保存流式回复 (If configured not to save streaming reply)
                                # 默认行为：只保存到用户最后输入（更稳健，流中断也能保存）
                                # Default behavior: Save only up to the user's last input (more robust, saves even if stream is interrupted)
                                logger.info(f"Stream finished successfully for Key {proxy_key[:8]}.... Saving context up to user's last input (STREAM_SAVE_REPLY=false).") # Log saving context up to user input
                                logger.debug(f"准备为 Key '{proxy_key[:8]}...' 保存流式上下文 (不含回复) (内存模式: {db_utils.IS_MEMORY_DB})") # Log preparing to save context without reply (DEBUG level)
                                try:
                                    await context_store.save_context(proxy_key, contents_to_send) # 添加 await (Added await) # 保存上下文 (Save context)
                                except Exception as e:
                                    logger.error(f"保存流式上下文 (不含回复) 失败 (Key: {proxy_key[:8]}...): {str(e)}") # 记录保存失败错误 (Log save failure error)
                            else:
                                # 配置为保存回复：在流结束后保存完整对话（流中断则不保存）
                                # Configured to save reply: Save the complete conversation after the stream ends (not saved if stream is interrupted)
                                if assistant_message_yielded: # 仅在有回复时保存 (Save only if there was a reply)
                                    logger.info(f"Stream finished successfully for Key {proxy_key[:8]}.... Saving context including model reply (STREAM_SAVE_REPLY=true).") # Log saving context including reply
                                    # 1. 构建模型回复部分
                                    # 1. Build model reply part
                                    model_reply_part = {"role": "model", "parts": [{"text": full_reply_content}]} # 构建模型回复部分 (Build model reply part)
                                    # 2. 合并上下文
                                    # 2. Merge context
                                    final_contents_to_save = contents_to_send + [model_reply_part] # 合并内容 (Merge contents)
                                    # 3. 再次截断
                                    # 3. Truncate again
                                    truncated_contents_to_save, still_over_limit_final = truncate_context(final_contents_to_save, chat_request.model) # 再次截断 (Truncate again)
                                    # 4. 保存 (如果不超限)
                                    # 4. Save (only if not over limit)
                                    if not still_over_limit_final: # 如果最终未超限 (If not over limit finally)
                                        # 使用原始的 proxy_key 保存上下文
                                        # Use the original proxy_key to save context
                                        logger.debug(f"准备为 Key '{proxy_key[:8]}...' 保存流式上下文 (含回复) (内存模式: {db_utils.IS_MEMORY_DB})") # Log preparing to save context with reply (DEBUG level)
                                        try:
                                            await context_store.save_context(proxy_key, truncated_contents_to_save) # 添加 await (Added await) # 保存上下文 (Save context)
                                            logger.info(f"流式上下文 (含回复) 保存成功 for Key {proxy_key[:8]}...") # Log successful save
                                        except Exception as e:
                                            logger.error(f"保存流式上下文 (含回复) 失败 (Key: {proxy_key[:8]}...): {str(e)}") # 记录保存失败错误 (Log save failure error)
                                    else:
                                        # 这种情况应该很少见，如果初始截断正确的话
                                        # This case should be rare if initial truncation was correct
                                        logger.error(f"流式上下文在添加回复并再次截断后仍然超限 (Key: {proxy_key[:8]}...). 上下文未保存。") # Log context still over limit after truncation
                                else:
                                     logger.warning(f"Stream finished successfully but no assistant message was yielded (Key: {proxy_key[:8]}...). No context saved for this interaction (STREAM_SAVE_REPLY=true).") # Log warning if no assistant message yielded

                    except asyncio.CancelledError: # 捕获 asyncio.CancelledError (Catch asyncio.CancelledError)
                        logger.info(f"客户端连接已中断 (IP: {client_ip})") # Log client disconnect
                        # 不需要 yield [DONE]
                        # No need to yield [DONE]
                    except httpx.HTTPStatusError as http_err: # 捕获 stream_chat 可能抛出的 HTTP 错误 (Catch HTTP errors that stream_chat might raise)
                        status_code = http_err.response.status_code # 获取状态码 (Get status code)
                        last_error = f"流式 API 错误: {status_code}" # 设置最后错误 (Set last error)
                        logger.error(f"{last_error} - {http_err.response.text}", exc_info=False) # 记录错误 (Log error)
                        stream_error_occurred = True # 标记流错误发生 (Mark stream error occurred)

                        error_type = "api_error" # 默认错误类型 (Default error type)
                        if status_code == 400:
                            error_message = "请求无效或格式错误，请检查您的输入。" # 错误消息 (Error message)
                            error_type = "invalid_request_error" # 错误类型 (Error type)
                        elif status_code == 401:
                            error_message = "API 密钥无效或认证失败。" # 错误消息 (Error message)
                            error_type = "authentication_error" # 错误类型 (Error type)
                        elif status_code == 403:
                            error_message = "API 密钥无权访问所请求的资源。" # 错误消息 (Error message)
                            error_type = "permission_error" # 错误类型 (Error type)
                        elif status_code == 429:
                            error_message = "请求频率过高或超出配额，请稍后重试。" # 错误消息 (Error message)
                            error_type = "rate_limit_error" # 错误类型 (Error type)
                            logger.warning(f"流式请求遇到 429 错误 (Key: {current_api_key[:8]}...): {error_message}") # 记录 429 错误 (Log 429 error)
                        elif status_code == 500:
                            error_message = "Gemini API 服务器内部错误，请稍后重试。" # 错误消息 (Error message)
                            error_type = "server_error" # 错误类型 (Error type)
                        elif status_code == 503:
                            error_message = "Gemini API 服务暂时不可用，请稍后重试。" # 错误消息 (Error message)
                            error_type = "service_unavailable_error" # 错误类型 (Error type)
                        else:
                            error_message = f"API 请求失败，状态码: {status_code}。请检查日志获取详情。" # 默认错误消息 (Default error message)

                        # 发送错误信息给客户端并结束流
                        # Send error information to the client and end the stream
                        yield f"data: {json.dumps({'error': {'message': error_message, 'type': error_type, 'code': status_code}})}\n\n" # Yield 错误信息 (Yield error information)
                        yield "data: [DONE]\n\n" # Yield DONE 标记 (Yield DONE marker)
                        return # 中断生成器 (Interrupt generator)

                    except Exception as stream_e: # 捕获流处理中捕获到的意外异常 (Catch unexpected exceptions caught during stream processing)
                        last_error = f"流处理中捕获到意外异常: {stream_e}" # 设置最后错误 (Set last error)
                        logger.error(last_error, exc_info=True) # 记录错误 (Log error)
                        stream_error_occurred = True # 标记流错误发生 (Mark stream error occurred)
                        # 可以在这里 yield 一个错误消息给客户端，但标准做法是直接中断
                        # Can yield an error message to the client here, but the standard practice is to interrupt directly
                        # yield f"error: {json.dumps({'error': {'message': last_error, 'type': 'proxy_error'}})}\n\n"

                response = StreamingResponse(stream_generator(), media_type="text/event-stream") # 创建 StreamingResponse (Create StreamingResponse)
                # 对于流式响应，我们假设它成功启动，直接返回。错误处理在生成器内部进行。
                # For streaming responses, we assume it started successfully and return directly. Error handling is done inside the generator.
                # 如果 stream_generator 内部发生错误导致无法生成数据，客户端会收到中断的流。
                # If an error occurs inside stream_generator that prevents data generation, the client will receive an interrupted stream.
                # 重试逻辑主要处理 API 调用本身的失败（例如密钥无效、网络问题）。
                # Retry logic primarily handles failures of the API call itself (e.g., invalid key, network issues).
                # 如果流成功启动但中途因模型原因（如安全）中断，这不算是需要重试的错误。
                # If the stream starts successfully but is interrupted midway due to model reasons (like safety), this is not considered a retryable error.
                logger.info(f"流式响应已启动 (Key: {current_api_key[:8]})") # Log that streaming response has started
                return response # 直接返回流式响应 (Return the streaming response directly)

            else: # 如果是非流式请求 (If it's a non-streaming request)
                # --- 非流式处理 ---
                # --- Non-streaming Handling ---
                async def run_gemini_completion(): # 定义运行 Gemini 补全的异步函数 (Define async function to run Gemini completion)
                    return await gemini_client_instance.complete_chat(chat_request, contents, current_safety_settings, system_instruction) # 运行 Gemini 补全 (Run Gemini completion)

                async def check_client_disconnect(): # 定义检查客户端断开连接的异步函数 (Define async function to check for client disconnect)
                    while True:
                        if await http_request.is_disconnected(): # 检查是否断开连接 (Check if disconnected)
                            logger.warning(f"客户端连接中断 detected (IP: {client_ip})") # Log client disconnect
                            return True # 返回 True (Return True)
                        await asyncio.sleep(0.5) # 等待 0.5 秒 (Wait for 0.5 seconds)

                gemini_task = asyncio.create_task(run_gemini_completion()) # 创建 Gemini 任务 (Create Gemini task)
                disconnect_task = asyncio.create_task(check_client_disconnect()) # 创建断开连接检查任务 (Create disconnect check task)

                done, pending = await asyncio.wait( # 等待任务完成 (Wait for tasks to complete)
                    [gemini_task, disconnect_task], return_when=asyncio.FIRST_COMPLETED
                )

                if disconnect_task in done: # 如果断开连接任务先完成 (If disconnect task completes first)
                    gemini_task.cancel() # 取消 Gemini 任务 (Cancel Gemini task)
                    try: await gemini_task
                    except asyncio.CancelledError: logger.info("非流式 API 任务已成功取消") # Log successful cancellation
                    logger.error(f"客户端连接中断 (IP: {client_ip})，终止请求处理。") # Log client disconnect and termination
                    return None # 不返回任何响应 (Do not return any response)

                # Gemini 任务完成
                # Gemini task completed
                disconnect_task.cancel() # 取消断开连接检查任务 (Cancel disconnect check task)
                try: await disconnect_task
                except asyncio.CancelledError: pass

                if gemini_task.exception(): # 如果 Gemini 任务抛出异常 (If Gemini task raised an exception)
                    # 如果 Gemini 任务本身抛出异常（例如 API 调用失败）
                    # If the Gemini task itself raised an exception (e.g., API call failed)
                    exc = gemini_task.exception() # 获取异常 (Get the exception)
                    raise exc # 将异常传递给外层 try-except 处理 (Pass the exception to the outer try-except handler)

                # 获取 Gemini 任务结果
                # Get Gemini task result
                response_content: ResponseWrapper = gemini_task.result() # 获取任务结果 (Get task result)

                # --- OpenAI API 兼容性处理 ---
                # --- OpenAI API Compatibility Handling ---
                assistant_content = response_content.text if response_content else "" # 获取助手回复内容 (Get assistant reply content)
                finish_reason = response_content.finish_reason if response_content else "stop" # 获取完成原因 (Get finish reason)

                if not response_content or not assistant_content: # 如果响应内容为空或助手回复为空 (If response content is empty or assistant reply is empty)
                    if finish_reason != "STOP": # 如果完成原因不是 STOP (If finish reason is not STOP)
                        last_error = f"Gemini API 返回空响应或被阻止。完成原因: {finish_reason}" # 设置最后错误 (Set last error)
                        logger.warning(f"{last_error} (Key: {current_api_key[:8]})") # 记录警告 (Log warning)
                        if finish_reason == "SAFETY": # 如果完成原因是 SAFETY (If finish reason is SAFETY)
                            key_manager.mark_key_issue(current_api_key, "safety_block") # 标记 Key 问题 (Mark key issue)
                        continue # 标记错误并尝试下一个 Key (Mark error and try the next key)
                    else:
                        logger.warning(f"Gemini API 返回 STOP 但文本为空 (Key: {current_api_key[:8]})。提供空助手消息。") # Log warning for empty text with STOP reason
                        assistant_content = "" # 确保有空字符串 (Ensure there is an empty string)

                # 处理工具调用
                # Handle tool calls
                final_tool_calls = None # 初始化最终工具调用 (Initialize final tool calls)
                raw_gemini_tool_calls = getattr(response_content, 'tool_calls', None) # 获取原始 Gemini 工具调用 (Get raw Gemini tool calls)
                if raw_gemini_tool_calls: # 如果有原始工具调用 (If there are raw tool calls)
                     logger.info("处理 Gemini 返回的工具调用...") # Log processing tool calls
                     final_tool_calls = process_tool_calls(raw_gemini_tool_calls) # 处理工具调用 (Process tool calls)
                     if final_tool_calls: logger.info(f"已处理的工具调用: {final_tool_calls}") # Log processed tool calls
                     else: logger.warning("process_tool_calls 返回 None 或空列表。") # Log warning if process_tool_calls returns None or empty list

                # 构建最终响应
                # Build final response
                response = ChatCompletionResponse( # 构建 ChatCompletionResponse (Build ChatCompletionResponse)
                    id=f"chatcmpl-{int(time.time() * 1000)}", # 更唯一的 ID (More unique ID)
                    object="chat.completion", # 对象类型 (Object type)
                    created=int(time.time()), # 创建时间 (Creation time)
                    model=chat_request.model, # 模型名称 (Model name)
                    choices=[{ # 选项列表 (List of choices)
                        "index": 0,
                        "message": ResponseMessage(role="assistant", content=assistant_content, tool_calls=final_tool_calls), # 助手消息 (Assistant message)
                        "finish_reason": finish_reason # 完成原因 (Finish reason)
                    }],
                    # usage 字段可以尝试从 response_content.usage_metadata 填充
                    # The usage field can be attempted to be populated from response_content.usage_metadata
                    usage={ # 使用情况 (Usage)
                        "prompt_tokens": response_content.prompt_token_count or 0,
                        "completion_tokens": response_content.candidates_token_count or 0,
                        "total_tokens": response_content.total_token_count or 0
                    } if response_content and response_content.usage_metadata else None # 如果有使用情况元数据则填充 (Populate if usage metadata is available)
                )

                logger.info(f"非流式请求处理成功 (Key: {current_api_key[:8]})") # Log successful non-streaming request

                # --- 处理 Token 计数（成功情况，移至 request_utils.update_token_counts）---
                # --- Handle Token Counts (Success Case, Moved to request_utils.update_token_counts) ---
                if response_content and response_content.usage_metadata: # 如果有使用情况元数据 (If usage metadata is available)
                    prompt_tokens = response_content.prompt_token_count # 获取 prompt_tokens (Get prompt_tokens)
                    update_token_counts(current_api_key, model_name, limits, prompt_tokens, client_ip, today_date_str_pt) # 更新 token 计数 (Update token counts)
                else:
                     logger.warning(f"Non-stream response successful but ResponseWrapper missing usage_metadata (Key: {current_api_key[:8]}...). Token counts not updated.") # Log warning if usage metadata is missing

                # --- 成功非流式响应后保存上下文（包括模型回复）---
                # --- Save Context After Successful Non-streaming Response (Including Model Reply) ---
                if assistant_content is not None: # 确保有模型内容（即使是空字符串） (Ensure there is model content (even if it's an empty string))
                    # 1. 构建模型回复部分
                    # 1. Build model reply part
                    model_reply_part = {"role": "model", "parts": [{"text": assistant_content}]} # 构建模型回复部分 (Build model reply part)
                    # 2. 合并：将模型回复附加到发送给 API 的上下文中
                    # 2. Merge: Append the model reply to the context sent to the API
                    final_contents_to_save = contents_to_send + [model_reply_part] # 合并内容 (Merge contents)
                    # 3. 再次截断（以防添加回复后超限，尽管如果初始截断有效则不太可能）
                    # 3. Truncate again (in case it goes over limit after adding reply, although unlikely if initial truncation was effective)
                    truncated_contents_to_save, still_over_limit_final = truncate_context(final_contents_to_save, chat_request.model) # 再次截断 (Truncate again)
                    # 4. 保存（仅当未超限时）
                    # 4. Save (only if not over limit)
                    if not still_over_limit_final: # 如果最终未超限 (If not over limit finally)
                        # 使用原始的 proxy_key 保存上下文
                        # Use the original proxy_key to save context
                        logger.debug(f"准备为 Key '{proxy_key[:8]}...' 保存非流式上下文 (内存模式: {db_utils.IS_MEMORY_DB})") # Log preparing to save context (DEBUG level)
                        try:
                            await context_store.save_context(proxy_key, truncated_contents_to_save) # 添加 await (Added await) # 保存上下文 (Save context)
                        except Exception as e:
                            logger.error(f"保存上下文失败 (Key: {proxy_key[:8]}...): {str(e)}") # 记录保存失败错误 (Log save failure error)
                        logger.info(f"上下文成功保存 for Key {proxy_key[:8]}...") # 记录实际使用的 Key (Log the key actually used)
                    else:
                        # 这种情况应该很少见，如果初始截断正确的话
                        # This case should be rare if initial truncation was correct
                        logger.error(f"添加模型回复并最终截断后上下文仍然超限 (Key: {proxy_key[:8]}...). 上下文未保存。") # Log context still over limit after truncation
                else:
                     logger.warning(f"非流式响应成功，但 assistant_content 为 None。无法将模型回复保存到上下文 (Key: {proxy_key[:8]}...).") # Log warning if assistant_content is None

                return response # 成功，跳出重试循环 (Success, break the retry loop)

        # --- 处理 API 调用异常 ---
        # --- Handle API Call Exceptions ---
        except HTTPException as e: # 捕获 HTTPException (Catch HTTPException)
            # 如果是消息转换失败，这是永久错误，直接抛出
            # If it's a message conversion failure, it's a permanent error, raise directly
            if e.status_code == status.HTTP_400_BAD_REQUEST and "消息转换失败" in e.detail: # 如果是消息转换失败错误 (If it's a message conversion failure error)
                 logger.error(f"消息转换失败，终止重试。详情: {e.detail}") # 记录错误并终止重试 (Log error and terminate retry)
                 raise e # 重新抛出异常 (Re-raise exception)
            # 其他 HTTPException 可能与特定 Key 相关，记录并继续重试
            # Other HTTPExceptions might be related to a specific key, log and continue retrying
            logger.warning(f"请求处理中遇到 HTTPException (状态码 {e.status_code})，尝试下一个 Key。详情: {e.detail}") # Log HTTPException and try next key
            last_error = f"HTTPException: {e.detail}" # 设置最后错误 (Set last error)
            continue # 尝试下一个密钥 (Try the next key)

        except Exception as e: # 捕获其他异常 (Catch other exceptions)
            # 使用 handle_gemini_error 处理通用 API 错误
            # Use handle_gemini_error to handle general API errors
            last_error = handle_gemini_error(e, current_api_key, key_manager) # 处理 Gemini 错误 (Handle Gemini error)
            logger.error(f"第 {attempt}/{retry_attempts} 次尝试失败 (Key: {current_api_key[:8]}): {last_error}", exc_info=True) # 记录失败尝试错误 (Log failed attempt error)
            # 继续下一次尝试
            # Continue to the next attempt
            continue # 尝试下一个密钥 (Try the next key)

    # --- 重试循环结束 ---
    # --- Retry Loop End ---
    # 如果所有尝试都失败了
    # If all attempts failed
    if response is None: # 确保是在所有尝试失败后 (Ensure it's after all attempts failed)
        final_error_msg = last_error or "所有 API 密钥均尝试失败或无可用密钥" # 设置最终错误消息 (Set final error message)
        extra_log_fail = {'request_type': request_type, 'model': chat_request.model, 'error_message': final_error_msg, 'ip': client_ip} # 构建额外日志信息 (Build extra log info)

        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR # 默认 500 (Default 500)
        detail_msg = f"API 请求处理失败: {final_error_msg}" # 默认消息 (Default message)

        if last_error: # 如果有最后错误 (If there is a last error)
            # 尝试从 last_error 中提取或判断错误类型
            # Attempt to extract or determine error type from last_error
            last_error_lower = last_error.lower() # 转换为小写 (Convert to lowercase)
            if "400" in last_error or "invalid" in last_error_lower or "bad request" in last_error_lower:
                status_code = status.HTTP_400_BAD_REQUEST # 设置状态码 (Set status code)
                detail_msg = "请求无效或格式错误，请检查您的输入。" # 设置详情消息 (Set detail message)
            elif "401" in last_error or "unauthorized" in last_error_lower or "authentication" in last_error_lower:
                status_code = status.HTTP_401_UNAUTHORIZED # 设置状态码 (Set status code)
                detail_msg = "API 密钥无效或认证失败。" # 设置详情消息 (Set detail message)
            elif "403" in last_error or "forbidden" in last_error_lower or "permission" in last_error_lower:
                status_code = status.HTTP_403_FORBIDDEN # 设置状态码 (Set status code)
                detail_msg = "API 密钥无权访问所请求的资源。" # 设置详情消息 (Set detail message)
            elif "429" in last_error or "rate_limit" in last_error_lower or "quota" in last_error_lower or "频率限制" in last_error:
                status_code = status.HTTP_429_TOO_MANY_REQUESTS # 设置状态码 (Set status code)
                detail_msg = "请求频率过高或超出配额，请稍后重试。" # 设置详情消息 (Set detail message)
            elif "500" in last_error or "internal server error" in last_error_lower:
                status_code = status.HTTP_500_INTERNAL_SERVER_ERROR # 设置状态码 (Set status code)
                detail_msg = "Gemini API 服务器内部错误，请稍后重试。" # 设置详情消息 (Set detail message)
            elif "503" in last_error or "service unavailable" in last_error_lower:
                status_code = status.HTTP_503_SERVICE_UNAVAILABLE # 设置状态码 (Set status code)
                detail_msg = "Gemini API 服务暂时不可用，请稍后重试。" # 设置详情消息 (Set detail message)
            # 可以添加更多特定错误的判断
            # More specific error judgments can be added

        # 记录最终错误日志
        # Log final error
        log_level = logging.WARNING if status_code == 429 else logging.ERROR # 根据状态码设置日志级别 (Set log level based on status code)
        logger.log(log_level, f"请求处理最终失败 ({status_code}): {final_error_msg}", extra={**extra_log_fail, 'status_code': status_code}) # 记录最终错误 (Log final error)

        # 抛出最终的 HTTPException
        # Raise the final HTTPException
        raise HTTPException(status_code=status_code, detail=detail_msg) # 抛出 HTTPException (Raise HTTPException)


# (process_tool_calls 函数已移至 request_utils.py)
# (process_tool_calls function has been moved to request_utils.py)
