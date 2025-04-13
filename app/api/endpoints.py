import asyncio
import json
import logging
import random # 新增导入
import time
import pytz
from datetime import datetime
from typing import Literal, List, Tuple, Dict, Any, Optional # 增加 Optional
from fastapi import APIRouter, HTTPException, Request, Depends, status, Form # 增加 Form
from fastapi.responses import StreamingResponse, HTMLResponse
from collections import Counter, defaultdict # 导入 Counter 和 defaultdict
from .. import config # 新增导入 config 模块

# 从其他模块导入必要的组件
# 注意：移动后，相对导入路径需要调整
from .models import ChatCompletionRequest, ChatCompletionResponse, ModelList, Choice, ResponseMessage # 从同级 models 模块导入
from ..core.gemini import GeminiClient, ResponseWrapper, StreamProcessingError # 添加了 StreamProcessingError
from ..core.utils import APIKeyManager, handle_gemini_error, protect_from_abuse # 假设 APIKeyManager 目前仍在 utils 中
from .middleware import verify_password # 同级目录导入
from ..config import ( # 导入必要的配置变量
    # MODEL_LIMITS, # 不再直接导入
    DISABLE_SAFETY_FILTERING,
    MAX_REQUESTS_PER_MINUTE,
    MAX_REQUESTS_PER_DAY_PER_IP,
    USAGE_REPORT_INTERVAL_MINUTES, # 根页面需要
    REPORT_LOG_LEVEL_STR, # 根页面需要
    safety_settings,
    safety_settings_g2
)
from ..core.key_management import INVALID_KEYS # 为根页面导入启动信息 (移除 INITIAL_KEY_COUNT)
from ..core.tracking import ( # 导入 process_request 所需的跟踪组件
    usage_data, usage_lock, RPM_WINDOW_SECONDS, TPM_WINDOW_SECONDS,
    daily_rpd_totals, daily_totals_lock, # 新增导入
    ip_daily_counts, ip_counts_lock, # 新增导入
    ip_daily_input_token_counts, ip_input_token_counts_lock # 更新变量名
)
from ..handlers.log_config import format_log_message # 导入日志记录工具
from ..config import __version__ # 为根页面导入版本信息 (从 config 导入)


# --- 此模块内需要的全局变量 ---
logger = logging.getLogger('my_logger')
# TODO: 在实际应用中，key_manager 最好通过依赖注入传递，
# 但在此次重构中，我们将在此处实例化它或假设它是全局可用/已传递的。
# 目前，假设它在 main.py 中实例化并通过全局变量访问。
# 我们需要一种方法来访问在 main.py 中创建的实例。
# 选项 1：显式传递（需要修改函数签名或使用类）
# 选项 2：使用启动时设置的全局变量（目前更简单，但不太清晰）
# 选项 3：FastAPI 依赖注入（最佳实践）
# 让我们继续假设 key_manager 是可访问的（例如，从 main 或 utils 导入，如果它被移到那里）。
# 我们稍后需要调整 main.py 以使 key_manager 可用。
# 目前，我们直接导入它，假设它在 utils 中定义。
# !! 重要：这里的实例化需要移除，应该从 main.py 传入或通过依赖注入获取 !!
# from ..core.utils import APIKeyManager # 暂时注释掉，等待 main.py 提供实例
# key_manager = APIKeyManager() # 临时：假设在此处实例化或全局可访问
# 替代方案：假设 main.py 会创建一个实例并使其可导入
from ..core.utils import key_manager_instance as key_manager # 从 core.utils 导入共享实例


# --- APIRouter 实例 ---
router = APIRouter()

# --- 端点定义 ---

@router.get("/v1/models", response_model=ModelList)
async def list_models():
    """处理获取可用模型列表的 GET 请求。"""
    active_keys_count = key_manager.get_active_keys_count()
    # 如果 GeminiClient.AVAILABLE_MODELS 为空，则确保填充它
    if not GeminiClient.AVAILABLE_MODELS and active_keys_count > 0:
        logger.info("首次请求模型列表，尝试获取...")
        try:
            key_to_use = None
            with key_manager.keys_lock: # 直接访问
                 if key_manager.api_keys: key_to_use = key_manager.api_keys[0]
            if key_to_use:
                all_models = await GeminiClient.list_available_models(key_to_use)
                # 确保 AVAILABLE_MODELS 被正确更新
                GeminiClient.AVAILABLE_MODELS = [model.replace("models/", "") for model in all_models]
                logger.info(f"成功获取可用模型: {GeminiClient.AVAILABLE_MODELS}")
            else: logger.error("无法找到有效 Key 来获取模型列表。")
        except Exception as e:
            logger.error(f"获取模型列表失败: {e}")
            GeminiClient.AVAILABLE_MODELS = [] # 失败时重置

    log_msg = format_log_message('INFO', "接收到列出模型的请求", extra={'request_type': 'list_models', 'status_code': 200}) # 翻译
    logger.info(log_msg)
    # 返回列表，确保使用可能已更新的 AVAILABLE_MODELS
    return ModelList(data=[{"id": model, "object": "model", "created": int(time.time()), "owned_by": "organization-owner"} for model in GeminiClient.AVAILABLE_MODELS])


