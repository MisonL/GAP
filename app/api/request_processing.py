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
    """
    if not api_key:
        return False

    try:
        error_detail = http_error.response.json()
        is_daily_quota_error = False
        if error_detail and "error" in error_detail and "details" in error_detail["error"]:
            for detail in error_detail["error"]["details"]:
                if detail.get("@type") == "type.googleapis.com/google.rpc/QuotaFailure":
                    quota_id = detail.get("quotaId", "")
                    if "PerDay" in quota_id:
                        is_daily_quota_error = True
                        break

        if is_daily_quota_error:
            key_manager.mark_key_daily_exhausted(api_key)
            logger.warning(f"Key {api_key[:8]}... 因每日配额耗尽被标记为当天不可用。")
            return True

    except json.JSONDecodeError:
        logger.error(f"无法解析 429 错误的 JSON 响应体 (Key: {api_key[:8]}...)")
    except Exception as parse_e:
        logger.error(f"解析 429 错误详情时发生意外异常 (Key: {api_key[:8]}...): {parse_e}")

    return False

async def _handle_http_error_in_attempt(
    http_err: httpx.HTTPStatusError,
    current_api_key: Optional[str],
    key_manager: APIKeyManager,
    is_stream: bool,
    request_id: Optional[str] = None
) -> Tuple[Dict[str, Any], bool]:
    """
    处理 _attempt_api_call 中发生的 httpx.HTTPStatusError。
    """
    logger.error(f"API HTTP 错误 ({'流式' if is_stream else '非流式'}, Key: {current_api_key[:8] if current_api_key else 'N/A'}): {http_err.response.status_code} - {http_err.response.text}", exc_info=False)
    error_info = _format_api_error(http_err, current_api_key, key_manager)
    needs_retry = False

    if http_err.response.status_code == 429:
        if _handle_429_daily_quota(http_err, current_api_key, key_manager):
            needs_retry = True
            error_info["message"] = f"Key {current_api_key[:8] if current_api_key else 'N/A'} 每日配额耗尽"
        # 非每日配额的 429 错误，不需要重试

    return error_info, needs_retry

async def _handle_api_call_exception(
    exc: Exception,
    current_api_key: Optional[str],
    key_manager: APIKeyManager,
    is_stream: bool,
    request_id: Optional[str] = None
) -> Tuple[Dict[str, Any], bool]:
    """
    处理 API 调用过程中发生的异常，格式化错误信息并判断是否需要重试。
    """
    needs_retry = False
    error_info: Dict[str, Any] = {
        "message": f"API 调用中发生意外异常: {exc}",
        "type": "internal_error",
        "code": 500
    }

    if isinstance(exc, httpx.HTTPStatusError):
        error_info, needs_retry = await _handle_http_error_in_attempt(exc, current_api_key, key_manager, is_stream)
    else:
        error_message = handle_gemini_error(exc, current_api_key, key_manager)
        logger.error(f"API 调用失败 ({'流式' if is_stream else '非流式'}, Key: {current_api_key[:8] if current_api_key else 'N/A'}): {error_message}", exc_info=True)
        error_info["message"] = error_message
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
    """
    if not enable_context:
        logger.debug(f"Key {proxy_key[:8]}... 的上下文补全已禁用，跳过上下文保存。")
        return

    logger.debug(f"准备为 Key '{proxy_key[:8]}...' 保存上下文 (内存模式: {db_utils.IS_MEMORY_DB})")

    model_reply_part = {"role": "model", "parts": [{"text": model_reply_content}]}
    if final_tool_calls:
        model_reply_part["tool_calls"] = final_tool_calls
    final_contents_to_save = contents_to_send + [model_reply_part]

:start_line:209
-------
    # 保存上下文时，仅使用模型的静态限制进行截断。
    # 动态截断（基于 Key 实时容量）主要用于发送给 API 的请求内容。
    truncated_contents_to_save, still_over_limit_final = truncate_context(final_contents_to_save, model_name) # 保存时仅使用静态限制

    if not still_over_limit_final:
        try:
            await context_store.save_context(proxy_key, truncated_contents_to_save)
            logger.info(f"上下文保存成功 for Key {proxy_key[:8]}...")
        except Exception as e:
            logger.error(f"保存上下文失败 (Key: {proxy_key[:8]}...): {str(e)}")
    else:
        logger.error(f"上下文在添加回复并再次截断后仍然超限 (Key: {proxy_key[:8]}...). 上下文未保存。")

