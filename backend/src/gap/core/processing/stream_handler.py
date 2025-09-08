# -*- coding: utf-8 -*-
"""
处理流式响应的逻辑。
"""
import asyncio # 导入异步 IO 库
import json # 导入 JSON 处理库
import logging # 导入日志库
import time # 导入时间库
from typing import List, Dict, Any, Optional, AsyncGenerator # 导入类型提示
from collections import defaultdict # 导入 defaultdict

# 导入核心模块和类型
from gap.api.models import ChatCompletionRequest # 导入请求模型
from gap.core.services.gemini import GeminiClient # 导入 Gemini 客户端
from gap.core.keys.manager import APIKeyManager # 导入 Key 管理器类型
from gap.core.cache.manager import CacheManager # 导入缓存管理器类型
from sqlalchemy.ext.asyncio import AsyncSession # 导入异步数据库会话类型
import httpx # 导入 HTTP 客户端库，用于处理可能的 HTTP 错误

# 导入需要在这里使用的工具函数
from gap.core.processing.utils import save_context_after_success, update_token_counts # 导入工具函数
# 导入配置
from gap import config # 应用配置

# 导入跟踪相关
from gap.core.tracking import usage_data, usage_lock # 导入共享的使用数据和锁

logger = logging.getLogger('my_logger') # 获取日志记录器实例

async def handle_stream_end(
    response_id: str,
    assistant_message_yielded: bool,
    actual_finish_reason: str,
    safety_issue_detail_received: Optional[Dict[str, Any]]
) -> AsyncGenerator[str, None]:
    """
    处理流式响应结束时的逻辑，根据不同情况发送合适的结束块或错误块。
    确保最后发送 [DONE] 标记。

    Args:
        response_id (str): 本次流式响应的唯一 ID。
        assistant_message_yielded (bool): 标记在流传输过程中是否已成功生成并发送了至少一个有效的助手消息块 (content 或 tool_calls)。
        actual_finish_reason (str): 从 Gemini API 获取的实际完成原因 (例如 "STOP", "MAX_TOKENS", "SAFETY" 等)。
        safety_issue_detail_received (Optional[Dict[str, Any]]): 如果完成原因是 SAFETY，这里会包含安全问题的详细信息。

    Yields:
        str: Server-Sent Events (SSE) 格式的字符串，包含结束块、错误块或最终的 [DONE] 标记。
    """
    if not assistant_message_yielded: # 检查是否从未生成过有效内容
        # --- 处理未生成任何内容就结束的情况 ---
        if actual_finish_reason == "STOP": # 如果完成原因是正常停止 (STOP)
            if safety_issue_detail_received:
                # 情况1：模型因安全策略停止，但在此之前未输出任何内容。
                error_message_detail = f"模型因安全策略停止生成内容。详情: {safety_issue_detail_received}" # 构造错误消息
                logger.warning(f"流 {response_id}: 结束时未产生助手内容，完成原因是 STOP，但检测到安全问题。向客户端发送安全提示。详情: {safety_issue_detail_received}") # 记录警告日志
                error_code = "safety_block" # 定义错误代码
                error_type = "model_error" # 定义错误类型
            else:
                # 情况2：模型返回 STOP，但没有生成任何内容。这通常表示输入可能有问题或模型内部出现异常。
                error_message_detail = f"模型返回 STOP 但未生成任何内容。可能是由于输入问题或模型内部错误。完成原因: {actual_finish_reason}" # 构造错误消息
                logger.error(f"流 {response_id}: 结束时未产生助手内容，但完成原因是 STOP。向客户端发送错误。") # 记录错误日志
                error_code = "empty_response" # 定义错误代码
                error_type = "model_error" # 定义错误类型

            # 构造并发送错误负载
            error_payload = {
                "error": {
                    "message": error_message_detail,
                    "type": error_type,
                    "code": error_code
                }
            }
            yield f"data: {json.dumps(error_payload)}\n\n" # 发送 SSE 格式的错误数据
        else:
            # 情况3：因其他原因（如 MAX_TOKENS）完成，但在此之前未输出任何内容。
            logger.warning(f"流 {response_id}: 结束时未产生助手内容 (完成原因: {actual_finish_reason})。发送包含 finish_reason 的结束块。") # 记录警告日志
            # 发送一个包含 finish_reason 的空 choice 块，符合 OpenAI 格式
            end_chunk = {
                "id": response_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": "ignored", # 模型信息通常在第一个块中提供，这里忽略
                "choices": [{"delta": {}, "index": 0, "finish_reason": actual_finish_reason}] # delta 为空，但包含 finish_reason
            }
            yield f"data: {json.dumps(end_chunk)}\n\n" # 发送 SSE 格式的结束块
    else:
        # --- 处理已生成内容后正常结束的情况 ---
        # 情况4：流中已成功生成并发送了内容，现在发送最终的结束块，包含 finish_reason。
        logger.debug(f"流 {response_id}: 正常结束，发送包含 finish_reason '{actual_finish_reason}' 的结束块。") # 记录调试日志
        end_chunk = {
            "id": response_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": "ignored", # 模型信息已在之前的块中提供
            "choices": [{"delta": {}, "index": 0, "finish_reason": actual_finish_reason}] # delta 为空，包含 finish_reason
        }
        yield f"data: {json.dumps(end_chunk)}\n\n" # 发送 SSE 格式的结束块

    # --- 最终标记 ---
    # 无论以上哪种情况，最后都需要发送 [DONE] 标记，表示 SSE 流结束。
    yield "data: [DONE]\n\n" # 发送 SSE 流结束标记