async def process_request(chat_request: ChatCompletionRequest, http_request: Request, request_type: Literal['stream', 'non-stream']):
    """
    聊天补全（流式和非流式）的核心请求处理函数。
    包括密钥选择、速率限制检查、API 调用尝试和响应处理。
    """
    # --- 获取客户端 IP ---
    client_ip = http_request.headers.get("x-forwarded-for")
    if client_ip:
        client_ip = client_ip.split(',')[0].strip()
    else:
        client_ip = http_request.client.host if http_request.client else "unknown_ip"

    # --- 获取当前时间 ---
    cst_tz = pytz.timezone('Asia/Shanghai')
    cst_now = datetime.now(cst_tz)
    cst_time_str = cst_now.strftime('%Y-%m-%d %H:%M:%S %Z')
    # 获取 PT 日期用于 IP 统计 - 确保时区转换正确
    pt_tz = pytz.timezone('America/Los_Angeles')
    today_date_str_pt = datetime.now(pt_tz).strftime('%Y-%m-%d') # 使用 PT 日期作为 IP 跟踪的键

    # --- 记录请求入口日志 ---
    logger.info(f"接收到来自 IP: {client_ip} 的请求 ({request_type})，模型: {chat_request.model}，时间: {cst_time_str}")

    # --- 防滥用保护 ---
    # protect_from_abuse 需要访问配置常量
    protect_from_abuse(http_request, MAX_REQUESTS_PER_MINUTE, MAX_REQUESTS_PER_DAY_PER_IP)
    if not chat_request.messages:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="消息不能为空") # 翻译

    # --- 模型列表检查 ---
    active_keys_count = key_manager.get_active_keys_count()
    if not GeminiClient.AVAILABLE_MODELS and active_keys_count > 0:
        logger.warning("可用模型列表为空，尝试在请求处理中获取...")
        try:
            key_to_use = None
            with key_manager.keys_lock: # 最后检查
                if key_manager.api_keys: key_to_use = key_manager.api_keys[0]
            if key_to_use:
                all_models = await GeminiClient.list_available_models(key_to_use)
                GeminiClient.AVAILABLE_MODELS = [model.replace("models/", "") for model in all_models]
                logger.info(f"请求处理中成功获取可用模型: {GeminiClient.AVAILABLE_MODELS}")
            else: logger.error("无法找到有效 Key 来获取模型列表。") # 翻译
        except Exception as e: logger.error(f"请求处理中获取模型列表失败: {e}") # 翻译

    if chat_request.model not in GeminiClient.AVAILABLE_MODELS:
        error_msg = f"无效的模型: {chat_request.model}. 可用模型: {GeminiClient.AVAILABLE_MODELS or '列表获取失败'}" # 翻译
        status_code = status.HTTP_400_BAD_REQUEST if GeminiClient.AVAILABLE_MODELS else status.HTTP_503_SERVICE_UNAVAILABLE
        raise HTTPException(status_code=status_code, detail=error_msg)

    # --- 请求处理循环 ---
    key_manager.reset_tried_keys_for_request()
    contents = None
    system_instruction = None
    last_error = None
    response = None
    current_api_key = None

    retry_attempts = active_keys_count if active_keys_count > 0 else 1

    for attempt in range(1, retry_attempts + 1):
        # --- 智能 Key 选择 ---
        current_api_key = key_manager.select_best_key(chat_request.model, config.MODEL_LIMITS) # 通过 config 模块访问

        if current_api_key is None:
            log_msg_no_key = format_log_message('WARNING', f"尝试 {attempt}/{retry_attempts}：无法选择合适的 API 密钥 (可能都已尝试或 RPD 超限)，结束重试。", extra={'request_type': request_type, 'model': chat_request.model})
            logger.warning(log_msg_no_key)
            break # 结束重试循环

        key_manager.tried_keys_for_request.add(current_api_key) # 标记为已尝试
        extra_log = {'key': current_api_key[:8], 'request_type': request_type, 'model': chat_request.model}
        log_msg = format_log_message('INFO', f"第 {attempt}/{retry_attempts} 次尝试 ... 选择密钥: {current_api_key[:8]}...", extra=extra_log)
        logger.info(log_msg)

        # --- 模型限制预检查 ---
        model_name = chat_request.model
        limits = config.MODEL_LIMITS.get(model_name) # 通过 config 模块访问
        if limits is None:
            logger.warning(f"模型 '{model_name}' 不在 MODEL_LIMITS 中，跳过此 Key 的本地速率限制检查和计数。")
        else:
            # --- 预检查 (RPM/RPD/TPD_Input/TPM_Input) --- # 更新注释
            now = time.time()
            perform_api_call = True
            with usage_lock:
                # 确保 key 和 model 存在于 usage_data 中 (defaultdict 会处理)
                key_usage = usage_data.setdefault(current_api_key, defaultdict(dict))[model_name]

                # 检查 RPD
                rpd_limit = limits.get("rpd")
                if rpd_limit is not None and key_usage.get("rpd_count", 0) >= rpd_limit:
                    logger.warning(f"预检查失败 (Key: {current_api_key[:8]}, Model: {model_name}): RPD 达到限制 ({key_usage.get('rpd_count', 0)}/{rpd_limit})。跳过此 Key。")
                    perform_api_call = False
                # 检查 TPD_Input (新增)
                if perform_api_call:
                    tpd_input_limit = limits.get("tpd_input")
                    if tpd_input_limit is not None and key_usage.get("tpd_input_count", 0) >= tpd_input_limit:
                        logger.warning(f"预检查失败 (Key: {current_api_key[:8]}, Model: {model_name}): TPD_Input 达到限制 ({key_usage.get('tpd_input_count', 0)}/{tpd_input_limit})。跳过此 Key。")
                        perform_api_call = False
                # 检查 RPM (在时间窗口内)
                if perform_api_call:
                    rpm_limit = limits.get("rpm")
                    if rpm_limit is not None:
                        if now - key_usage.get("rpm_timestamp", 0) < RPM_WINDOW_SECONDS:
                            if key_usage.get("rpm_count", 0) >= rpm_limit:
                                 logger.warning(f"预检查失败 (Key: {current_api_key[:8]}, Model: {model_name}): RPM 达到限制 ({key_usage.get('rpm_count', 0)}/{rpm_limit})。跳过此 Key。")
                                 perform_api_call = False
                        else: # 如果时间窗口已过，则重置 RPM 计数
                            key_usage["rpm_count"] = 0
                            key_usage["rpm_timestamp"] = 0
                # 检查 TPM_Input (在时间窗口内) (新增)
                if perform_api_call:
                    tpm_input_limit = limits.get("tpm_input")
                    if tpm_input_limit is not None:
                        if now - key_usage.get("tpm_input_timestamp", 0) < TPM_WINDOW_SECONDS:
                             if key_usage.get("tpm_input_count", 0) >= tpm_input_limit:
                                 logger.warning(f"预检查失败 (Key: {current_api_key[:8]}, Model: {model_name}): TPM_Input 达到限制 ({key_usage.get('tpm_input_count', 0)}/{tpm_input_limit})。跳过此 Key。")
                                 perform_api_call = False
                        else: # 如果时间窗口已过，则重置 TPM_Input 计数
                            key_usage["tpm_input_count"] = 0
                            key_usage["tpm_input_timestamp"] = 0

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
                    key_usage["rpm_count"] = key_usage.get("rpm_count", 0) + 1 # 使用 get 以确保安全
                # 更新 RPD
                key_usage["rpd_count"] = key_usage.get("rpd_count", 0) + 1
                # 更新最后请求时间戳
                key_usage["last_request_timestamp"] = now
                logger.debug(f"计数增加 (Key: {current_api_key[:8]}, Model: {model_name}): RPM={key_usage['rpm_count']}, RPD={key_usage['rpd_count']}")

        # --- API 调用尝试 ---
        try:
            # 如果需要，仅转换一次消息
            if contents is None and system_instruction is None:
                # 假设 GeminiClient 已正确导入
                # !! 需要使用正确的 client 实例 !!
                gemini_client_instance = GeminiClient(current_api_key)
                conversion_result = gemini_client_instance.convert_messages(chat_request.messages, use_system_prompt=True)
                if isinstance(conversion_result, list): # 错误情况
                    error_msg = "; ".join(conversion_result)
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"消息转换失败: {error_msg}")
                contents, system_instruction = conversion_result

            # 确定安全设置
            current_safety_settings = safety_settings_g2 if DISABLE_SAFETY_FILTERING or 'gemini-2.0-flash-exp' in chat_request.model else safety_settings
            # !! 需要使用正确的 client 实例 !!
            if 'gemini_client_instance' not in locals(): # 确保实例存在（如果跳过了转换）
                 gemini_client_instance = GeminiClient(current_api_key)

            # --- 流式 vs 非流式 ---
            if chat_request.stream:
                async def stream_generator():
                    nonlocal last_error # 使用 nonlocal 修改外部作用域变量
                    stream_error_occurred = False
                    final_response_data = None # 用于存储潜在的最终数据，如使用情况
                    assistant_message_yielded = False # Roo Code 兼容性标志
                    usage_metadata_received = None # 存储收到的 usage metadata
                    actual_finish_reason = "stop" # 存储从 stream_chat 获取的实际完成原因

                    try:
                        usage_metadata_received = None
                        # !! 使用正确的 client 实例 !!
                        async for chunk in gemini_client_instance.stream_chat(chat_request, contents, current_safety_settings, system_instruction):
                            if isinstance(chunk, dict) and '_usage_metadata' in chunk:
                                usage_metadata_received = chunk['_usage_metadata']
                                logger.debug(f"流接收到 usage metadata: {usage_metadata_received}") # 翻译
                                continue # 处理完元数据，继续循环
                            # 检查是否是最终完成原因块
                            if isinstance(chunk, dict) and '_final_finish_reason' in chunk:
                                actual_finish_reason = chunk['_final_finish_reason']
                                logger.debug(f"流接收到最终完成原因: {actual_finish_reason}") # 翻译
                                continue # 处理完元数据，继续循环

                            # 检查 stream_chat 产生的内部错误消息
                            if isinstance(chunk, str) and chunk.startswith("[代理服务警告"):
                                logger.error(f"流产生错误消息: {chunk}") # 翻译
                                last_error = chunk
                                stream_error_occurred = True
                                break # 停止处理流

                            # --- Roo Code 兼容性：检查工具调用并修复参数 ---
                            # 这需要在 gemini.py 的 stream_chat 中进行修改，以产生结构化的工具调用信息
                            # 目前，假设 chunk 只是文本内容。工具调用处理需要更深入的集成。
                            # TODO: 调整 stream_chat 以便单独产生工具调用块在此处处理。

                            # 格式化标准文本块
                            formatted_chunk = {
                                "id": f"chatcmpl-{int(time.time())}", # 使用时间戳作为唯一 ID
                                "object": "chat.completion.chunk",
                                "created": int(time.time()),
                                "model": chat_request.model,
                                "choices": [{
                                    "delta": {"role": "assistant", "content": chunk},
                                    "index": 0,
                                    "finish_reason": None
                                }]
                            }
                            yield f"data: {json.dumps(formatted_chunk)}\n\n"
                            assistant_message_yielded = True # 标记我们已发送助手内容

                        # --- 流结束处理 ---
                        if not stream_error_occurred:
                            # --- Roo Code 兼容性：如果未发送任何助手消息，则确保发送一个 ---
                            # 这个检查可能多余（如果 Gemini 总是发送内容或 stream_chat 处理空响应），
                            # 但为了健壮性根据需求添加。
                            if not assistant_message_yielded:
                                logger.warning(f"流结束时未产生助手内容 (实际完成原因: {actual_finish_reason})。为 Roo Code 兼容性发送空助手块。") # 翻译
                                empty_chunk = {
                                    "id": f"chatcmpl-{int(time.time())}-empty",
                                    "object": "chat.completion.chunk",
                                    "created": int(time.time()),
                                    "model": chat_request.model,
                                    "choices": [{"delta": {"role": "assistant", "content": ""}, "index": 0, "finish_reason": actual_finish_reason}] # 使用实际的完成原因
                                }
                                yield f"data: {json.dumps(empty_chunk)}\n\n"


                            # 发送 [DONE] 信号
                            yield "data: [DONE]\n\n"

                            # --- 处理 Token 计数（成功情况）---
                            if limits and usage_metadata_received:
                                prompt_tokens = usage_metadata_received.get('promptTokenCount', 0)
                                completion_tokens = usage_metadata_received.get('candidatesTokenCount', 0)
                                # total_tokens = prompt_tokens + completion_tokens # 不再需要计算总 tokens
                                if prompt_tokens > 0: # 仅在有输入 token 时更新
                                    with usage_lock:
                                        key_usage = usage_data[current_api_key][model_name]
                                        # 更新 TPD_Input
                                        key_usage["tpd_input_count"] = key_usage.get("tpd_input_count", 0) + prompt_tokens
                                        # 更新 TPM_Input
                                        tpm_input_limit = limits.get("tpm_input")
                                        if tpm_input_limit is not None:
                                            now_tpm = time.time() # 使用一致的时间
                                            if now_tpm - key_usage.get("tpm_input_timestamp", 0) >= TPM_WINDOW_SECONDS:
                                                key_usage["tpm_input_count"] = prompt_tokens
                                                key_usage["tpm_input_timestamp"] = now_tpm
                                            else:
                                                key_usage["tpm_input_count"] = key_usage.get("tpm_input_count", 0) + prompt_tokens
                                            logger.debug(f"输入 Token 计数更新 (Key: {current_api_key[:8]}, Model: {model_name}): Added TPD_Input={prompt_tokens}, TPM_Input={key_usage['tpm_input_count']}") # 翻译
                                    # --- 记录 IP 输入 Token 消耗 ---
                                    with ip_input_token_counts_lock: # 使用更新后的锁名
                                        # 确保日期键存在
                                        ip_daily_input_token_counts.setdefault(today_date_str_pt, Counter())[client_ip] += prompt_tokens # 使用 prompt_tokens
                                else:
                                     logger.warning(f"流式响应成功但未获取到有效的 prompt token 数量: {usage_metadata_received}")

                    except asyncio.CancelledError:
                        logger.info(f"客户端连接已中断 (IP: {client_ip})")
                        return # 停止生成器，不发送 [DONE]
                    except StreamProcessingError as spe:
                        last_error = str(spe)
                        logger.error(f"流处理错误 (StreamProcessingError): {last_error}", exc_info=False)
                        # 如果需要，可以选择性地向客户端产生错误块，但通常只是停止。
                        return # 停止生成器
                    except Exception as e:
                        # 使用导入的 handle_gemini_error
                        last_error = handle_gemini_error(e, current_api_key, key_manager)
                        logger.error(f"流处理中捕获到意外异常: {last_error}", exc_info=True)
                        return # 停止生成器

                return StreamingResponse(stream_generator(), media_type="text/event-stream")

            else: # 非流式请求
                # --- 非流式 API 调用 ---
                async def run_gemini_completion():
                    # 直接调用异步 Gemini 函数
                    # !! 需要使用正确的 client 实例 !!
                    return await gemini_client_instance.complete_chat(chat_request, contents, current_safety_settings, system_instruction)

                async def check_client_disconnect():
                    # 监控客户端连接的任务
                    while True:
                        if await http_request.is_disconnected():
                            logger.warning(f"客户端连接中断 detected (IP: {client_ip})") # 翻译
                            return True
                        await asyncio.sleep(0.5)

                gemini_task = asyncio.create_task(run_gemini_completion())
                disconnect_task = asyncio.create_task(check_client_disconnect())

                try:
                    done, pending = await asyncio.wait(
                        [gemini_task, disconnect_task], return_when=asyncio.FIRST_COMPLETED
                    )

                    if disconnect_task in done:
                        # 客户端在 Gemini 完成前断开连接
                        gemini_task.cancel()
                        try: await gemini_task # 等待取消
                        except asyncio.CancelledError: logger.info("非流式 API 任务已成功取消")
                        # 没有发送响应，客户端已离开
                        # 记录断开连接，但不要向无处可去的 FastAPI 抛出 HTTPException
                        logger.error(f"客户端连接中断 (IP: {client_ip})，终止请求处理。")
                        # 我们需要优雅地退出函数，而不是返回/抛出给 FastAPI
                        # 返回 None 可能有效，或者专门处理此状态
                        return None # 指示不应发送响应

                    if gemini_task in done:
                        # Gemini 先完成，取消断开连接检查器
                        disconnect_task.cancel()
                        try: await disconnect_task
                        except asyncio.CancelledError: pass # 预期之中

                        response_content: ResponseWrapper = gemini_task.result()

                        # --- Roo Code 兼容性：检查空响应/缺少助手消息 ---
                        assistant_content = None # 初始化
                        finish_reason = response_content.finish_reason if response_content else "stop" # 如果没有 response_content，默认为 stop

                        if not response_content or not response_content.text:
                            if finish_reason != "STOP":
                                # 可能是被阻止或出错，按失败处理
                                last_error = f"Gemini API 返回空响应或被阻止。完成原因: {finish_reason}" # 翻译
                                logger.warning(f"{last_error} (Key: {current_api_key[:8]})")
                                # 如果需要，将密钥标记为可能有问题（例如，安全阻止）
                                if finish_reason == "SAFETY": # 在安全阻止时标记密钥问题
                                    key_manager.mark_key_issue(current_api_key, "safety_block")
                                continue # 使用下一个密钥重试
                            else: # 完成原因是 STOP 但文本为空
                                # 对于 Roo Code，我们必须提供助手消息。
                                logger.warning(f"Gemini API 返回 STOP 完成原因但文本为空 (Key: {current_api_key[:8]})。为兼容性提供空助手消息。") # 翻译
                                assistant_content = "" # 设置空内容
                        else: # 我们有文本内容
                            assistant_content = response_content.text

                        # 确保 assistant_content 已赋值（现在应始终为 str）
                        if assistant_content is None:
                             logger.error("逻辑错误：assistant_content 未赋值。") # 不应发生
                             assistant_content = "" # 后备方案

                        # --- Roo Code 兼容性：检查工具调用 ---
                        # 这需要 ResponseWrapper 从 Gemini 响应中解析工具调用
                        # TODO: 在 gemini.py 中增强 ResponseWrapper 以提取 Gemini 格式中存在的 tool_calls
                        final_tool_calls = None
                        # 假设 response_content 有一个 'tool_calls' 属性，包含 Gemini 的原始工具调用
                        raw_gemini_tool_calls = getattr(response_content, 'tool_calls', None) # 安全地获取潜在的工具调用
                        if raw_gemini_tool_calls:
                             logger.info("正在处理 Gemini 返回的工具调用...")
                             final_tool_calls = process_tool_calls(raw_gemini_tool_calls) # 调用辅助函数
                             if final_tool_calls:
                                  logger.info(f"已处理的工具调用: {final_tool_calls}")
                             else:
                                  logger.warning("process_tool_calls 返回 None 或空列表。")
                        # else: 响应中未找到工具调用


                        # 构建最终响应
                        response = ChatCompletionResponse(
                            id=f"chatcmpl-{int(time.time())}",
                            object="chat.completion",
                            created=int(time.time()),
                            model=chat_request.model,
                            choices=[{
                                "index": 0,
                                "message": ResponseMessage(role="assistant", content=assistant_content, tool_calls=final_tool_calls), # 使用处理后的 assistant_content
                                "finish_reason": finish_reason # 使用确定的 finish_reason
                            }],
                            # TODO: 如果可能，正确提取和格式化使用情况
                            # usage=UsageInfo(...)
                        )

                        logger.info(f"请求处理成功 (Key: {current_api_key[:8]})")

                        # --- 处理 Token 计数（成功情况）---
                        if limits:
                            # 假设 ResponseWrapper 具有 usage_metadata 属性
                            usage_info = getattr(response_content, 'usage_metadata', None)
                            if usage_info:
                                prompt_tokens = usage_info.get('promptTokenCount', 0)
                                completion_tokens = usage_info.get('candidatesTokenCount', 0)
                                # total_tokens = prompt_tokens + completion_tokens # 不再需要
                                if prompt_tokens > 0: # 仅在有输入 token 时更新
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
                                            logger.debug(f"输入 Token 计数更新 (Key: {current_api_key[:8]}, Model: {model_name}): Added TPD_Input={prompt_tokens}, TPM_Input={key_usage['tpm_input_count']}") # 翻译
                                    # --- 记录 IP 输入 Token 消耗 ---
                                    with ip_input_token_counts_lock: # 使用更新后的锁名
                                        ip_daily_input_token_counts.setdefault(today_date_str_pt, Counter())[client_ip] += prompt_tokens # 使用 prompt_tokens
                                else:
                                    logger.warning(f"非流式响应成功但未获取到有效的 prompt token 数量: {usage_info}") # 翻译
                            else:
                                logger.warning(f"非流式响应成功但 ResponseWrapper 未包含 usage_metadata 属性。") # 翻译

                        return response # 成功，返回构建的响应

                except asyncio.CancelledError:
                    # 如果外部请求被取消，可能会发生这种情况
                    logger.info("非流式请求任务被取消")
                    raise # 重新引发取消异常

        # --- 处理 API 调用异常 ---
        except HTTPException as e:
            # 如果客户端断开连接，记录日志并停止此请求的重试
            if e.status_code == status.HTTP_408_REQUEST_TIMEOUT:
                logger.error(f"客户端连接中断 (IP: {client_ip})，终止后续重试")
                # 不要向 FastAPI 抛出异常，因为客户端已离开，只需停止处理。
                return None # 指示不应发送响应
            elif e.status_code == status.HTTP_400_BAD_REQUEST and "消息转换失败" in e.detail:
                 # 如果消息转换失败，则这是此请求的永久错误
                 logger.error(f"消息转换失败，终止重试。详情: {e.detail}")
                 raise e # 重新引发原始异常
            else:
                # 其他 HTTPException 可能可以根据状态码重试
                logger.warning(f"请求处理中遇到 HTTPException (状态码 {e.status_code})，尝试下一个 Key。详情: {e.detail}")
                last_error = f"HTTPException: {e.detail}" # 存储错误信息，以备所有密钥都失败时使用
                continue # 尝试下一个密钥

        except Exception as e:
            # 使用导入的 handle_gemini_error
            last_error = handle_gemini_error(e, current_api_key, key_manager)
            logger.error(f"第 {attempt}/{retry_attempts} 次尝试失败: {last_error}", exc_info=True)
            # 继续下一次尝试
            continue

    # --- 重试循环结束 ---
    # 如果我们在没有返回响应的情况下退出循环，则所有尝试都失败了
    final_error_msg = last_error or "所有 API 密钥均尝试失败或无可用密钥"
    extra_log_fail = {'request_type': request_type, 'model': chat_request.model, 'status_code': 500, 'error_message': final_error_msg}
    log_msg = format_log_message('ERROR', f"请求处理失败: {final_error_msg}", extra=extra_log_fail)
    logger.error(log_msg)
    # 如果所有重试都失败，则引发 500 内部服务器错误
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=final_error_msg)