async def _handle_stream_end(
    response_id: str,
    assistant_message_yielded: bool,
    actual_finish_reason: str,
    safety_issue_detail_received: Optional[Dict[str, Any]]
):
    """
    处理流式响应结束时的逻辑，发送结束块或错误块。
    """
    if not assistant_message_yielded:
        if actual_finish_reason == "STOP":
            if safety_issue_detail_received:
                error_message_detail = f"模型因安全策略停止生成内容。详情: {safety_issue_detail_received}"
                logger.warning(f"流结束时未产生助手内容，完成原因是 STOP，但检测到安全问题。向客户端发送安全提示。详情: {safety_issue_detail_received}")
                error_code = "safety_block"
                error_type = "model_error"
            else:
                error_message_detail = f"模型返回 STOP 但未生成任何内容。可能是由于输入问题或模型内部错误。完成原因: {actual_finish_reason}"
                logger.error(f"流结束时未产生助手内容，但完成原因是 STOP。向客户端发送错误。")
                error_code = "empty_response"
                error_type = "model_error"

            error_payload = {
                "error": {
                    "message": error_message_detail,
                    "type": error_type,
                    "code": error_code
                }
            }
            yield f"data: {json.dumps(error_payload)}\n\n"
        else:
            logger.warning(f"流结束时未产生助手内容 (完成原因: {actual_finish_reason})。发送结束块。")
            end_chunk = {
                "id": response_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": "ignored",
                "choices": [{"delta": {}, "index": 0, "finish_reason": actual_finish_reason}]
            }
            yield f"data: {json.dumps(end_chunk)}\n\n"
    # 检查是否已产生助手消息，并累积回复内容
    # 这段逻辑应该在 stream_generator 内部，而不是 _handle_stream_end 内部
    # if isinstance(chunk, str) and chunk:
    #     assistant_message_yielded = True
    #     full_reply_content += chunk

    yield "data: [DONE]\n\n"

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
    retry_attempts: int,
    request_id: Optional[str] = None
) -> Tuple[Optional[Union[StreamingResponse, ChatCompletionResponse]], Optional[str], bool]:
    """
    尝试使用给定的 API Key 进行一次 API 调用。
    """
    last_error = None
    response = None
    needs_retry = False

    try:
        current_safety_settings = safety_settings_g2 if config.DISABLE_SAFETY_FILTERING or 'gemini-2.0-flash-exp' in chat_request.model else safety_settings
        gemini_client_instance = GeminiClient(current_api_key, http_client)

        if chat_request.stream:
            async def stream_generator():
                stream_error_occurred = False
                assistant_message_yielded = False
                full_reply_content = ""
                usage_metadata_received = None
                actual_finish_reason = "stop"
                safety_issue_detail_received = None
                response_id = f"chatcmpl-{int(time.time() * 1000)}"

                try:
                    async for chunk in gemini_client_instance.stream_chat(chat_request, contents, current_safety_settings, system_instruction):
                        if isinstance(chunk, dict):
                            if '_usage_metadata' in chunk:
                                usage_metadata_received = chunk['_usage_metadata']
                                logger.debug(f"流接收到 usage metadata: {usage_metadata_received}")
                                continue
                            elif '_final_finish_reason' in chunk:
                                actual_finish_reason = chunk['_final_finish_reason']
                                logger.debug(f"流接收到最终完成原因: {actual_finish_reason}")
                                continue
                            elif '_safety_issue' in chunk:
                                safety_issue_detail_received = chunk['_safety_issue']
                                logger.warning(f"流接收到安全问题详情: {safety_issue_detail_received}")
                                continue

                        elif isinstance(chunk, str) and chunk.startswith("[ERROR]"):
                            logger.error(f"流处理内部错误: {chunk}")
                            stream_error_occurred = True
                            break

                        formatted_chunk = {
                            "id": response_id,
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": chat_request.model,
                            "choices": [{
                                "delta": {"role": "assistant", "content": chunk if isinstance(chunk, str) else ""},
                                "index": 0,
                                "finish_reason": None
                            }]
                        }
                        yield f"data: {json.dumps(formatted_chunk)}\n\n"
                        if isinstance(chunk, str) and chunk:
                            assistant_message_yielded = True
                            full_reply_content += chunk

                    if not stream_error_occurred:
                        async for end_chunk_data in _handle_stream_end(
                            response_id,
                            assistant_message_yielded,
                            actual_finish_reason,
                            safety_issue_detail_received
                        ):
                            yield end_chunk_data

                        if usage_metadata_received:
                            prompt_tokens = usage_metadata_received.get('promptTokenCount')
                            update_token_counts(current_api_key, model_name, limits, prompt_tokens, client_ip, today_date_str_pt)
                        else:
                            logger.warning(f"Stream response successful but no usage metadata found (Key: {current_api_key[:8]}...). Token counts not updated.")

                        await _save_context_after_success(
                            proxy_key=proxy_key,
                            contents_to_send=contents,
                            model_reply_content=full_reply_content,
                            model_name=chat_request.model,
                            enable_context=enable_context,
                            final_tool_calls=None
                        )

                except asyncio.CancelledError:
                    logger.info(f"客户端连接已中断 (IP: {client_ip})")
                except httpx.HTTPStatusError as http_err:
                    logger.error(f"流式 API 错误: {http_err.response.status_code} - {http_err.response.text}", exc_info=False)
                    stream_error_occurred = True
                    error_info = _format_api_error(http_err, current_api_key, key_manager)
                    yield f"data: {json.dumps({'error': error_info})}\n\n"
                    yield "data: [DONE]\n\n"
                    # 重新抛出异常，以便外层重试循环捕获
                    raise http_err
                except Exception as stream_e:
                    logger.error(f"流处理中捕获到意外异常: {stream_e}", exc_info=True)
                    stream_error_occurred = True
                    # 重新抛出异常，以便外层重试循环捕获
                    raise stream_e

            response = StreamingResponse(stream_generator(), media_type="text/event-stream")
            logger.info(f"流式响应已启动 (Key: {current_api_key[:8]})")
            return response, None, False

        else:
            async def run_gemini_completion():
                return await gemini_client_instance.complete_chat(chat_request, contents, current_safety_settings, system_instruction)

            try:
                response_obj = await run_gemini_completion()
                logger.info(f"非流式 API 调用成功 (Key: {current_api_key[:8]})")

                if response_obj and hasattr(response_obj, 'usage_metadata') and response_obj.usage_metadata:
                     prompt_tokens = response_obj.usage_metadata.get('promptTokenCount')
                     update_token_counts(current_api_key, model_name, limits, prompt_tokens, client_ip, today_date_str_pt)
                else:
                     logger.warning(f"Non-stream response successful but no usage metadata found (Key: {current_api_key[:8]}...). Token counts not updated.")

                await _save_context_after_success(
                    proxy_key=proxy_key,
                    contents_to_send=contents,
                    model_reply_content=response_obj.candidates[0].content.parts[0].text if response_obj and response_obj.candidates and response_obj.candidates[0].content.parts else "",
                    model_name=chat_request.model,
                    enable_context=enable_context,
                    final_tool_calls=[tc.model_dump() for tc in response_obj.candidates[0].content.tool_calls] if response_obj and response_obj.candidates and response_obj.candidates[0].content.tool_calls else None
                )

                return response_obj, None, False

            except httpx.HTTPStatusError as http_err:
                logger.error(f"非流式 API 错误: {http_err.response.status_code} - {http_err.response.text}", exc_info=False)
                error_info, needs_retry = await _handle_http_error_in_attempt(http_err, current_api_key, key_manager, is_stream)
                return None, json.dumps({'error': error_info}), needs_retry

            except Exception as e:
                logger.error(f"非流式 API 错误: {e}", exc_info=True)
                error_info, needs_retry = await _handle_api_call_exception(e, current_api_key, key_manager, is_stream)
                return None, json.dumps({'error': error_info}), needs_retry

    except Exception as e:
        logger.error(f"API 调用尝试中捕获到意外异常: {e}", exc_info=True)
        error_info, needs_retry = await _handle_api_call_exception(e, current_api_key, key_manager, chat_request.stream)
        return None, json.dumps({'error': error_info}), needs_retry