async def generate_stream_response(
    # --- Gemini Client 相关参数 ---
    gemini_client_instance: GeminiClient, # 已初始化的 Gemini 客户端实例
    chat_request: ChatCompletionRequest, # 原始的聊天请求对象
    contents: List[Dict[str, Any]], # 经过处理和可能截断后，要发送给 Gemini API 的内容列表
    safety_settings: List[Dict[str, Any]], # 安全设置列表
    system_instruction: Optional[str], # 系统指令文本
    cached_content_id: Optional[str], # 如果是缓存调用，传递缓存内容的 ID
    response_id: str, # 外部生成的本次流式响应的唯一 ID
    # --- 缓存相关参数 ---
    enable_native_caching: bool, # 是否启用原生缓存功能
    cache_manager_instance: CacheManager, # 缓存管理器实例
    content_to_cache_on_success: Optional[Dict[str, Any]], # 如果是缓存未命中，成功后需要缓存的原始内容（通常是请求体）
    db_for_cache: Optional[AsyncSession], # 数据库会话，用于缓存读写
    user_id_for_mapping: Optional[str], # 用户 ID，用于缓存查找和关联
    # --- Key 和跟踪相关参数 ---
    key_manager: APIKeyManager, # Key 管理器实例
    selected_key: str, # 本次 API 调用选定的 API Key
    model_name: str, # 本次请求使用的模型名称
    limits: Optional[Dict[str, Any]], # 该模型的速率限制配置
    client_ip: str, # 发起请求的客户端 IP 地址
    today_date_str_pt: str, # 当前太平洋时区的日期字符串 (YYYY-MM-DD)
    # --- 上下文保存相关参数 (如果需要在此处理) ---
    # enable_context: bool, # 是否启用传统上下文保存 (目前不在流中处理)
    # merged_contents_for_context: List[Dict[str, Any]], # 用于保存上下文的完整内容 (目前不在流中处理)
) -> AsyncGenerator[str, None]:
    """
    异步生成器函数，负责调用 Gemini API 的流式接口，处理返回的数据块，
    并将其格式化为 Server-Sent Events (SSE) 发送给客户端。
    同时处理流结束、错误、Token 计数、缓存创建和 Key 状态更新等逻辑。

    Args:
        (参数说明见上方的类型提示)

    Yields:
        str: Server-Sent Events (SSE) 格式的字符串数据块。
             可能的块类型包括：内容块 (delta)、工具调用块 (tool_calls)、错误块 (error)、结束块 (finish_reason)、[DONE] 标记。
    """
    # --- 初始化状态变量 ---
    stream_error_occurred = False # 标记流处理过程中是否发生错误
    assistant_message_yielded = False # 标记是否已生成并发送了有效的助手消息（文本或工具调用）
    full_reply_content = "" # 用于累积模型生成的文本内容，主要用于后续可能的上下文保存
    usage_metadata_received = None # 存储从流中接收到的使用量元数据
    actual_finish_reason = "stop" # 初始化默认的完成原因为 "stop"
    safety_issue_detail_received = None # 存储可能的安全问题详情
    final_tool_calls = None # 存储可能的工具调用信息

    try:
        # --- 调用 Gemini 客户端的流式聊天方法 ---
        # gemini_client_instance.stream_chat 是一个异步生成器
        async for chunk_data in gemini_client_instance.stream_chat(
            request=chat_request, # 传递原始请求对象
            contents=contents, # 传递处理后的内容
            safety_settings=safety_settings, # 传递安全设置
            system_instruction=system_instruction, # 传递系统指令
            cached_content_id=cached_content_id # 传递缓存 ID (如果命中)
        ):
            # --- 处理接收到的数据块 ---
            if isinstance(chunk_data, dict): # 如果是字典类型的数据块
                # 检查是否为特殊元数据块
                if '_usage_metadata' in chunk_data: # 使用量元数据
                    usage_metadata_received = chunk_data['_usage_metadata'] # 存储元数据
                    logger.debug(f"流 {response_id}: 接收到 usage metadata: {usage_metadata_received}") # 记录日志
                    continue # 元数据不直接发送给客户端，继续处理下一个块
                elif '_final_finish_reason' in chunk_data: # 最终完成原因
                    actual_finish_reason = chunk_data['_final_finish_reason'] # 更新实际完成原因
                    logger.debug(f"流 {response_id}: 接收到最终完成原因: {actual_finish_reason}") # 记录日志
                    continue # 完成原因在流结束后统一处理，继续
                elif '_safety_issue' in chunk_data: # 安全问题详情
                    safety_issue_detail_received = chunk_data['_safety_issue'] # 存储安全问题详情
                    logger.warning(f"流 {response_id}: 接收到安全问题详情: {safety_issue_detail_received}") # 记录警告日志
                    continue # 安全问题在流结束后统一处理，继续
                elif '_tool_calls' in chunk_data: # 工具调用信息
                    # 处理工具调用块 (假设 GeminiClient 会返回这种格式)
                    final_tool_calls = chunk_data['_tool_calls'] # 存储工具调用信息
                    logger.info(f"流 {response_id}: 接收到工具调用: {final_tool_calls}") # 记录日志
                    # 将工具调用信息格式化为 OpenAI SSE chunk 格式发送给客户端
                    formatted_chunk = {
                        "id": response_id,
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": model_name, # 包含模型名称
                        "choices": [{
                            "delta": {"role": "assistant", "tool_calls": final_tool_calls}, # delta 中包含 tool_calls
                            "index": 0,
                            "finish_reason": None # 工具调用不是流的最终结束
                        }]
                    }
                    yield f"data: {json.dumps(formatted_chunk)}\n\n" # 发送 SSE 数据块
                    assistant_message_yielded = True # 标记已产生有效内容
                    continue # 工具调用块处理完毕，继续处理下一个块

            elif isinstance(chunk_data, str): # 如果是字符串类型的数据块（通常是文本内容）
                # 处理文本块
                if chunk_data: # 忽略空字符串块
                    # 格式化为 OpenAI SSE chunk 格式
                    formatted_chunk = {
                        "id": response_id,
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": model_name, # 在第一个有效内容块中包含模型名称
                        "choices": [{
                            "delta": {"role": "assistant", "content": chunk_data}, # delta 中包含 content
                            "index": 0,
                            "finish_reason": None # 文本块不是最终结束
                        }]
                    }
                    yield f"data: {json.dumps(formatted_chunk)}\n\n" # 发送 SSE 数据块
                    assistant_message_yielded = True # 标记已产生有效内容
                    full_reply_content += chunk_data # 累积文本内容
            else:
                # 处理未知类型的块
                logger.warning(f"流 {response_id}: 接收到未知类型的块: {type(chunk_data)}") # 记录警告日志


        # --- 流正常结束后处理 ---
        if not stream_error_occurred: # 确保流处理过程中没有发生错误
            # 调用 handle_stream_end 生成并发送结束块或错误块，以及最终的 [DONE] 标记
            async for end_chunk_data in handle_stream_end(
                response_id,
                assistant_message_yielded,
                actual_finish_reason,
                safety_issue_detail_received
            ):
                yield end_chunk_data # 发送结束处理逻辑生成的 SSE 数据

            # --- 流成功结束后的附加处理逻辑 ---
            # 只有在成功生成了内容或工具调用时才执行后续操作
            if assistant_message_yielded or final_tool_calls:
                # 1. 更新 Token 计数 (如果收到了元数据)
                if usage_metadata_received:
                    prompt_tokens = usage_metadata_received.get('promptTokenCount') # 获取提示 Token 数
                    # 注意：update_token_counts 函数目前在 utils.py 中是占位符，需要确保其已正确实现
                    # await update_token_counts(selected_key, model_name, limits, prompt_tokens, client_ip, today_date_str_pt) # 调用更新函数
                    logger.debug(f"流 {response_id}: 请求成功，更新 Key {selected_key[:8]}... ({model_name}) 的 Token 计数 (占位符)。") # 记录日志
                else:
                    # 如果没有收到使用量元数据，记录警告
                    logger.warning(f"流 {response_id}: 响应成功但未找到 usage metadata。Token 计数未更新。") # 记录警告

                # 2. 更新 Key 的最后使用时间戳
                with usage_lock: # 使用锁保证线程安全
                    # 确保 usage_data 中存在对应的 Key 和模型条目
                    key_usage = usage_data.setdefault(selected_key, defaultdict(lambda: defaultdict(int)))[model_name]
                    key_usage['last_used_timestamp'] = time.time() # 更新时间戳
                    logger.debug(f"流 {response_id}: 请求成功，更新 Key {selected_key[:8]}... ({model_name}) 的 last_used_timestamp") # 记录日志

                # 3. 更新用户与 Key 的关联（如果提供了用户 ID 且数据库会话有效）
                if user_id_for_mapping and db_for_cache: # 确保有 user_id 和 db session
                    try:
                        # 调用 Key 管理器的函数更新关联
                        await key_manager.update_user_key_association(db_for_cache, user_id_for_mapping, selected_key)
                        logger.debug(f"流 {response_id}: 请求成功，更新用户 {user_id_for_mapping} 与 Key {selected_key[:8]}... 的关联。") # 记录日志
                    except Exception as assoc_err:
                         # 记录更新关联失败的错误
                         logger.error(f"流 {response_id}: 更新用户 Key 关联失败: {assoc_err}", exc_info=True)
                elif user_id_for_mapping and not db_for_cache:
                    # 如果有用户 ID 但没有数据库会话，记录警告
                    logger.warning(f"流 {response_id}: db session 无效，跳过用户 Key 关联更新。") # 记录警告


                # 4. 创建缓存 (如果启用了原生缓存、是缓存未命中且成功生成了内容)
                if enable_native_caching and content_to_cache_on_success:
                    logger.debug(f"流 {response_id}: 请求成功且是缓存未命中，尝试创建新缓存 (Key: {selected_key[:8]}...)") # 记录日志
                    try:
                        # 确保数据库会话和用户 ID 有效
                        if db_for_cache and user_id_for_mapping is not None:
                            # 获取当前 Key 在数据库中的 ID
                            api_key_id = await key_manager.get_key_id(selected_key)
                            if api_key_id is not None: # 确保成功获取到 ID
                                # 调用缓存管理器的 create_cache 方法
                                new_cache_id = await cache_manager_instance.create_cache(
                                    db=db_for_cache, # 传递数据库会话
                                    user_id=user_id_for_mapping, # 传递用户 ID
                                    api_key_id=api_key_id, # 传递 Key 的数据库 ID
                                    content=content_to_cache_on_success, # 传递要缓存的原始内容
                                    ttl=3600 # 设置缓存有效期（例如 1 小时）
                                )
                                if new_cache_id: # 如果成功创建缓存
                                    logger.info(f"流 {response_id}: 新缓存创建成功: {new_cache_id} (Key: {selected_key[:8]}...)") # 记录成功日志
                                    # TODO: 实现 Key 与缓存的关联更新逻辑 (在 key_manager 中)
                                else: # 如果创建失败
                                    logger.warning(f"流 {response_id}: 创建新缓存失败 (Key: {selected_key[:8]}...)") # 记录失败警告
                            else: # 如果无法获取 Key ID
                                logger.warning(f"流 {response_id}: 无法获取 Key {selected_key[:8]}... 的 ID，跳过缓存创建。") # 记录警告
                        else: # 如果数据库会话或用户 ID 无效
                            logger.warning(f"流 {response_id}: db session 或 user_id 无效，跳过缓存创建。") # 记录警告
                    except Exception as cache_create_err:
                        # 捕获并记录缓存创建过程中可能发生的异常
                        logger.error(f"流 {response_id}: 创建缓存时发生异常 (Key: {selected_key[:8]}...): {cache_create_err}", exc_info=True) # 记录错误

                # 5. 传统上下文保存 (如果 STREAM_SAVE_REPLY 为 True)
                # 注意：这里的 enable_context 可能是被原生缓存禁用的，但 STREAM_SAVE_REPLY 是一个独立的开关
                if config.STREAM_SAVE_REPLY and user_id_for_mapping and (full_reply_content or final_tool_calls):
                    logger.info(f"流 {response_id}: STREAM_SAVE_REPLY 已启用，准备保存流式响应上下文。")
                    try:
                        # contents 参数是流开始前发送给模型的内容
                        await save_context_after_success(
                            proxy_key=user_id_for_mapping,
                            contents_to_send=contents, # 这是传递给 stream_chat 的内容
                            model_reply_content=full_reply_content,
                            model_name=model_name,
                            enable_context=True, # 强制为 True，因为 STREAM_SAVE_REPLY 意味着要保存
                            final_tool_calls=final_tool_calls
                        )
                        logger.info(f"流 {response_id}: 流式响应上下文已保存。")
                    except Exception as context_save_err:
                        logger.error(f"流 {response_id}: 保存流式响应上下文失败: {context_save_err}", exc_info=True)
                elif config.STREAM_SAVE_REPLY:
                    logger.debug(f"流 {response_id}: STREAM_SAVE_REPLY 已启用，但无内容 ({'有' if full_reply_content else '无'}文本, {'有' if final_tool_calls else '无'}工具调用) 或无 user_id_for_mapping ({user_id_for_mapping})，跳过上下文保存。")
                else:
                    logger.debug(f"流 {response_id}: STREAM_SAVE_REPLY 未启用，跳过流式响应上下文保存。")

    except asyncio.CancelledError:
        # --- 处理客户端连接中断 ---
        logger.info(f"流 {response_id}: 客户端连接已中断 (IP: {client_ip})") # 记录日志
        # 连接已断开，生成器停止，不需要 yield 任何东西，FastAPI 会处理
    except httpx.HTTPStatusError as http_err:
        # --- 处理 API 调用时的 HTTP 错误 ---
        logger.error(f"流 {response_id}: API HTTP 错误: {http_err.response.status_code} - {http_err.response.text}", exc_info=False) # 记录错误日志
        stream_error_occurred = True # 标记发生错误
        # 格式化错误信息 (需要 _format_api_error 函数，此处简化)
        error_info = {"message": f"API Error: {http_err.response.status_code}", "type": "api_error", "code": http_err.response.status_code}
        yield f"data: {json.dumps({'error': error_info})}\n\n" # 发送错误信息给客户端
        yield "data: [DONE]\n\n" # 发送结束标记
    except Exception as stream_e:
        # --- 处理流处理过程中的其他意外异常 ---
        logger.error(f"流 {response_id}: 处理中捕获到意外异常: {stream_e}", exc_info=True) # 记录详细错误日志
        stream_error_occurred = True # 标记发生错误
        # 构造通用内部错误信息
        error_info = {
            "message": f"流处理中发生意外异常: {stream_e}",
            "type": "internal_error",
            "code": 500 # 使用 500 状态码表示内部错误
        }
        yield f"data: {json.dumps({'error': error_info})}\n\n" # 发送错误信息给客户端
        yield "data: [DONE]\n\n" # 发送结束标记