@router.post("/v1/chat/completions", response_model=ChatCompletionResponse, status_code=status.HTTP_200_OK)
async def chat_completions(
    chat_request: ChatCompletionRequest,
    http_request: Request,
    _ = Depends(verify_password) # 添加密码验证依赖
):
    """处理聊天补全的 POST 请求（流式和非流式）。"""
    response = await process_request(
        chat_request=chat_request,
        http_request=http_request,
        request_type='stream' if chat_request.stream else 'non-stream'
    )
    # 处理 process_request 可能返回 None 的情况 (客户端断开连接)
    if response is None:
        # 返回一个空的响应或根据需要处理，这里我们假设不返回任何内容
        # 或者可以返回一个特定的状态码，但这可能不符合 OpenAI API 规范
        return None # 或者根据 FastAPI 的行为调整
    return response

# 根据配置决定是否对根路径应用密码保护
# root_dependencies = [Depends(verify_password)] if config.PROTECT_STATUS_PAGE else [] # 旧逻辑移除

@router.route("/", methods=["GET", "POST"]) # 接受 GET 和 POST
async def root(request: Request): # 移除 password 参数，直接从 request 获取表单
    """根路径，返回一个简单的 HTML 状态页面（可能受密码保护）。"""
    is_authenticated = False
    login_error = None

    # 检查是否需要密码保护
    if config.PROTECT_STATUS_PAGE:
        # 优先检查 Header (如果之前登录过或通过工具访问)
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            try:
                token = auth_header.split(" ")[1]
                if token == config.PASSWORD:
                    is_authenticated = True
            except IndexError:
                pass # 格式错误，忽略

        # 如果 Header 验证失败，检查 POST 表单
        if not is_authenticated and request.method == "POST":
            form_data = await request.form()
            password = form_data.get("password")
            # 添加调试日志
            logger.debug(f"状态页面登录尝试：表单密码='{password}', 配置密码='{config.PASSWORD}'")
            if password and password == config.PASSWORD:
                is_authenticated = True
                # 简单的 "登录成功" 提示，实际应用中可能需要更复杂的会话管理
                # 这里我们依赖后续请求中包含正确的 Header
            elif password is not None: # 用户尝试提交密码但错误
                login_error = "密码错误！"
    else:
        # 如果不需要保护，则始终视为已认证
        is_authenticated = True

    # 获取当前 CST 时间用于显示
    cst_tz = pytz.timezone('Asia/Shanghai')
    cst_now = datetime.now(cst_tz).strftime('%Y-%m-%d %H:%M:%S %Z')

    # 获取密钥状态摘要 (仅在认证后获取)
    initial_keys = "N/A"
    active_keys = "N/A"
    invalid_keys_count = "N/A"
    if is_authenticated:
        active_keys = key_manager.get_active_keys_count()
        initial_keys = key_manager.get_initial_key_count() # 通过实例获取初始数量
        invalid_keys_count = len(INVALID_KEYS)

    # 获取最近的每日 RPD 总量 (仅在认证后获取)
    pt_tz = pytz.timezone('America/Los_Angeles')
    recent_rpd_str = "N/A"
    if is_authenticated:
        try:
            with daily_totals_lock:
                dates = sorted(daily_rpd_totals.keys(), reverse=True)
                if dates:
                    last_date = dates[0]
                    last_rpd = daily_rpd_totals[last_date]
                    recent_rpd_str = f"{last_date} (PT): {last_rpd:,}"
        except Exception as e:
            logger.error(f"获取最近 RPD 总量时出错: {e}")

    # 获取 Top IPs (仅在认证后获取)
    top_req_ips_str = "N/A"
    top_token_ips_str = "N/A"
    if is_authenticated:
        try:
            today_date_str_pt = datetime.now(pt_tz).strftime('%Y-%m-%d')
            with ip_counts_lock:
                today_ips = ip_daily_counts.get(today_date_str_pt, {})
                top_req_ips = Counter(today_ips).most_common(3) # type: ignore
                if top_req_ips:
                    top_req_ips_str = ", ".join([f"{ip}({count})" for ip, count in top_req_ips])
            with ip_input_token_counts_lock:
                today_token_ips = ip_daily_input_token_counts.get(today_date_str_pt, {})
                top_token_ips = Counter(today_token_ips).most_common(3) # type: ignore
                if top_token_ips:
                     top_token_ips_str = ", ".join([f"{ip}({tokens:,})" for ip, tokens in top_token_ips])
        except Exception as e:
             logger.error(f"获取 Top IPs 时出错: {e}")


    # 构建美化后的 HTML 内容
    html_content = f"""
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>🚀 Gemini API 代理状态</title>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol";
                line-height: 1.6;
                padding: 20px;
                background-color: #f8f9fa;
                color: #343a40;
                margin: 0;
            }}
            .container {{
                max-width: 900px;
                margin: 40px auto;
                background-color: #ffffff;
                padding: 30px;
                border-radius: 8px;
                box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
            }}
            h1 {{
                color: #007bff;
                text-align: center;
                margin-bottom: 30px;
                border-bottom: 2px solid #dee2e6;
                padding-bottom: 10px;
            }}
            h2 {{
                color: #495057;
                margin-top: 40px;
                margin-bottom: 15px;
                border-bottom: 1px solid #e9ecef;
                padding-bottom: 5px;
            }}
            p {{
                margin-bottom: 10px;
            }}
            strong {{
                color: #495057;
            }}
            .status-ok {{ color: #28a745; font-weight: bold; }}
            .status-warn {{ color: #ffc107; font-weight: bold; }}
            .status-error {{ color: #dc3545; font-weight: bold; }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 20px;
                box-shadow: 0 1px 3px rgba(0,0,0,0.05);
            }}
            th, td {{
                border: 1px solid #dee2e6;
                padding: 12px 15px;
                text-align: left;
                vertical-align: top;
            }}
            th {{
                background-color: #e9ecef;
                color: #495057;
                font-weight: 600;
            }}
            tr:nth-child(even) {{
                background-color: #f8f9fa;
            }}
            td:first-child {{
                font-weight: 500;
                width: 30%; /* 调整第一列宽度 */
            }}
            .links {{
                margin-top: 30px;
                text-align: center;
            }}
            .links a {{
                display: inline-block;
                margin: 0 10px;
                padding: 10px 20px;
                background-color: #007bff;
                color: white;
                text-decoration: none;
                border-radius: 5px;
                transition: background-color 0.3s ease;
            }}
            .links a:hover {{
                background-color: #0056b3;
            }}
            .login-form {{
                margin-bottom: 30px;
                padding: 20px;
                background-color: #f1f1f1;
                border-radius: 5px;
                text-align: center;
            }}
            .login-form input[type="password"] {{
                padding: 10px;
                margin-right: 10px;
                border: 1px solid #ccc;
                border-radius: 4px;
            }}
            .login-form button {{
                padding: 10px 20px;
                background-color: #28a745;
                color: white;
                border: none;
                border-radius: 4px;
                cursor: pointer;
            }}
            .login-form button:hover {{
                background-color: #218838;
            }}
            .login-error {{
                color: red;
                margin-top: 10px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🚀 Gemini API 代理状态</h1>

            { f'<div class="login-form">'
              f'<form method="post">'
              f'<label for="password">请输入访问密码:</label> '
              f'<input type="password" id="password" name="password" required> '
              f'<button type="submit">登录</button>'
              f'</form>'
              f'{ f"<p class=login-error>{login_error}</p>" if login_error else "" }'
              f'</div>'
              if config.PROTECT_STATUS_PAGE and not is_authenticated else "" }

            <p><strong>版本:</strong> {__version__}</p>
            <p><strong>当前时间:</strong> {cst_now}</p>
            <p><strong>状态:</strong> <span class="status-ok">运行中</span></p>

            { f'''
            <h2>密钥状态</h2>
            <table>
                <tr><th>总配置密钥数</th><td>{initial_keys}</td></tr>
                <tr><th>当前有效密钥数</th><td class="{ 'status-ok' if isinstance(active_keys, int) and active_keys > 0 else 'status-error' }">{active_keys}</td></tr>
                <tr><th>启动时无效密钥数</th><td class="{ 'status-warn' if isinstance(invalid_keys_count, int) and invalid_keys_count > 0 else 'status-ok' }">{invalid_keys_count}</td></tr>
            </table>

            <h2>使用情况摘要</h2>
            <table>
                <tr><th>报告日志级别</th><td>{REPORT_LOG_LEVEL_STR}</td></tr>
                <tr><th>报告间隔 (分钟)</th><td>{USAGE_REPORT_INTERVAL_MINUTES}</td></tr>
                <tr><th>最近 RPD 总量</th><td>{recent_rpd_str}</td></tr>
                <tr><th>今日 Top 3 请求 IP</th><td>{top_req_ips_str}</td></tr>
                <tr><th>今日 Top 3 输入 Token IP</th><td>{top_token_ips_str}</td></tr>
            </table>
            ''' if is_authenticated else "" }

            <h2>配置</h2>
            <table>
                <tr><th>密码保护</th><td>{'是' if config.PASSWORD else '否'}</td></tr>
                <tr><th>状态页面保护</th><td>{'是' if config.PROTECT_STATUS_PAGE else '否'}</td></tr>
                <tr><th>安全过滤禁用</th><td>{config.DISABLE_SAFETY_FILTERING}</td></tr>
                <tr><th>RPM 限制 (全局)</th><td>{config.MAX_REQUESTS_PER_MINUTE}</td></tr>
                <tr><th>RPD/IP 限制 (全局)</th><td>{config.MAX_REQUESTS_PER_DAY_PER_IP}</td></tr>
            </table>

            <div class="links">
                <a href="/docs">API 文档 (Swagger UI)</a>
                <a href="/redoc">API 文档 (ReDoc)</a>
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


def process_tool_calls(gemini_tool_calls: Any) -> List[Dict[str, Any]]:
    """处理 Gemini 返回的工具调用，根据需要调整参数以实现兼容性。"""
    processed_calls = []
    if not isinstance(gemini_tool_calls, list):
        logger.warning(f"预期的工具调用格式为列表，但收到: {type(gemini_tool_calls)}")
        return processed_calls

    # 遍历 Gemini 返回的工具调用列表
    for call in gemini_tool_calls:
        # 检查是否是函数调用
        if 'functionCall' in call:
            function_call = call['functionCall']
            # 获取函数名称和参数
            name = function_call.get('name')
            args_str = function_call.get('args')

            if not name or not args_str:
                logger.warning(f"工具调用缺少名称或参数: {call}")
                continue

            args = {}
            # 尝试解析参数（如果它们是 JSON 字符串）
            if isinstance(args_str, str):
                try:
                    args = json.loads(args_str)
                except json.JSONDecodeError:
                    logger.warning(f"无法将工具调用的参数解析为 JSON: {args_str}")
                    # 如果解析失败，可能需要决定如何处理，这里我们跳过此调用
                    continue
            elif isinstance(args_str, dict):
                 args = args_str # 如果已经是 dict，直接使用
            else:
                 logger.warning(f"工具调用的参数类型未知: {type(args_str)}")
                 continue


            # --- Roo Code 兼容性修复 ---
            # 修复 write_to_file 缺失的 line_count
            if name == 'write_to_file' and 'content' in args and 'line_count' not in args:
                content = args.get('content', '')
                # 如果 content 存在，则计算 line_count
                if isinstance(content, str):
                    line_count = content.count('\n') + 1
                    args['line_count'] = line_count
                    logger.info(f"为 write_to_file 计算并添加了 line_count: {line_count}")

            # TODO: 如果需要，在此处添加其他兼容性修复

            # 将处理后的参数转换回 JSON 字符串以符合 OpenAI 格式
            try:
                processed_args_str = json.dumps(args)
            except TypeError as e:
                logger.error(f"无法将处理后的参数序列化为 JSON: {args}, 错误: {e}")
                continue

            # 构建 OpenAI 格式的最终工具调用结构
            # 注意：OpenAI 格式通常需要一个 'id'，这里我们生成一个简单的
            tool_call_id = f"call_{random.randint(1000, 9999)}"
            processed_calls.append({
                "id": tool_call_id,
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": processed_args_str
                }
            })
        else:
             logger.warning(f"接收到非函数调用的工具调用部分: {call}")

    # 返回处理后的工具调用列表
    return processed_calls