async def process_request(
    chat_request: ChatCompletionRequest,
    http_client: httpx.AsyncClient,
    http_request: Request,
    key_manager: APIKeyManager
) -> Union[StreamingResponse, ChatCompletionResponse]:
    """
    处理传入的聊天请求。
    """
    # 生成请求 ID
    request_id = f"req-{int(time.time() * 1000)}-{random.randint(1000, 9999)}"
    client_ip = get_client_ip(http_request)
    logger.info(format_log_message(f"收到来自 {client_ip} 的请求 (请求ID: {request_id})", chat_request))

    if not protect_from_abuse(client_ip):
         logger.warning(f"IP {client_ip} 达到每日请求限制。")
         raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="每日请求次数过多。")

    current_timestamp, today_date_str_pt = get_current_timestamps()

    if config.MAX_REQUESTS_PER_MINUTE > 0:
        pass

    proxy_key = chat_request.api_key

    if key_manager.is_key_daily_exhausted(proxy_key):
         logger.warning(f"代理 Key {proxy_key[:8]}... 已被标记为当天配额耗尽，拒绝请求。")
         raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="您的 API Key 已达到每日使用上限。")

    key_config = key_manager.get_key_config(proxy_key)
    enable_context = key_config.get('enable_context_completion', True) if key_config else True

    contents: List[Dict[str, Any]] = []
    system_instruction: Optional[str] = None
    if enable_context:
        logger.debug(f"Key {proxy_key[:8]}... 启用了上下文补全。尝试加载上下文...")
        try:
            loaded_context = await context_store.load_context(proxy_key)
            if loaded_context:
                logger.debug(f"加载到 {len(loaded_context)} 条历史上下文消息 for Key {proxy_key[:8]}...")
                contents.extend(loaded_context)
                if contents and contents[0].get("role") == "system":
                     system_instruction = contents.pop(0).get("parts", [{}])[0].get("text")
                     logger.debug(f"从上下文加载到系统指令 for Key {proxy_key[:8]}...")
            else:
                 logger.debug(f"Key {proxy_key[:8]}... 没有找到历史上下文。")
        except Exception as e:
            logger.error(f"加载上下文失败 (Key: {proxy_key[:8]}...): {str(e)}")

    current_message = convert_messages([chat_request.messages])
    contents.extend(current_message)

