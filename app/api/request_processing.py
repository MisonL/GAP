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

async def process_request(
    chat_request: ChatCompletionRequest,
    http_request: Request,
    request_type: Literal['stream', 'non-stream'],
    auth_data: Dict[str, Any], # 认证数据，包含 Key 和配置
    key_manager: APIKeyManager, # 依赖注入的 Key Manager
    http_client: httpx.AsyncClient # 依赖注入的 HTTP Client
) -> Optional[Union[StreamingResponse, ChatCompletionResponse]]:
    """
    聊天补全（流式和非流式）的核心请求处理函数。
    包括密钥选择、速率限制检查、API 调用尝试和响应处理。
    未来将加入上下文管理逻辑。

    Args:
        chat_request: 包含聊天请求数据的 Pydantic 模型。
        http_request: FastAPI Request 对象，用于获取 IP 和检查断开连接。
        request_type: 'stream' 或 'non-stream'。
        auth_data: 验证通过的认证数据，包含代理 Key 和配置。

    Returns:
        流式请求返回 StreamingResponse，
        非流式请求返回 ChatCompletionResponse，
        如果客户端断开连接或早期发生不可重试的错误，则返回 None。

    Raises:
    """
    client_ip = get_client_ip(http_request) # 获取客户端 IP
    cst_time_str, today_date_str_pt = get_current_timestamps() # 获取当前时间戳

    # 从认证数据中提取代理 Key 和配置
    proxy_key = auth_data.get("key") # 获取代理 Key
    key_config = auth_data.get("config", {}) # 获取 Key 配置，默认为空字典
    enable_context = key_config.get('enable_context_completion', config.ENABLE_CONTEXT_COMPLETION) # 获取 Key 的上下文补全配置，如果 Key 配置中没有则使用全局配置


    # --- 记录请求入口日志 ---
    logger.info(f"处理来自 IP: {client_ip} 的请求 ({request_type})，模型: {chat_request.model}，时间: {cst_time_str}，Key: {proxy_key[:8]}..., 上下文补全: {enable_context}") # 记录收到的请求信息

    # --- 防滥用保护 ---
    try:
        protect_from_abuse(http_request, config.MAX_REQUESTS_PER_MINUTE, config.MAX_REQUESTS_PER_DAY_PER_IP) # 执行防滥用检查
    except HTTPException as e:
        logger.warning(f"IP {client_ip} 的请求被阻止 (防滥用): {e.detail}") # IP 的请求被阻止 (防滥用)
        raise e # 重新抛出防滥用异常

    if not chat_request.messages: # 检查消息列表是否为空
        logger.warning(f"Request from IP: {client_ip} (Key: {proxy_key[:8]}...) has empty messages list") # 消息列表为空
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="消息列表不能为空") # 引发 400 异常

    # --- 模型列表检查 (如果需要) ---
    # 保持在 endpoints.py 中，因为它更像是路由级别的检查
    # 此处假设模型已验证

    # --- 上下文管理 ---
    history_contents: Optional[List[Dict[str, Any]]] = None # 初始化历史上下文
    if enable_context: # 如果启用了上下文补全
        # 1. 加载历史上下文
        history_contents = await context_store.load_context_as_gemini(proxy_key) # 加载并转换历史上下文
        logger.info(f"Loaded and converted {len(history_contents) if history_contents else 0} historical messages to Gemini format for Key {proxy_key[:8]}...") # 加载并转换历史消息
    else:
        logger.debug(f"Key {proxy_key[:8]}... 的上下文补全已禁用，跳过加载历史上下文。") # 上下文补全已禁用，跳过加载历史上下文

    # 2. 转换当前请求中的新消息
    conversion_result = convert_messages(chat_request.messages, use_system_prompt=True) # 转换消息
    if isinstance(conversion_result, list): # 转换错误
        error_msg = "; ".join(conversion_result) # 拼接错误消息
        logger.error(f"消息转换失败 (Key: {proxy_key[:8]}...): {error_msg}") # 消息转换失败
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"消息转换失败: {error_msg}") # 引发 400 异常
    new_contents, system_instruction = conversion_result # system_instruction 仅来自当前请求

    # 3. 合并历史记录和新消息
    # 仅在加载了历史上下文时合并
    merged_contents = (history_contents or []) + new_contents # 合并历史和新内容

    if not merged_contents: # 如果合并后内容为空
         logger.error(f"Merged message list is empty (Key: {proxy_key[:8]}...)") # 合并消息列表为空
         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot process empty message list") # 引发 400 异常

    # 4. 在发送到 API 之前截断合并后的上下文
    contents_to_send, is_over_limit_after_truncate = truncate_context(merged_contents, chat_request.model) # 截断上下文

    # 处理截断后仍超限的情况（例如单个长消息）
    if is_over_limit_after_truncate:
         logger.error(f"Context exceeds token limit for model {chat_request.model} even after truncation (Key: {proxy_key[:8]}...)") # 上下文在截断后仍然超限
         raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=f"Request content exceeds processing capacity for model {chat_request.model}. Please shorten the input.") # 引发 413 异常

    # 处理截断后列表为空的情况（如果输入验证正确则不应发生）
    if not contents_to_send:
         logger.error(f"Message list became empty after truncation (Key: {proxy_key[:8]}...)") # 消息列表在截断后变为空
         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Processed message list is empty") # 引发 400 异常

    # 使用可能被截断的上下文进行 API 调用
    contents = contents_to_send # 重命名以便在函数其余部分使用

    # --- 请求处理循环 ---
    key_manager.reset_tried_keys_for_request() # 重置已尝试的 Key 集合
    last_error = None # 初始化最后错误
    response = None # 初始化响应
    current_api_key = None # 初始化当前 API Key
    gemini_client_instance = None # 在循环外初始化

    active_keys_count = key_manager.get_active_keys_count() # 获取活跃 Key 数量
    retry_attempts = active_keys_count if active_keys_count > 0 else 1 # 设置重试次数

    for attempt in range(1, retry_attempts + 1): # 遍历重试次数
        # --- 智能 Key 选择 ---
        current_api_key = key_manager.select_best_key(chat_request.model, config.MODEL_LIMITS) # 选择最佳 Key

        if current_api_key is None: # 如果无法选择 Key
            log_msg_no_key = format_log_message('WARNING', f"尝试 {attempt}/{retry_attempts}：无法选择合适的 API 密钥，结束重试。", extra={'request_type': request_type, 'model': chat_request.model, 'ip': client_ip}) # 格式化日志消息
            logger.warning(log_msg_no_key) # 记录警告
            break # 结束重试循环

        key_manager.tried_keys_for_request.add(current_api_key) # 将当前 Key 添加到已尝试集合
        extra_log = {'key': current_api_key[:8], 'request_type': request_type, 'model': chat_request.model, 'ip': client_ip, 'attempt': attempt} # 构建额外日志信息
        log_msg = format_log_message('INFO', f"第 {attempt}/{retry_attempts} 次尝试，选择密钥: {current_api_key[:8]}...", extra=extra_log) # 格式化日志消息
        logger.info(log_msg) # 记录信息

        # --- 模型速率限制预检查 ---
        model_name = chat_request.model # 获取模型名称
        limits = config.MODEL_LIMITS.get(model_name) # 获取模型限制
        # 调用新的检查函数
        if not check_rate_limits_and_update_counts(current_api_key, model_name, limits): # 检查并更新速率限制计数
            continue # 如果检查失败 (达到限制)，跳过此 Key，尝试下一个

        # --- API 调用尝试 ---
        try:
            # 确定安全设置
            current_safety_settings = safety_settings_g2 if config.DISABLE_SAFETY_FILTERING or 'gemini-2.0-flash-exp' in chat_request.model else safety_settings # 根据配置和模型选择安全设置
            # 创建 GeminiClient 实例，传入共享的 http_client
            gemini_client_instance = GeminiClient(current_api_key, http_client) # 创建 GeminiClient 实例

            # --- Streaming vs Non-streaming ---
            if chat_request.stream: # 如果是流式请求
                # --- Streaming Handling ---
                async def stream_generator(): # 定义流式生成器
                    nonlocal last_error, current_api_key, model_name, client_ip, today_date_str_pt, limits, proxy_key, enable_context # 引用外部变量
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
                                last_error = chunk # 记录错误供外部重试判断
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
                            # 如果没有产生任何助手消息，根据完成原因发送结束块
                            if not assistant_message_yielded: # 如果没有产生助手消息
                                if actual_finish_reason == "STOP":
                                    # 新增：如果完成原因是 STOP 但没有内容，根据是否有安全问题发送不同错误块
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
                                        "model": chat_request.model,
                                        "choices": [{"delta": {}, "index": 0, "finish_reason": actual_finish_reason}] # delta 为空
                                    }
                                    yield f"data: {json.dumps(end_chunk)}\n\n" # Yield 结束块
                            else:
                                # 如果已产生内容，发送一个只有 finish_reason 的结束块
                                end_chunk = { # 构建结束块
                                    "id": response_id,
                                    "object": "chat.completion.chunk",
                                    "created": int(time.time()),
                                    "model": chat_request.model,
                                    "choices": [{"delta": {}, "index": 0, "finish_reason": actual_finish_reason}]
                                }
                                yield f"data: {json.dumps(end_chunk)}\n\n" # Yield 结束块

                            yield "data: [DONE]\n\n" # Yield DONE 标记

                            # --- 处理 Token 计数（成功情况）---
                            if usage_metadata_received: # 如果接收到使用情况元数据
                                prompt_tokens = usage_metadata_received.get('promptTokenCount') # 获取 prompt_tokens
                                update_token_counts(current_api_key, model_name, limits, prompt_tokens, client_ip, today_date_str_pt) # 更新 token 计数
                            else:
                                logger.warning(f"Stream response successful but no usage metadata received (Key: {current_api_key[:8]}...). Token counts not updated.") # 流式响应成功但未接收到 usage metadata

                            # --- 成功流式传输后保存上下文（可配置）---
                            if enable_context: # 仅在启用了上下文补全时保存
                                if not config.STREAM_SAVE_REPLY: # 如果配置为不保存流式回复
                                    # 默认行为：只保存到用户最后输入（更稳健，流中断也能保存）
                                    logger.info(f"Stream finished successfully for Key {proxy_key[:8]}.... Saving context up to user's last input (STREAM_SAVE_REPLY=false).") # 流式响应成功，保存上下文到用户最后输入
                                    logger.debug(f"准备为 Key '{proxy_key[:8]}...' 保存流式上下文 (不含回复) (内存模式: {db_utils.IS_MEMORY_DB})") # 准备保存流式上下文 (不含回复)
                                    try:
                                        await context_store.save_context(proxy_key, contents_to_send) # 添加 await # 保存上下文
                                    except Exception as e:
                                        logger.error(f"保存流式上下文 (不含回复) 失败 (Key: {proxy_key[:8]}...): {str(e)}") # 保存流式上下文 (不含回复) 失败
                                else:
                                    # 配置为保存回复：在流结束后保存完整对话（流中断则不保存）
                                    if assistant_message_yielded: # 仅在有回复时保存
                                        logger.info(f"Stream finished successfully for Key {proxy_key[:8]}.... Saving context including model reply (STREAM_SAVE_REPLY=true).") # 流式响应成功，保存上下文 (含回复)
                                        # 1. 构建模型回复部分
                                        model_reply_part = {"role": "model", "parts": [{"text": full_reply_content}]} # 构建模型回复部分
                                        # 2. 合并上下文
                                        final_contents_to_save = contents_to_send + [model_reply_part] # 合并内容
                                        # 3. 再次截断
                                        truncated_contents_to_save, still_over_limit_final = truncate_context(final_contents_to_save, chat_request.model) # 再次截断
                                        # 4. 保存 (如果不超限)
                                        if not still_over_limit_final: # 如果最终未超限
                                            # 使用原始的 proxy_key 保存上下文
                                            logger.debug(f"准备为 Key '{proxy_key[:8]}...' 保存流式上下文 (含回复) (内存模式: {db_utils.IS_MEMORY_DB})") # 准备保存流式上下文 (含回复)
                                            try:
                                                await context_store.save_context(proxy_key, truncated_contents_to_save) # 添加 await # 保存上下文
                                                logger.info(f"流式上下文 (含回复) 保存成功 for Key {proxy_key[:8]}...") # 流式上下文 (含回复) 保存成功
                                            except Exception as e:
                                                logger.error(f"保存流式上下文 (含回复) 失败 (Key: {proxy_key[:8]}...): {str(e)}") # 保存流式上下文 (含回复) 失败
                                        else:
                                            # 这种情况应该很少见，如果初始截断正确的话
                                            logger.error(f"流式上下文在添加回复并再次截断后仍然超限 (Key: {proxy_key[:8]}...). 上下文未保存。") # 流式上下文在添加回复并再次截断后仍然超限
                            # Removed the inner else: pass block for assistant_message_yielded=false when STREAM_SAVE_REPLY=true, as no action is needed.
                            else: # enable_context is false
                                logger.debug(f"Key {proxy_key[:8]}... 的上下文补全已禁用，跳过流式上下文保存。") # 上下文补全已禁用，跳过流式上下文保存

                    except asyncio.CancelledError: # 捕获 asyncio.CancelledError
                        logger.info(f"客户端连接已中断 (IP: {client_ip})") # 客户端连接已中断
                        # No need to yield [DONE]
                    except httpx.HTTPStatusError as http_err: # 捕获 stream_chat 可能抛出的 HTTP 错误
                        status_code = http_err.response.status_code # 获取状态码
                        last_error = f"流式 API 错误: {status_code}" # 设置最后错误
                        logger.error(f"{last_error} - {http_err.response.text}", exc_info=False) # 记录错误
                        stream_error_occurred = True # 标记流错误发生

                        error_type = "api_error" # 默认错误类型
                        if status_code == 400:
                            error_message = "请求无效或格式错误，请检查您的输入。" # 错误消息
                            error_type = "invalid_request_error" # 错误类型
                        elif status_code == 401:
                            error_message = "API 密钥无效或认证失败。" # 错误消息
                            error_type = "authentication_error" # 错误类型
                        elif status_code == 403:
                            error_message = "API 密钥无权访问所请求的资源。" # 错误消息
                            error_type = "permission_error" # 错误类型
                        elif status_code == 429:
                            error_message = "请求频率过高或超出配额，请稍后重试。" # 错误消息
                            error_type = "rate_limit_error" # 错误类型
                            logger.warning(f"流式请求遇到 429 错误 (Key: {current_api_key[:8]}...): {error_message}") # 流式请求遇到 429 错误

                            # 尝试解析 429 错误详情，判断是否为每日配额耗尽
                            try:
                                error_detail = http_err.response.json() # 获取 JSON 格式的错误详情
                                is_daily_quota_error = False # 初始化标记
                                if error_detail and "error" in error_detail and "details" in error_detail["error"]: # 检查结构
                                    for detail in error_detail["error"]["details"]: # 遍历详情列表
                                        if detail.get("@type") == "type.googleapis.com/google.rpc/QuotaFailure": # 检查类型
                                            quota_id = detail.get("quotaId", "") # 获取 quotaId
                                            if "PerDay" in quota_id: # 检查是否包含 "PerDay"
                                                is_daily_quota_error = True # 标记为每日配额错误
                                                break # 找到即停止

                                if is_daily_quota_error and current_api_key: # 如果是每日配额错误且有当前 Key
                                    key_manager.mark_key_daily_exhausted(current_api_key) # 标记 Key 为当天耗尽
                                    logger.warning(f"Key {current_api_key[:8]}... 因每日配额耗尽被标记为当天不可用。") # 记录日志
                                    # 对于流式请求，标记错误后生成器会中断，外层循环会尝试下一个 Key

                            except json.JSONDecodeError: # 捕获 JSON 解析错误
                                logger.error("无法解析 429 错误的 JSON 响应体。") # 无法解析 429 错误的 JSON 响应体
                            except Exception as parse_e: # 捕获其他解析错误
                                logger.error(f"解析 429 错误详情时发生意外异常: {parse_e}") # 解析 429 错误详情时发生意外异常

                        elif status_code == 500:
                            error_message = "Gemini API 服务器内部错误，请稍后重试。" # 错误消息
                            error_type = "server_error" # 错误类型
                        elif status_code == 503:
                            error_message = "Gemini API 服务暂时不可用，请稍后重试。" # 错误消息
                            error_type = "service_unavailable_error" # 错误类型
                            error_message = "Gemini API 服务暂时不可用，请稍后重试。" # 错误消息
                            error_type = "service_unavailable_error" # 错误类型
                        else:
                            error_message = f"API 请求失败，状态码: {status_code}。请检查日志获取详情。" # 默认错误消息

                        # 发送错误信息给客户端并结束流
                        yield f"data: {json.dumps({'error': {'message': error_message, 'type': error_type, 'code': status_code}})}\n\n" # Yield 错误信息
                        yield "data: [DONE]\n\n" # Yield DONE 标记
                        return # 中断生成器

                    except Exception as stream_e: # 捕获流处理中捕获到的意外异常
                        last_error = f"流处理中捕获到意外异常: {stream_e}" # 设置最后错误
                        logger.error(last_error, exc_info=True) # 记录错误
                        stream_error_occurred = True # 标记流错误发生

                response = StreamingResponse(stream_generator(), media_type="text/event-stream") # 创建 StreamingResponse
                # 对于流式响应，我们假设它成功启动，直接返回。错误处理在生成器内部进行。
                # 如果 stream_generator 内部发生错误导致无法生成数据，客户端会收到中断的流。
                # 重试逻辑主要处理 API 调用本身的失败（例如密钥无效、网络问题）。
                # 如果流成功启动但中途因模型原因（如安全）中断，这不算是需要重试的错误。
                logger.info(f"流式响应已启动 (Key: {current_api_key[:8]})") # 流式响应已启动
                return response # 直接返回流式响应

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
                    return None # 不返回任何响应

                # Gemini 任务完成
                disconnect_task.cancel() # 取消断开连接检查任务
                try: await disconnect_task
                except asyncio.CancelledError: pass

                if gemini_task.exception(): # 如果 Gemini 任务抛出异常
                    # 如果 Gemini 任务本身抛出异常（例如 API 调用失败）
                    exc = gemini_task.exception() # 获取异常

                    # 检查是否为 HTTPStatusError 且状态码为 429
                    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429: # 如果是 HTTPStatusError 且状态码为 429
                        logger.warning(f"非流式请求遇到 429 错误 (Key: {current_api_key[:8]}...): {exc.response.text}") # 非流式请求遇到 429 错误
                        # 尝试解析 429 错误详情，判断是否为每日配额耗尽
                        try:
                            error_detail = exc.response.json() # 获取 JSON 格式的错误详情
                            is_daily_quota_error = False # 初始化标记
                            if error_detail and "error" in error_detail and "details" in error_detail["error"]: # 检查结构
                                for detail in error_detail["error"]["details"]: # 遍历详情列表
                                    if detail.get("@type") == "type.googleapis.com/google.rpc/QuotaFailure": # 检查类型
                                        quota_id = detail.get("quotaId", "") # 获取 quotaId
                                        if "PerDay" in quota_id: # 检查是否包含 "PerDay"
                                            is_daily_quota_error = True # 标记为每日配额错误
                                            break # 找到即停止

                            if is_daily_quota_error and current_api_key: # 如果是每日配额错误且有当前 Key
                                key_manager.mark_key_daily_exhausted(current_api_key) # 标记 Key 为当天耗尽
                                logger.warning(f"Key {current_api_key[:8]}... 因每日配额耗尽被标记为当天不可用。") # 记录日志
                                # 对于非流式请求，标记错误后，外层循环会尝试下一个 Key
                                continue # 跳到下一次循环尝试下一个 Key

                        except json.JSONDecodeError: # 捕获 JSON 解析错误
                            logger.error("无法解析 429 错误的 JSON 响应体。") # 无法解析 429 错误的 JSON 响应体
                        except Exception as parse_e: # 捕获其他解析错误
                            logger.error(f"解析 429 错误详情时发生意外异常: {parse_e}") # 解析 429 错误详情时发生意外异常

                    raise exc # 将异常传递给外层 try-except 处理 (对于非每日配额的 429 或其他错误)

                # 获取 Gemini 任务结果
                response_content: ResponseWrapper = gemini_task.result() # 获取任务结果

                # --- OpenAI API 兼容性处理 ---
                assistant_content = response_content.text if response_content else "" # 获取助手回复内容
                finish_reason = response_content.finish_reason if response_content else "stop" # 获取完成原因

                if not response_content or not assistant_content: # 如果响应内容为空或助手回复为空
                    if finish_reason != "STOP": # 如果完成原因不是 STOP
                        last_error = f"Gemini API 返回空响应或被阻止。完成原因: {finish_reason}" # 设置最后错误
                        logger.warning(f"{last_error} (Key: {current_api_key[:8]})") # Gemini API 返回空响应或被阻止
                        if finish_reason == "SAFETY": # 如果完成原因不是 SAFETY
                            key_manager.mark_key_issue(current_api_key, "safety_block") # 标记 Key 问题
                        continue # 标记错误并尝试下一个 Key
                    else:
                        logger.warning(f"Gemini API 返回 STOP 但文本为空 (Key: {current_api_key[:8]})。提供空助手消息。") # Gemini API 返回 STOP 但文本为空
                        assistant_content = "" # 确保有空字符串

                # 处理工具调用
                final_tool_calls = None # 初始化最终工具调用
                raw_gemini_tool_calls = getattr(response_content, 'tool_calls', None) # 获取原始 Gemini 工具调用
                if raw_gemini_tool_calls: # 如果有原始工具调用
                     logger.info("处理 Gemini 返回的工具调用...") # 处理 Gemini 返回的工具调用
                     final_tool_calls = process_tool_calls(raw_gemini_tool_calls) # 处理工具调用
                     if final_tool_calls: logger.info(f"已处理的工具调用: {final_tool_calls}") # 已处理的工具调用
                     else: logger.warning("process_tool_calls 返回 None 或空列表。") # process_tool_calls 返回 None 或空列表

                # 构建最终响应
                response = ChatCompletionResponse( # 构建 ChatCompletionResponse
                    id=f"chatcmpl-{int(time.time() * 1000)}", # 更唯一的 ID
                    object="chat.completion", # 对象类型
                    created=int(time.time()), # 创建时间
                    model=chat_request.model, # 模型名称
                    choices=[{ # 选项列表
                        "index": 0,
                        "message": ResponseMessage(role="assistant", content=assistant_content, tool_calls=final_tool_calls), # 助手消息
                        "finish_reason": finish_reason # 完成原因
                    }],
                    # usage 字段可以尝试从 response_content.usage_metadata 填充
                    usage={ # 使用情况
                        "prompt_tokens": response_content.prompt_token_count or 0,
                        "completion_tokens": response_content.candidates_token_count or 0,
                        "total_tokens": response_content.total_token_count or 0
                    } if response_content and response_content.usage_metadata else None # 如果有使用情况元数据则填充
                )

                logger.info(f"非流式请求处理成功 (Key: {current_api_key[:8]})") # 非流式请求处理成功

                # --- 处理 Token 计数（成功情况）---
                if response_content and response_content.usage_metadata: # 确保有使用情况元数据
                    prompt_tokens = response_content.usage_metadata.get('promptTokenCount') # 获取 prompt_tokens
                    # completion_tokens = response_content.usage_metadata.get('candidatesTokenCount') # 获取 completion_tokens
                    # total_tokens = response_content.usage_metadata.get('totalTokenCount') # 获取 total_tokens
                    update_token_counts(current_api_key, model_name, limits, prompt_tokens, client_ip, today_date_str_pt) # 更新 token 计数
                else:
                    logger.warning(f"非流式响应成功但没有使用情况元数据 (Key: {current_api_key[:8]}...). Token 计数未更新。") # 非流式响应成功但没有使用情况元数据

                # --- 成功处理后保存上下文 ---
                if enable_context: # 仅在启用了上下文补全时保存
                    logger.debug(f"准备为 Key '{proxy_key[:8]}...' 保存非流式上下文 (内存模式: {db_utils.IS_MEMORY_DB})") # 准备保存非流式上下文
                    # 1. 构建模型回复部分
                    # 对于非流式，assistant_content 已经是完整回复
                    model_reply_part = {"role": "model", "parts": [{"text": assistant_content}]} # 构建模型回复部分
                    # 如果有工具调用，也添加到模型回复中
                    if final_tool_calls:
                         model_reply_part["tool_calls"] = final_tool_calls # 添加工具调用

                    # 2. 合并上下文
                    final_contents_to_save = contents_to_send + [model_reply_part] # 合并内容
                    # 3. 再次截断
                    truncated_contents_to_save, still_over_limit_final = truncate_context(final_contents_to_save, chat_request.model) # 再次截断
                    # 4. 保存 (如果不超限)
                    if not still_over_limit_final: # 如果最终未超限
                         # 使用原始的 proxy_key 保存上下文
                         try:
                             await context_store.save_context(proxy_key, truncated_contents_to_save) # 添加 await # 保存上下文
                             logger.info(f"非流式上下文保存成功 for Key {proxy_key[:8]}...") # 非流式上下文保存成功
                         except Exception as e:
                             logger.error(f"保存非流式上下文失败 (Key: {proxy_key[:8]}...): {str(e)}") # 保存非流式上下文失败
                    else:
                         # 这种情况应该很少见，如果初始截断正确的话
                         logger.error(f"非流式上下文在添加回复并再次截断后仍然超限 (Key: {proxy_key[:8]}...). 上下文未保存。") # 非流式上下文在添加回复并再次截断后仍然超限
                else:
                    logger.debug(f"Key {proxy_key[:8]}... 的上下文补全已禁用，跳过非流式上下文保存。") # 上下文补全已禁用，跳过非流式上下文保存

                # 如果成功，返回响应
                return response # 返回响应

        except httpx.HTTPStatusError as http_err: # 捕获 API 调用尝试中的 HTTP 错误
            status_code = http_err.response.status_code # 获取状态码
            error_message = handle_gemini_error(http_err, current_api_key, key_manager) # 处理错误并获取消息
            last_error = error_message # 记录最后错误

            if status_code == 429: # 如果是速率限制错误
                logger.warning(f"API 请求遇到 429 错误 (Key: {current_api_key[:8]}..., 尝试 {attempt}/{retry_attempts})。等待后重试...") # 记录 429 警告
                # 计算等待时间（指数退避 + 随机抖动）
                wait_time = min(60, 2 ** attempt) + random.uniform(0, 1) # 最大等待 60 秒
                logger.info(f"等待 {wait_time:.2f} 秒后重试...") # 记录等待时间
                await asyncio.sleep(wait_time) # 等待
                continue # 继续下一次重试循环
            else:
                # 非 429 错误，重新抛出让外层处理
                raise http_err

        except Exception as e: # 捕获 API 调用尝试中的其他异常
            error_message = handle_gemini_error(e, current_api_key, key_manager) # 处理错误并获取消息
            last_error = error_message # 记录最后错误
            logger.warning(f"API 调用尝试 {attempt}/{retry_attempts} 失败 (Key: {current_api_key[:8]}...): {error_message}")

            # 如果是最后一个 Key 尝试失败，或者 Key Manager 中已经没有 Key 了，则不再重试
    # 如果所有重试都失败了
    if last_error:
        logger.error(f"所有重试尝试失败。最后错误: {last_error}") # 所有重试尝试失败
        # 如果最后一个错误是 429，抛出特定的 HTTPException
        if "429" in last_error:
             raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="API 请求频率过高或超出配额，请稍后重试。") # 引发 429 异常
        else:
             # 对于其他错误，抛出通用的 500 异常
             raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"API 请求失败: {last_error}") # 引发 500 异常
    else:
        # 这不应该发生，除非 active_keys_count 为 0 且没有进入循环
        logger.error("请求处理结束，但没有成功响应且没有记录错误。") # 请求处理结束，但没有成功响应且没有记录错误
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="请求处理失败，没有可用的 API 密钥或发生未知错误。") # 引发 500 异常
