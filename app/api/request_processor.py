# -*- coding: utf-8 -*-
"""
核心请求处理逻辑，包括流式和非流式处理、上下文管理（待实现）、错误处理等。
"""
import asyncio
import json
import logging
import time
import pytz
from datetime import datetime
from typing import Literal, List, Tuple, Dict, Any, Optional, Union
from fastapi import HTTPException, Request, status
from fastapi.responses import StreamingResponse
from collections import Counter, defaultdict # Counter 用于 IP 统计
import httpx

# 相对导入
from .models import ChatCompletionRequest, ChatCompletionResponse, ResponseMessage # ResponseMessage 用于保存上下文
from ..core.gemini import GeminiClient
from ..core.response_wrapper import ResponseWrapper
# 导入上下文存储和请求工具
from ..core import context_store
from ..core import db_utils # 导入 db_utils 以检查内存模式
from .request_utils import get_client_ip, get_current_timestamps, estimate_token_count, truncate_context # 导入新的工具函数
from ..core.message_converter import convert_messages
from ..core.utils import handle_gemini_error, protect_from_abuse, StreamProcessingError
from ..core.utils import key_manager_instance as key_manager # 导入共享实例
from .request_utils import get_client_ip, get_current_timestamps # 新增导入
from .. import config # 导入根配置
from ..config import ( # 导入具体配置项
    DISABLE_SAFETY_FILTERING,
    MAX_REQUESTS_PER_MINUTE,
    STREAM_SAVE_REPLY, # 新增：导入流式保存配置
    MAX_REQUESTS_PER_DAY_PER_IP,
    safety_settings,
    safety_settings_g2
)
from ..core.tracking import ( # 导入跟踪相关
    usage_data, usage_lock, RPM_WINDOW_SECONDS, TPM_WINDOW_SECONDS,
    ip_daily_input_token_counts, ip_input_token_counts_lock
)
from ..handlers.log_config import format_log_message

logger = logging.getLogger('my_logger')

# --- 核心请求处理函数 ---