:start_line:482
-------
    # 第一次 Token 截断 (基于模型静态限制)
    # 在调用 select_best_key 之前无法获取 remaining_tpm_input，因此第一次截断仍基于静态限制。
    # 动态截断将在 select_best_key 之后进行。
    truncated_contents_static, still_over_limit_initial = truncate_context(contents, chat_request.model)

    if still_over_limit_initial:
        logger.warning(f"请求消息和上下文在初次静态截断后仍然超限 (Key: {proxy_key[:8]}...).")
        # 即使超限，仍然使用静态截断后的内容进行初步估算和 Key 选择
        contents_for_key_selection = truncated_contents_static
    else:
        contents_for_key_selection = truncated_contents_static # 使用静态截断后的内容进行 Key 选择

    key_manager.reset_tried_keys_for_request()

    max_attempts = config.MAX_RETRY_ATTEMPTS + 1

    for attempt in range(max_attempts):
        # 获取用于 Key 选择的输入 Token 估算值 (计划 1.1)
        current_request_tokens_for_selection = estimate_token_count(contents_for_key_selection, chat_request.model)
        logger.debug(f"用于 Key 选择的请求输入 Token 估算值: {current_request_tokens_for_selection}")

        # 选择最佳 Key，并进行 Token 预检查，获取剩余容量 (计划 1.1)
        current_api_key, remaining_tpm_input = key_manager.select_best_key(
            chat_request.model,
            current_request_tokens_for_selection, # 使用静态截断后的内容估算 Token 进行 Key 选择
            request_id=request_id
        )

        if not current_api_key:
            logger.error(f"所有可用 Key 均无法满足当前请求 (请求ID: {request_id})")
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="所有可用 API Key 当前均无法处理此请求，请稍后重试或联系管理员。")

        logger.info(f"尝试使用 Key: {current_api_key[:8]}... (剩余 TPM_Input 容量: {remaining_tpm_input}) 进行 API 调用 (尝试 {attempt + 1}/{max_attempts}, 请求ID: {request_id})")

        # 在这里使用 Key 的剩余容量进行动态上下文截断 (计划 4)
        # 只有在获取到 remaining_tpm_input 后才能进行动态截断
        dynamic_truncated_contents, still_over_limit_dynamic = truncate_context(
            contents, # 注意这里使用原始的 contents，因为动态截断应基于完整的上下文
            chat_request.model,
            dynamic_max_tokens_limit=remaining_tpm_input # 传递动态限制
        )

        if still_over_limit_dynamic:
             logger.warning(f"请求消息和上下文在动态截断后仍然超限 (Key: {proxy_key[:8]}...). 本次请求可能失败或返回不完整响应。")
             # 即使超限，仍然尝试使用截断后的内容进行调用，因为这是最佳尝试
             contents_to_send = dynamic_truncated_contents
        else:
             contents_to_send = dynamic_truncated_contents # 使用动态截断后的内容

        # 重新估算发送内容的 Token 数
        estimated_tokens_to_send = estimate_token_count(contents_to_send, chat_request.model)
        logger.debug(f"发送到 Gemini 的内容估算 Token 数: {estimated_tokens_to_send}")

        # 检查动态截断后的内容是否仍然超过模型的静态限制（双重检查）
        # 理论上，如果 dynamic_max_tokens_limit <= static_max_tokens，
        # 动态截断后的内容应该不会超过静态限制。
        # 但为了健壮性，这里进行检查。
        model_limits = getattr(config, 'MODEL_LIMITS', {})
        limit_info = model_limits.get(chat_request.model)
        static_max_tokens = getattr(config, 'DEFAULT_MAX_CONTEXT_TOKENS', 30000)
        if limit_info and isinstance(limit_info, dict) and limit_info.get("input_token_limit") is not None:
             try:
                  static_max_tokens = int(limit_info["input_token_limit"])
             except (ValueError, TypeError):
                  pass # 使用默认值

        if estimated_tokens_to_send > static_max_tokens:
             logger.error(f"动态截断后的内容 ({estimated_tokens_to_send} tokens) 仍然超过模型的静态输入限制 ({static_max_tokens} tokens)。这不应该发生，请检查截断逻辑。")
             # 尽管有错误，但为了不中断流程，继续尝试发送，但记录警告
             pass # 继续发送，但已记录错误


        response, error_payload, needs_retry = await _attempt_api_call(
            chat_request=chat_request,
            contents=contents_to_send, # 使用动态截断后的内容
            system_instruction=system_instruction,
            current_api_key=current_api_key,
            http_client=http_client,
            http_request=http_request,
            key_manager=key_manager,
            model_name=chat_request.model,
            limits=key_config.get('limits'),
            client_ip=client_ip,
            today_date_str_pt=today_date_str_pt,
            proxy_key=proxy_key,
            enable_context=enable_context,
            attempt=attempt,
            retry_attempts=config.MAX_RETRY_ATTEMPTS,
            request_id=request_id
        )

        if response:
            return response
        elif not needs_retry or attempt == config.MAX_RETRY_ATTEMPTS:
            # 如果不需要重试，或者已经达到最大重试次数，则返回错误
            logger.error(f"API 调用最终失败 (请求ID: {request_id})")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=json.loads(error_payload).get('error', {}).get('message', '未知错误'))

        logger.warning(f"API 调用失败，正在重试 (尝试 {attempt + 1}/{max_attempts}, 请求ID: {request_id})")
        await asyncio.sleep(1) # 重试前等待 1 秒

    # 如果所有尝试都失败
    logger.error(f"所有 API 调用尝试均失败 (请求ID: {request_id})")
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="所有 API 调用尝试均失败，请稍后重试或联系管理员。")
            chat_request.model, config.MODEL_LIMITS, current_request_tokens, request_id
        )

        if not current_api_key:
            if attempt < max_attempts - 1:
                 logger.warning(f"尝试 {attempt + 1}/{max_attempts} 失败 (请求ID: {request_id}): 没有找到可用的 API Key。")
                 # 记录未找到 Key 的原因
                 key_manager.record_selection_reason("N/A", "No available keys found", request_id)
                 await asyncio.sleep(1)
                 continue
            else:
                 # 记录最终未找到 Key 的原因
                 key_manager.record_selection_reason("N/A", "No available keys found after multiple attempts", request_id)
                 logger.error(f"所有 {max_attempts} 次尝试均失败，没有找到可用的 API Key。")
                 raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="没有可用的 API Key。请稍后再试或联系管理员。")

        # 如果找到 Key，记录剩余容量 (计划 1.1)
        logger.debug(f"选定 Key {current_api_key[:8]}...，预估剩余 TPM_Input 容量: {remaining_tpm_input}")

        # TODO: 将 remaining_tpm_input 传递给上下文处理逻辑 (计划 4)

        key_manager.tried_keys_for_request.add(current_api_key)

        rate_limit_passed, rate_limit_message = check_rate_limits_and_update_counts(
            current_api_key,
            chat_request.model,
            config.MODEL_LIMITS,
            1,
            current_request_tokens,
            client_ip,
            today_date_str_pt
        )

        if not rate_limit_passed:
            logger.warning(f"Key {current_api_key[:8]}... 速率限制检查失败: {rate_limit_message}. 尝试下一个 Key。")
            # 记录 Key 筛选原因
            key_manager.record_selection_reason(current_api_key, f"Rate Limit Exceeded: {rate_limit_message}", request_id)
            continue

        response, last_error, needs_retry = await _attempt_api_call(
            chat_request,
            truncated_contents,
            system_instruction,
            current_api_key,
            http_client,
            http_request,
            key_manager,
            chat_request.model,
            config.MODEL_LIMITS,
            client_ip,
            today_date_str_pt,
            proxy_key,
            enable_context,
            attempt,
            max_attempts - 1,
            request_id # 传递请求 ID
        )

        if response:
            # API 调用成功，返回响应
            return response

        # 检查是否需要重试
        if needs_retry and attempt < max_attempts - 1:
            logger.warning(f"API 调用失败，尝试重试 (尝试 {attempt + 1}/{max_attempts}, 请求ID: {request_id})。错误: {last_error}")
            # 记录重试原因
            error_info = json.loads(last_error).get('error', {})
            key_manager.record_selection_reason(current_api_key, f"API Error - Retrying: {error_info.get('message', 'Unknown error')}", request_id)
            await asyncio.sleep(1) # 等待 1 秒后重试
            continue # 继续下一次循环，尝试下一个 Key
        else:
            # API 调用失败且不需要重试，或者已达到最大重试次数
            logger.error(f"API 调用最终失败 (尝试 {attempt + 1}/{max_attempts}, 请求ID: {request_id})。错误: {last_error}")
            # 返回格式化的错误响应
            error_data = json.loads(last_error)
            raise HTTPException(status_code=error_data['error'].get('code', status.HTTP_500_INTERNAL_SERVER_ERROR),
                                detail=error_data['error'])

    # 如果循环结束（所有尝试都失败）
    logger.error(f"所有 API Key 尝试均失败 (请求ID: {request_id})。")
    if last_error:
         try:
             error_payload = json.loads(last_error)
             raise HTTPException(status_code=error_payload.get('error', {}).get('code', status.HTTP_500_INTERNAL_SERVER_ERROR), detail=error_payload.get('error', {}).get('message', 'API 调用失败'))
         except json.JSONDecodeError:
             raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=last_error)
    else:
         raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="API 调用失败。")


async def check_client_disconnect():
    """
    检查客户端连接是否断开。
    """
    try:
        await asyncio.get_running_loop().create_future()
    except asyncio.CancelledError:
        # 客户端连接已断开
        pass

# 在适当的地方调用 check_client_disconnect()
# 例如在处理流式响应的循环中

# IP 每日请求计数器和锁
# ip_daily_request_counts = Counter()
# ip_daily_request_counts_lock = Lock()

# IP 每分钟请求计数器和锁
# ip_minute_request_counts = Counter()
# ip_minute_request_timestamps = defaultdict(list)
# ip_minute_request_lock = Lock()

# 在适当的地方调用 protect_from_abuse(client_ip)
async def check_client_disconnect():
    """
    检查客户端连接是否断开。
    """
    try:
        await asyncio.get_running_loop().create_future()
    except asyncio.CancelledError:
        # 客户端连接已断开
        pass