async def process_request(
    chat_request: ChatCompletionRequest,
    http_request: Request,
    request_type: Literal['stream', 'non-stream'],
    proxy_key: str # 新增参数，由认证依赖注入
) -> Optional[Union[StreamingResponse, ChatCompletionResponse]]:
    """
    聊天补全（流式和非流式）的核心请求处理函数。
    包括密钥选择、速率限制检查、API 调用尝试和响应处理。
    未来将加入上下文管理逻辑。

    Args:
        chat_request: 包含聊天请求数据的 Pydantic 模型。
        http_request: FastAPI Request 对象，用于获取 IP 和检查断开连接。
        request_type: 'stream' 或 'non-stream'。

    Returns:
        流式请求返回 StreamingResponse，
        非流式请求返回 ChatCompletionResponse，
        如果客户端断开连接或早期发生不可重试的错误，则返回 None。

    Raises:
        HTTPException: For user errors (e.g., bad input) or final processing errors.
    """
    # --- 获取客户端 IP 和时间戳 ---
    client_ip = get_client_ip(http_request)
    cst_time_str, today_date_str_pt = get_current_timestamps()

    # --- 记录请求入口日志 ---
    logger.info(f"处理来自 IP: {client_ip} 的请求 ({request_type})，模型: {chat_request.model}，时间: {cst_time_str}")

    # --- 防滥用保护 ---
    try:
        protect_from_abuse(http_request, MAX_REQUESTS_PER_MINUTE, MAX_REQUESTS_PER_DAY_PER_IP)
    except HTTPException as e:
        logger.warning(f"IP {client_ip} 的请求被阻止 (防滥用): {e.detail}")
        raise e # 重新抛出防滥用异常

    if not chat_request.messages:
        logger.warning(f"Request from IP: {client_ip} (Key: {proxy_key[:8]}...) has empty messages list")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="消息列表不能为空")

    # --- 模型列表检查 (如果需要) ---
    # 保持在 endpoints.py 中，因为它更像是路由级别的检查
    # 此处假设模型已验证

    # --- 上下文管理 ---
    # 1. 加载历史上下文
    history_contents: Optional[List[Dict[str, Any]]] = await context_store.load_context(proxy_key) # 添加 await
    logger.info(f"Loaded {len(history_contents) if history_contents else 0} historical messages for Key {proxy_key[:8]}...")

    # 2. 转换当前请求中的新消息
    conversion_result = convert_messages(chat_request.messages, use_system_prompt=True)
    if isinstance(conversion_result, list): # 转换错误
        error_msg = "; ".join(conversion_result)
        logger.error(f"消息转换失败 (Key: {proxy_key[:8]}...): {error_msg}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"消息转换失败: {error_msg}")
    new_contents, system_instruction = conversion_result # system_instruction 仅来自当前请求

    # 3. 合并历史记录和新消息
    merged_contents = (history_contents or []) + new_contents
    if not merged_contents:
         logger.error(f"Merged message list is empty (Key: {proxy_key[:8]}...)")
         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot process empty message list")

    # 4. 在发送到 API 之前截断合并后的上下文
    contents_to_send, is_over_limit_after_truncate = truncate_context(merged_contents, chat_request.model)

    # 处理截断后仍超限的情况（例如单个长消息）
    if is_over_limit_after_truncate:
         logger.error(f"Context exceeds token limit for model {chat_request.model} even after truncation (Key: {proxy_key[:8]}...)")
         raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=f"Request content exceeds processing capacity for model {chat_request.model}. Please shorten the input.")

    # 处理截断后列表为空的情况（如果输入验证正确则不应发生）
    if not contents_to_send:
         logger.error(f"Message list became empty after truncation (Key: {proxy_key[:8]}...)")
         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Processed message list is empty")

    # 使用可能被截断的上下文进行 API 调用
    contents = contents_to_send # 重命名以便在函数其余部分使用

    # --- 请求处理循环 ---
    key_manager.reset_tried_keys_for_request()
    last_error = None
    response = None
    current_api_key = None
    gemini_client_instance = None # 在循环外初始化

    active_keys_count = key_manager.get_active_keys_count()
    retry_attempts = active_keys_count if active_keys_count > 0 else 1

    for attempt in range(1, retry_attempts + 1):
        # --- 智能 Key 选择 ---
        current_api_key = key_manager.select_best_key(chat_request.model, config.MODEL_LIMITS)

        if current_api_key is None:
            log_msg_no_key = format_log_message('WARNING', f"尝试 {attempt}/{retry_attempts}：无法选择合适的 API 密钥，结束重试。", extra={'request_type': request_type, 'model': chat_request.model, 'ip': client_ip})
            logger.warning(log_msg_no_key)
            break # 结束重试循环

        key_manager.tried_keys_for_request.add(current_api_key)
        extra_log = {'key': current_api_key[:8], 'request_type': request_type, 'model': chat_request.model, 'ip': client_ip, 'attempt': attempt}
        log_msg = format_log_message('INFO', f"第 {attempt}/{retry_attempts} 次尝试，选择密钥: {current_api_key[:8]}...", extra=extra_log)
        logger.info(log_msg)

        # --- 模型速率限制预检查 ---
        # TODO: 考虑将此检查移至 request_utils.py
        model_name = chat_request.model
        limits = config.MODEL_LIMITS.get(model_name)
        perform_api_call = True
        if limits:
            now = time.time()
            with usage_lock:
                key_usage = usage_data.setdefault(current_api_key, defaultdict(lambda: defaultdict(int)))[model_name]

                # 检查 RPD
                rpd_limit = limits.get("rpd")
                if rpd_limit is not None and key_usage.get("rpd_count", 0) >= rpd_limit:
                    logger.warning(f"预检查失败 (Key: {current_api_key[:8]}, Model: {model_name}): RPD 达到限制 ({key_usage.get('rpd_count', 0)}/{rpd_limit})。跳过此 Key。")
                    perform_api_call = False
                # 检查 TPD_Input
                if perform_api_call:
                    tpd_input_limit = limits.get("tpd_input")
                    if tpd_input_limit is not None and key_usage.get("tpd_input_count", 0) >= tpd_input_limit:
                        logger.warning(f"预检查失败 (Key: {current_api_key[:8]}, Model: {model_name}): TPD_Input 达到限制 ({key_usage.get('tpd_input_count', 0)}/{tpd_input_limit})。跳过此 Key。")
                        perform_api_call = False
                # 检查 RPM
                if perform_api_call:
                    rpm_limit = limits.get("rpm")
                    if rpm_limit is not None:
                        if now - key_usage.get("rpm_timestamp", 0) < RPM_WINDOW_SECONDS:
                            if key_usage.get("rpm_count", 0) >= rpm_limit:
                                 logger.warning(f"预检查失败 (Key: {current_api_key[:8]}, Model: {model_name}): RPM 达到限制 ({key_usage.get('rpm_count', 0)}/{rpm_limit})。跳过此 Key。")
                                 perform_api_call = False
                        else:
                            key_usage["rpm_count"] = 0
                            key_usage["rpm_timestamp"] = 0 # 重置时间戳
                # 检查 TPM_Input
                if perform_api_call:
                    tpm_input_limit = limits.get("tpm_input")
                    if tpm_input_limit is not None:
                        if now - key_usage.get("tpm_input_timestamp", 0) < TPM_WINDOW_SECONDS:
                             if key_usage.get("tpm_input_count", 0) >= tpm_input_limit:
                                 logger.warning(f"预检查失败 (Key: {current_api_key[:8]}, Model: {model_name}): TPM_Input 达到限制 ({key_usage.get('tpm_input_count', 0)}/{tpm_input_limit})。跳过此 Key。")
                                 perform_api_call = False
                        else:
                            key_usage["tpm_input_count"] = 0
                            key_usage["tpm_input_timestamp"] = 0 # 重置时间戳

            if not perform_api_call:
                continue # 跳过此 Key，尝试下一个

            # --- 预检查通过，增加计数 ---
            with usage_lock:
                key_usage = usage_data[current_api_key][model_name]
                # 更新 RPM
                if now - key_usage.get("rpm_timestamp", 0) >= RPM_WINDOW_SECONDS:
                    key_usage["rpm_count"] = 1
                    key_usage["rpm_timestamp"] = now
                else:
                    key_usage["rpm_count"] = key_usage.get("rpm_count", 0) + 1
                # 更新 RPD
                key_usage["rpd_count"] = key_usage.get("rpd_count", 0) + 1
                # 更新最后请求时间戳
                key_usage["last_request_timestamp"] = now
                logger.debug(f"计数增加 (Key: {current_api_key[:8]}, Model: {model_name}): RPM={key_usage['rpm_count']}, RPD={key_usage['rpd_count']}")
        else:
             logger.warning(f"模型 '{model_name}' 不在 model_limits.json 中，跳过本地速率限制检查。")


        # --- API 调用尝试 ---
        try:
            # 确定安全设置
            current_safety_settings = safety_settings_g2 if DISABLE_SAFETY_FILTERING or 'gemini-2.0-flash-exp' in chat_request.model else safety_settings
            # 创建 GeminiClient 实例
            gemini_client_instance = GeminiClient(current_api_key)

            # --- 流式 vs 非流式 ---
            if chat_request.stream:
                # --- 流式处理 ---
                async def stream_generator():
                    nonlocal last_error, current_api_key, model_name, client_ip, today_date_str_pt, limits # 引用外部变量
                    stream_error_occurred = False
                    assistant_message_yielded = False
                    full_reply_content = "" # 新增：用于累积回复内容
                    usage_metadata_received = None
                    actual_finish_reason = "stop"
                    response_id = f"chatcmpl-{int(time.time() * 1000)}" # 更唯一的 ID

                    try:
                        async for chunk in gemini_client_instance.stream_chat(chat_request, contents, current_safety_settings, system_instruction):
                            if isinstance(chunk, dict):
                                if '_usage_metadata' in chunk:
                                    usage_metadata_received = chunk['_usage_metadata']
                                    logger.debug(f"流接收到 usage metadata: {usage_metadata_received}")
                                    continue
                                if '_final_finish_reason' in chunk:
                                    actual_finish_reason = chunk['_final_finish_reason']
                                    logger.debug(f"流接收到最终完成原因: {actual_finish_reason}")
                                    continue
                                # 可以添加对其他元数据块的处理

                            # 检查是否是错误信息（例如内部处理错误）
                            if isinstance(chunk, str) and chunk.startswith("[ERROR]"):
                                logger.error(f"流处理内部错误: {chunk}")
                                last_error = chunk # 记录错误供外部重试判断
                                stream_error_occurred = True
                                break # 停止处理此流

                            # 格式化标准文本块
                            formatted_chunk = {
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
                            yield f"data: {json.dumps(formatted_chunk)}\n\n"
                            if isinstance(chunk, str) and chunk: # 仅在有实际文本时标记
                                assistant_message_yielded = True
                                full_reply_content += chunk # 累积回复内容

                        # --- 流结束处理 ---
                        if not stream_error_occurred:
                            # 如果没有产生任何助手消息，根据完成原因发送结束块
                            if not assistant_message_yielded:
                                logger.warning(f"流结束时未产生助手内容 (完成原因: {actual_finish_reason})。发送结束块。")
                                end_chunk = {
                                    "id": response_id,
                                    "object": "chat.completion.chunk",
                                    "created": int(time.time()),
                                    "model": chat_request.model,
                                    "choices": [{"delta": {}, "index": 0, "finish_reason": actual_finish_reason}] # delta 为空
                                }
                                yield f"data: {json.dumps(end_chunk)}\n\n"
                            else:
                                # 如果已产生内容，发送一个只有 finish_reason 的结束块
                                end_chunk = {
                                    "id": response_id,
                                    "object": "chat.completion.chunk",
                                    "created": int(time.time()),
                                    "model": chat_request.model,
                                    "choices": [{"delta": {}, "index": 0, "finish_reason": actual_finish_reason}]
                                }
                                yield f"data: {json.dumps(end_chunk)}\n\n"

                            yield "data: [DONE]\n\n"

                            # --- 处理 Token 计数（成功情况）---
                            # TODO: 考虑将 Token 计数逻辑移至 request_utils.py
                            if limits and usage_metadata_received:
                                prompt_tokens = usage_metadata_received.get('promptTokenCount', 0)
                                # completion_tokens = usage_metadata_received.get('candidatesTokenCount', 0) # 输出 token 在流式中不直接用于速率限制
                                if prompt_tokens > 0:
                                    with usage_lock:
                                        key_usage = usage_data[current_api_key][model_name]
                                        # 更新 TPD_Input
                                        key_usage["tpd_input_count"] = key_usage.get("tpd_input_count", 0) + prompt_tokens
                                        # 更新 TPM_Input
                                        tpm_input_limit = limits.get("tpm_input")
                                        if tpm_input_limit is not None:
                                            now_tpm = time.time()
                                            if now_tpm - key_usage.get("tpm_input_timestamp", 0) >= TPM_WINDOW_SECONDS:
                                                key_usage["tpm_input_count"] = prompt_tokens
                                                key_usage["tpm_input_timestamp"] = now_tpm
                                            else:
                                                key_usage["tpm_input_count"] = key_usage.get("tpm_input_count", 0) + prompt_tokens
                                            logger.debug(f"输入 Token 计数更新 (Key: {current_api_key[:8]}, Model: {model_name}): Added TPD_Input={prompt_tokens}, TPM_Input={key_usage['tpm_input_count']}")
                                    # 记录 IP 输入 Token 消耗
                                    with ip_input_token_counts_lock:
                                        ip_daily_input_token_counts.setdefault(today_date_str_pt, Counter())[client_ip] += prompt_tokens
                                else:
                                     logger.warning(f"Stream response successful but no valid prompt token count received (Key: {current_api_key[:8]}...): {usage_metadata_received}")

                            # --- 成功流式传输后保存上下文（可配置）---
                            if not config.STREAM_SAVE_REPLY:
                                # 默认行为：只保存到用户最后输入（更稳健，流中断也能保存）
                                logger.info(f"Stream finished successfully for Key {proxy_key[:8]}.... Saving context up to user's last input (STREAM_SAVE_REPLY=false).")
                                logger.debug(f"准备为 Key '{proxy_key[:8]}...' 保存流式上下文 (不含回复) (内存模式: {db_utils.IS_MEMORY_DB})")
                                try:
                                    await context_store.save_context(proxy_key, contents_to_send) # 添加 await
                                except Exception as e:
                                    logger.error(f"保存流式上下文 (不含回复) 失败 (Key: {proxy_key[:8]}...): {str(e)}")
                            else:
                                # 配置为保存回复：在流结束后保存完整对话（流中断则不保存）
                                if assistant_message_yielded: # 仅在有回复时保存
                                    logger.info(f"Stream finished successfully for Key {proxy_key[:8]}.... Saving context including model reply (STREAM_SAVE_REPLY=true).")
                                    # 1. 构建模型回复部分
                                    model_reply_part = {"role": "model", "parts": [{"text": full_reply_content}]}
                                    # 2. 合并上下文
                                    final_contents_to_save = contents_to_send + [model_reply_part]
                                    # 3. 再次截断
                                    truncated_contents_to_save, still_over_limit_final = truncate_context(final_contents_to_save, chat_request.model)
                                    # 4. 保存 (如果不超限)
                                    if not still_over_limit_final:
                                        logger.debug(f"准备为 Key '{proxy_key[:8]}...' 保存流式上下文 (含回复) (内存模式: {db_utils.IS_MEMORY_DB})")
                                        try:
                                            await context_store.save_context(proxy_key, truncated_contents_to_save) # 添加 await
                                            logger.info(f"流式上下文 (含回复) 保存成功 for Key {proxy_key[:8]}...")
                                        except Exception as e:
                                            logger.error(f"保存流式上下文 (含回复) 失败 (Key: {proxy_key[:8]}...): {str(e)}")
                                    else:
                                        logger.error(f"流式上下文在添加回复并再次截断后仍然超限 (Key: {proxy_key[:8]}...). 上下文未保存。")
                                else:
                                     logger.warning(f"Stream finished successfully but no assistant message was yielded (Key: {proxy_key[:8]}...). No context saved for this interaction (STREAM_SAVE_REPLY=true).")

                    except asyncio.CancelledError:
                        logger.info(f"客户端连接已中断 (IP: {client_ip})")
                        # 不需要 yield [DONE]
                    except httpx.HTTPStatusError as http_err: # 捕获 stream_chat 可能抛出的 HTTP 错误
                        status_code = http_err.response.status_code
                        last_error = f"流式 API 错误: {status_code}"
                        logger.error(f"{last_error} - {http_err.response.text}", exc_info=False)
                        stream_error_occurred = True

                        error_type = "api_error"
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
                            logger.warning(f"流式请求遇到 429 错误 (Key: {current_api_key[:8]}...): {error_message}")
                        elif status_code == 500:
                            error_message = "Gemini API 服务器内部错误，请稍后重试。"
                            error_type = "server_error"
                        elif status_code == 503:
                            error_message = "Gemini API 服务暂时不可用，请稍后重试。"
                            error_type = "service_unavailable_error"
                        else:
                            error_message = f"API 请求失败，状态码: {status_code}。请检查日志获取详情。"

                        # 发送错误信息给客户端并结束流
                        yield f"data: {json.dumps({'error': {'message': error_message, 'type': error_type, 'code': status_code}})}\n\n"
                        yield "data: [DONE]\n\n"
                        return # 中断生成器

                    except Exception as stream_e:
                        last_error = f"流处理中捕获到意外异常: {stream_e}"
                        logger.error(last_error, exc_info=True)
                        stream_error_occurred = True
                        # 可以在这里 yield 一个错误消息给客户端，但标准做法是直接中断
                        # yield f"error: {json.dumps({'error': {'message': last_error, 'type': 'proxy_error'}})}\n\n"

                response = StreamingResponse(stream_generator(), media_type="text/event-stream")
                # 对于流式响应，我们假设它成功启动，直接返回。错误处理在生成器内部进行。
                # 如果 stream_generator 内部发生错误导致无法生成数据，客户端会收到中断的流。
                # 重试逻辑主要处理 API 调用本身的失败（例如密钥无效、网络问题）。
                # 如果流成功启动但中途因模型原因（如安全）中断，这不算是需要重试的错误。
                logger.info(f"流式响应已启动 (Key: {current_api_key[:8]})")
                return response # 直接返回流式响应

            else:
                # --- 非流式处理 ---
                async def run_gemini_completion():
                    return await gemini_client_instance.complete_chat(chat_request, contents, current_safety_settings, system_instruction)

                async def check_client_disconnect():
                    while True:
                        if await http_request.is_disconnected():
                            logger.warning(f"客户端连接中断 detected (IP: {client_ip})")
                            return True
                        await asyncio.sleep(0.5)

                gemini_task = asyncio.create_task(run_gemini_completion())
                disconnect_task = asyncio.create_task(check_client_disconnect())

                done, pending = await asyncio.wait(
                    [gemini_task, disconnect_task], return_when=asyncio.FIRST_COMPLETED
                )

                if disconnect_task in done:
                    gemini_task.cancel()
                    try: await gemini_task
                    except asyncio.CancelledError: logger.info("非流式 API 任务已成功取消")
                    logger.error(f"客户端连接中断 (IP: {client_ip})，终止请求处理。")
                    return None # 不返回任何响应

                # Gemini 任务完成
                disconnect_task.cancel()
                try: await disconnect_task
                except asyncio.CancelledError: pass

                if gemini_task.exception():
                    # 如果 Gemini 任务本身抛出异常（例如 API 调用失败）
                    exc = gemini_task.exception()
                    raise exc # 将异常传递给外层 try-except 处理

                # 获取 Gemini 任务结果
                response_content: ResponseWrapper = gemini_task.result()

                # --- OpenAI API 兼容性处理 ---
                assistant_content = response_content.text if response_content else ""
                finish_reason = response_content.finish_reason if response_content else "stop"

                if not response_content or not assistant_content:
                    if finish_reason != "STOP":
                        last_error = f"Gemini API 返回空响应或被阻止。完成原因: {finish_reason}"
                        logger.warning(f"{last_error} (Key: {current_api_key[:8]})")
                        if finish_reason == "SAFETY":
                            key_manager.mark_key_issue(current_api_key, "safety_block")
                        continue # 标记错误并尝试下一个 Key
                    else:
                        logger.warning(f"Gemini API 返回 STOP 但文本为空 (Key: {current_api_key[:8]})。提供空助手消息。")
                        assistant_content = "" # 确保有空字符串

                # 处理工具调用
                final_tool_calls = None
                raw_gemini_tool_calls = getattr(response_content, 'tool_calls', None)
                if raw_gemini_tool_calls:
                     logger.info("处理 Gemini 返回的工具调用...")
                     final_tool_calls = process_tool_calls(raw_gemini_tool_calls)
                     if final_tool_calls: logger.info(f"已处理的工具调用: {final_tool_calls}")
                     else: logger.warning("process_tool_calls 返回 None 或空列表。")

                # 构建最终响应
                response = ChatCompletionResponse(
                    id=f"chatcmpl-{int(time.time() * 1000)}", # 更唯一的 ID
                    object="chat.completion",
                    created=int(time.time()),
                    model=chat_request.model,
                    choices=[{
                        "index": 0,
                        "message": ResponseMessage(role="assistant", content=assistant_content, tool_calls=final_tool_calls),
                        "finish_reason": finish_reason
                    }],
                    # usage 字段可以尝试从 response_content.usage_metadata 填充
                    usage={
                        "prompt_tokens": response_content.prompt_token_count or 0,
                        "completion_tokens": response_content.candidates_token_count or 0,
                        "total_tokens": response_content.total_token_count or 0
                    } if response_content and response_content.usage_metadata else None
                )

                logger.info(f"非流式请求处理成功 (Key: {current_api_key[:8]})")

                # --- 处理 Token 计数（成功情况）---
                # TODO: 考虑移至 request_utils.py
                if limits and response_content and response_content.usage_metadata:
                    prompt_tokens = response_content.prompt_token_count
                    if prompt_tokens and prompt_tokens > 0:
                        with usage_lock:
                            key_usage = usage_data[current_api_key][model_name]
                            # 更新 TPD_Input
                            key_usage["tpd_input_count"] = key_usage.get("tpd_input_count", 0) + prompt_tokens
                            # 更新 TPM_Input
                            tpm_input_limit = limits.get("tpm_input")
                            if tpm_input_limit is not None:
                                now_tpm = time.time()
                                if now_tpm - key_usage.get("tpm_input_timestamp", 0) >= TPM_WINDOW_SECONDS:
                                    key_usage["tpm_input_count"] = prompt_tokens
                                    key_usage["tpm_input_timestamp"] = now_tpm
                                else:
                                    key_usage["tpm_input_count"] = key_usage.get("tpm_input_count", 0) + prompt_tokens
                                logger.debug(f"输入 Token 计数更新 (Key: {current_api_key[:8]}, Model: {model_name}): Added TPD_Input={prompt_tokens}, TPM_Input={key_usage['tpm_input_count']}")
                        # 记录 IP 输入 Token 消耗
                        with ip_input_token_counts_lock:
                            ip_daily_input_token_counts.setdefault(today_date_str_pt, Counter())[client_ip] += prompt_tokens
                    else:
                        logger.warning(f"Non-stream response successful but no valid prompt token count received (Key: {current_api_key[:8]}...): {response_content.usage_metadata}")
                elif limits:
                     logger.warning(f"Non-stream response successful but ResponseWrapper missing usage_metadata (Key: {current_api_key[:8]}...).")

                # --- 成功非流式响应后保存上下文（包括模型回复）---
                if assistant_content is not None: # 确保有模型内容（即使是空字符串）
                    # 1. 构建模型回复部分
                    model_reply_part = {"role": "model", "parts": [{"text": assistant_content}]}
                    # 2. 合并：将模型回复附加到发送给 API 的上下文中
                    final_contents_to_save = contents_to_send + [model_reply_part]
                    # 3. 再次截断（以防添加回复后超限，尽管如果初始截断有效则不太可能）
                    truncated_contents_to_save, still_over_limit_final = truncate_context(final_contents_to_save, chat_request.model)
                    # 4. 保存（仅当未超限时）
                    if not still_over_limit_final:
                        # 使用原始的 proxy_key 保存上下文
                        logger.debug(f"准备为 Key '{proxy_key[:8]}...' 保存非流式上下文 (内存模式: {db_utils.IS_MEMORY_DB})")
                        try:
                            await context_store.save_context(proxy_key, truncated_contents_to_save) # 添加 await
                        except Exception as e:
                            logger.error(f"保存上下文失败 (Key: {proxy_key[:8]}...): {str(e)}")
                        logger.info(f"上下文成功保存 for Key {proxy_key[:8]}...") # 记录实际使用的 Key
                    else:
                        # 这种情况应该很少见，如果初始截断正确的话
                        logger.error(f"添加模型回复并最终截断后上下文仍然超限 (Key: {proxy_key[:8]}...). 上下文未保存。")
                else:
                     logger.warning(f"非流式响应成功，但 assistant_content 为 None。无法将模型回复保存到上下文 (Key: {proxy_key[:8]}...).")

                return response # 成功，跳出重试循环

        # --- 处理 API 调用异常 ---
        except HTTPException as e:
            # 如果是消息转换失败，这是永久错误，直接抛出
            if e.status_code == status.HTTP_400_BAD_REQUEST and "消息转换失败" in e.detail:
                 logger.error(f"消息转换失败，终止重试。详情: {e.detail}")
                 raise e
            # 其他 HTTPException 可能与特定 Key 相关，记录并继续重试
            logger.warning(f"请求处理中遇到 HTTPException (状态码 {e.status_code})，尝试下一个 Key。详情: {e.detail}")
            last_error = f"HTTPException: {e.detail}"
            continue # 尝试下一个密钥

        except Exception as e:
            # 使用 handle_gemini_error 处理通用 API 错误
            last_error = handle_gemini_error(e, current_api_key, key_manager)
            logger.error(f"第 {attempt}/{retry_attempts} 次尝试失败 (Key: {current_api_key[:8]}): {last_error}", exc_info=True)
            # 继续下一次尝试
            continue

    # --- 重试循环结束 ---
    # 如果所有尝试都失败了
    if response is None: # 确保是在所有尝试失败后
        final_error_msg = last_error or "所有 API 密钥均尝试失败或无可用密钥"
        extra_log_fail = {'request_type': request_type, 'model': chat_request.model, 'error_message': final_error_msg, 'ip': client_ip}

        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR # 默认 500
        detail_msg = f"API 请求处理失败: {final_error_msg}" # 默认消息

        if last_error:
            # 尝试从 last_error 中提取或判断错误类型
            last_error_lower = last_error.lower()
            if "400" in last_error or "invalid" in last_error_lower or "bad request" in last_error_lower:
                status_code = status.HTTP_400_BAD_REQUEST
                detail_msg = "请求无效或格式错误，请检查您的输入。"
            elif "401" in last_error or "unauthorized" in last_error_lower or "authentication" in last_error_lower:
                status_code = status.HTTP_401_UNAUTHORIZED
                detail_msg = "API 密钥无效或认证失败。"
            elif "403" in last_error or "forbidden" in last_error_lower or "permission" in last_error_lower:
                status_code = status.HTTP_403_FORBIDDEN
                detail_msg = "API 密钥无权访问所请求的资源。"
            elif "429" in last_error or "rate_limit" in last_error_lower or "quota" in last_error_lower or "频率限制" in last_error:
                status_code = status.HTTP_429_TOO_MANY_REQUESTS
                detail_msg = "请求频率过高或超出配额，请稍后重试。"
            elif "500" in last_error or "internal server error" in last_error_lower:
                status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
                detail_msg = "Gemini API 服务器内部错误，请稍后重试。"
            elif "503" in last_error or "service unavailable" in last_error_lower:
                status_code = status.HTTP_503_SERVICE_UNAVAILABLE
                detail_msg = "Gemini API 服务暂时不可用，请稍后重试。"
            # 可以添加更多特定错误的判断

        # 记录最终错误日志
        log_level = logging.WARNING if status_code == 429 else logging.ERROR
        logger.log(log_level, f"请求处理最终失败 ({status_code}): {final_error_msg}", extra={**extra_log_fail, 'status_code': status_code})

        # 抛出最终的 HTTPException
        raise HTTPException(status_code=status_code, detail=detail_msg)


# --- 辅助函数 (例如处理工具调用) ---
# TODO: 考虑将此函数移至 request_utils.py
def process_tool_calls(gemini_tool_calls: Any) -> Optional[List[Dict[str, Any]]]:
    """
    将 Gemini 返回的 functionCall 列表转换为 OpenAI 兼容的 tool_calls 格式。
    Gemini: [{'functionCall': {'name': 'func_name', 'args': {...}}}]
    OpenAI: [{'id': 'call_...', 'type': 'function', 'function': {'name': 'func_name', 'arguments': '{...}'}}]
    """
    if not isinstance(gemini_tool_calls, list):
        logger.warning(f"期望 gemini_tool_calls 是列表，但得到 {type(gemini_tool_calls)}")
        return None

    openai_tool_calls = []
    for i, call in enumerate(gemini_tool_calls):
        if not isinstance(call, dict):
             logger.warning(f"工具调用列表中的元素不是字典: {call}")
             continue

        func_call = call # Gemini 直接返回 functionCall 字典

        if not isinstance(func_call, dict):
             logger.warning(f"functionCall 元素不是字典: {func_call}")
             continue

        func_name = func_call.get('name')
        func_args = func_call.get('args')

        if not func_name or not isinstance(func_args, dict):
            logger.warning(f"functionCall 缺少 name 或 args 不是字典: {func_call}")
            continue

        try:
            # OpenAI 需要 arguments 是 JSON 字符串
            arguments_str = json.dumps(func_args, ensure_ascii=False)
        except TypeError as e:
            logger.error(f"序列化工具调用参数失败 (Name: {func_name}): {e}", exc_info=True)
            continue # 跳过这个调用

        openai_tool_calls.append({
            "id": f"call_{int(time.time()*1000)}_{i}", # 生成唯一 ID
            "type": "function",
            "function": {
                "name": func_name,
                "arguments": arguments_str,
            }
        })

    return openai_tool_calls if openai_tool_calls else None