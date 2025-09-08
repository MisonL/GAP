# -*- coding: utf-8 -*-
"""
主请求处理程序，包含 process_request 和 _attempt_api_call 逻辑。
此模块负责协调处理来自 API 端点的请求，包括：
- 解析请求数据
- 加载和处理上下文
- 选择合适的 API Key
- 调用 Gemini API (流式或非流式)
- 处理 API 响应和错误
- 更新速率限制和 Token 计数
- 创建缓存条目
- 保存上下文
"""
import asyncio # 异步 IO 库
import json # JSON 处理库
import logging # 日志库
import time # 时间库
import pytz # 时区库
import uuid # UUID 生成库
from datetime import datetime # 日期时间库
import random # 随机数库 (可能在 Key 选择策略中使用)
import hashlib # 哈希库 (可能在缓存中使用)
from typing import Literal, List, Tuple, Dict, Any, Optional, Union # 类型提示
from fastapi import HTTPException, Request, status, Depends # FastAPI 相关组件
from fastapi.responses import StreamingResponse # 流式响应
from collections import Counter, defaultdict # 集合库
import httpx # HTTP 客户端库
from sqlalchemy.orm import Session # SQLAlchemy 同步会话 (可能在某些依赖中使用)
from sqlalchemy.ext.asyncio import AsyncSession # SQLAlchemy 异步会话
from aiosqlite import Connection # aiosqlite 连接类型 (可能在某些依赖中使用)

# 导入模型定义
from gap.api.models import ChatCompletionRequest, ChatCompletionResponse, ResponseMessage # API 请求/响应模型

# 导入核心模块的类和函数
from gap.core.services.gemini import GeminiClient # Gemini API 客户端
from gap.core.utils.response_wrapper import ResponseWrapper # 响应包装器
from gap.core.context import store as context_store # 上下文存储模块
from gap.core.database import utils as db_utils # 数据库工具模块
from gap.core.context.converter import convert_messages # 消息格式转换器
from gap.core.keys.manager import APIKeyManager # Key 管理器
from gap.core.cache.manager import CacheManager # 缓存管理器
from gap.core.processing.error_handler import _handle_api_call_exception # 统一的 API 调用异常处理器
from gap.core.utils.request_helpers import get_client_ip, get_current_timestamps # 请求辅助函数 (移除 protect_from_abuse)
from gap.core.security.rate_limit import protect_from_abuse # 从新路径导入
# 导入依赖注入函数
from gap.core.dependencies import get_db_session, get_key_manager, get_cache_manager, get_http_client # FastAPI 依赖项

# 导入处理工具函数
from gap.core.processing.utils import ( # 从 utils 模块导入
    estimate_token_count, truncate_context, check_rate_limits_and_update_counts,
    update_token_counts, save_context_after_success
)

# 导入流处理函数
from gap.core.processing.stream_handler import generate_stream_response # 从 stream_handler 导入流生成器

# 导入配置
from gap import config # 应用配置
from gap.config import ( # 导入具体配置项
    DISABLE_SAFETY_FILTERING, # 是否禁用安全过滤
    MAX_REQUESTS_PER_MINUTE, # 每分钟最大请求数 (可能用于 IP 限制)
    ENABLE_NATIVE_CACHING, # 是否启用原生缓存
    ENABLE_STICKY_SESSION, # 是否启用粘性会话 (Key 选择)
    STREAM_SAVE_REPLY, # 是否在流式响应中保存回复 (可能已废弃)
    MAX_REQUESTS_PER_DAY_PER_IP, # 每个 IP 每日最大请求数 (可能用于 IP 限制)
    safety_settings, # 默认安全设置
    safety_settings_g2 # Gemini 2.0 Flash 的安全设置
)

# 导入跟踪相关
from gap.core.tracking import ( # 导入用于跟踪和限制的数据结构及锁
    usage_data, usage_lock, RPM_WINDOW_SECONDS, TPM_WINDOW_SECONDS, # Key 使用数据和锁，时间窗口常量
    ip_daily_input_token_counts, ip_input_token_counts_lock, # IP 每日 Token 计数和锁
    increment_cache_hit_count, increment_cache_miss_count, add_tokens_saved, # 缓存统计函数
    track_cache_hit, track_cache_miss # 缓存命中/未命中跟踪函数
)

# 导入日志格式化函数 (如果需要自定义格式)
# from gap.handlers.log_config import format_log_message

logger = logging.getLogger('my_logger') # 获取日志记录器实例

# --- 核心 API 调用尝试逻辑 ---
async def _attempt_api_call(
    chat_request: ChatCompletionRequest, # 聊天请求对象
    contents: List[Dict[str, Any]], # 经过处理和可能截断后，要发送给 Gemini API 的内容列表
    system_instruction: Optional[str], # 系统指令文本
    current_api_key: str, # 本次尝试选定的 API Key
    http_client: httpx.AsyncClient, # 共享的 HTTP 客户端实例
    key_manager: APIKeyManager, # Key 管理器实例，用于错误处理时标记 Key
    model_name: str, # 请求的模型名称
    limits: Optional[Dict[str, Any]], # 该模型的速率限制配置
    client_ip: str, # 客户端 IP 地址，用于日志和可能的关联
    today_date_str_pt: str, # 当前太平洋时区日期字符串，用于 Token 计数
    enable_native_caching: bool, # 是否启用原生缓存
    cache_manager_instance: CacheManager, # 缓存管理器实例
    request_id: Optional[str] = None, # 请求的唯一 ID，用于日志跟踪
    # --- 缓存相关参数 ---
    cached_content_id_to_use: Optional[str] = None, # 如果缓存命中，传递缓存内容的 ID 给 Gemini API
    content_to_cache_on_success: Optional[Dict[str, Any]] = None, # 如果缓存未命中，成功后需要缓存的原始内容
    user_id: Optional[str] = None, # 用户 ID，用于缓存创建和用户关联
    db: AsyncSession = None # 数据库会话 (异步)
) -> Tuple[Optional[Union[StreamingResponse, ChatCompletionResponse]], Optional[Dict[str, Any]], bool]:
    """
    尝试使用给定的 API Key 和内容进行一次对 Gemini API 的调用。
    此函数封装了单次 API 调用的逻辑，包括流式和非流式处理、
    原生缓存的创建（如果需要且调用成功）、以及基本的成功/失败判断。

    Args:
        (参数说明见上方的类型提示)

    Returns:
        Tuple[Optional[Union[StreamingResponse, ChatCompletionResponse]], Optional[Dict[str, Any]], bool]:
        一个元组包含：
        - 第一个元素：如果调用成功，返回 FastAPI 的响应对象 (StreamingResponse 或 ChatCompletionResponse)；否则为 None。
        - 第二个元素：如果调用失败，返回包含错误信息的字典；否则为 None。
        - 第三个元素：一个布尔值，指示调用失败后是否需要外部重试循环尝试使用其他 Key (True 表示需要重试，False 表示不需要)。
    """
    response = None # 初始化响应对象
    error_info = None # 初始化错误信息字典
    needs_retry = False # 初始化重试标志，默认为 False

    try:
        # --- 确定安全设置 ---
        # 根据全局配置或模型名称选择合适的安全设置
        # TODO: 确认 'gemini-2.0-flash-exp' 的检查逻辑是否仍然需要或准确
        current_safety_settings = safety_settings_g2 if config.DISABLE_SAFETY_FILTERING or 'gemini-2.0-flash-exp' in chat_request.model else safety_settings

        # --- 初始化 Gemini 客户端 ---
        # 每次尝试都创建一个新的客户端实例可能不是最高效的，但可以确保使用正确的 Key
        # 考虑是否可以在外部创建并传递，或者优化 GeminiClient 使其能切换 Key
        gemini_client_instance = GeminiClient(current_api_key, http_client) # 使用当前 Key 和共享的 http_client 初始化

        # --- 判断是否为流式请求 ---
        is_stream = chat_request.stream # 从请求对象中获取 stream 标志

        if is_stream:
            # --- 处理流式请求 ---
            response_id = f"chatcmpl-{int(time.time() * 1000)}" # 为本次流式响应生成一个唯一的 ID
            # 调用位于 stream_handler.py 中的异步生成器函数
            response = StreamingResponse(generate_stream_response(
                # 传递所有需要的参数给流生成器
                gemini_client_instance=gemini_client_instance,
                chat_request=chat_request,
                contents=contents, # 传递已处理和截断的内容
                safety_settings=current_safety_settings,
                system_instruction=system_instruction,
                cached_content_id=cached_content_id_to_use, # 传递缓存 ID (如果命中)
                response_id=response_id, # 传递生成的响应 ID
                enable_native_caching=enable_native_caching,
                cache_manager_instance=cache_manager_instance,
                content_to_cache_on_success=content_to_cache_on_success, # 传递待缓存内容 (如果未命中)
                db_for_cache=db, # 传递数据库会话
                user_id_for_mapping=user_id, # 传递用户 ID
                key_manager=key_manager, # 传递 Key 管理器
                selected_key=current_api_key, # 传递当前使用的 Key
                model_name=model_name, # 传递模型名称
                limits=limits, # 传递模型限制
                client_ip=client_ip, # 传递客户端 IP
                today_date_str_pt=today_date_str_pt, # 传递日期字符串
            ), media_type="text/event-stream") # 设置响应媒体类型为 SSE
            logger.info(f"流式响应已启动 (Key: {current_api_key[:8]}, ID: {response_id})") # 记录流启动日志
            # 流式请求一旦成功启动（StreamingResponse 对象创建成功），就认为本次尝试成功，不需要重试。
            # 流内部的错误由 generate_stream_response 自行处理并发送给客户端。
            return response, None, False # 返回响应对象，无错误信息，不需重试

        else:
            # --- 处理非流式请求 ---
            # 调用 Gemini 客户端的非流式聊天方法
            # 注意：缓存命中/未命中的跟踪已移至 process_request 函数的缓存查找逻辑部分
            response_obj = await gemini_client_instance.complete_chat(
                request=chat_request, # 传递原始请求
                contents=contents, # 传递处理和截断后的内容
                safety_settings=current_safety_settings, # 传递安全设置
                system_instruction=system_instruction, # 传递系统指令
                cached_content_id=cached_content_id_to_use # 传递缓存 ID (如果命中)
            )
            # 假设 complete_chat 返回的是 ResponseWrapper 实例或兼容的对象
            if isinstance(response_obj, ResponseWrapper):
                 # 将 Gemini 的响应格式化为 OpenAI 的 ChatCompletionResponse 格式
                 response = ChatCompletionResponse(
                     id=f"chatcmpl-{int(time.time() * 1000)}", # 生成响应 ID
                     object="chat.completion", # 固定值
                     created=int(time.time()), # 创建时间戳
                     model=chat_request.model, # 使用请求中的模型名称
                     choices=[{ # choices 列表
                         "index": 0, # 索引
                         "message": ResponseMessage( # 消息体
                             role="assistant", # 角色为助手
                             content=response_obj.text, # 模型回复文本
                             tool_calls=response_obj.tool_calls # 模型返回的工具调用 (如果支持)
                         ),
                         "finish_reason": response_obj.finish_reason # 完成原因
                     }],
                     usage={ # 使用量信息
                         "prompt_tokens": response_obj.prompt_token_count or 0, # 输入 Token 数
                         "completion_tokens": response_obj.candidates_token_count or 0, # 输出 Token 数
                         "total_tokens": response_obj.total_token_count or 0 # 总 Token 数
                     }
                 )
            else:
                 # 如果 complete_chat 返回了非预期的类型，记录错误并抛出异常
                 logger.error(f"complete_chat 返回了意外的类型: {type(response_obj)}") # 记录错误日志
                 raise TypeError("API 调用返回了非预期的响应类型") # 抛出类型错误


            # --- 非流式请求成功后的处理 ---
            # 1. 更新 Key 的最后使用时间戳
            with usage_lock: # 使用锁保证线程安全
                # 确保 usage_data 中存在对应的 Key 和模型条目
                key_usage = usage_data.setdefault(current_api_key, defaultdict(lambda: defaultdict(int)))[model_name]
                key_usage['last_used_timestamp'] = time.time() # 更新时间戳
                logger.debug(f"非流式请求成功，更新 Key {current_api_key[:8]}... ({model_name}) 的 last_used_timestamp") # 记录日志

            # 2. 更新 Token 计数
            if response.usage: # 确保响应中包含 usage 信息
                 prompt_tokens = response.usage.prompt_tokens # 获取输入 Token 数
                 # 调用位于 utils.py 中的函数更新计数
                 update_token_counts(current_api_key, model_name, limits, prompt_tokens, client_ip, today_date_str_pt) # 移除 await
                 logger.debug(f"非流式请求成功，更新 Key {current_api_key[:8]}... ({model_name}) 的 Token 计数 (占位符)。") # 记录日志
            else:
                 # 如果响应中没有 usage 信息，记录警告
                 logger.warning(f"非流式响应成功但未找到 usage metadata (Key: {current_api_key[:8]}...). Token counts not updated.") # 记录警告

            # 3. 创建缓存 (如果启用了原生缓存、是缓存未命中且调用成功)
            if enable_native_caching and content_to_cache_on_success:
                logger.debug(f"非流式请求成功且是缓存未命中，尝试创建新缓存 (Key: {current_api_key[:8]}...)") # 记录日志
                try:
                    # 确保数据库会话和用户 ID 有效
                    if db and user_id is not None:
                        # 获取当前 Key 在数据库中的 ID
                        api_key_id = await key_manager.get_key_id(current_api_key)
                        if api_key_id is not None: # 确保成功获取到 ID
                            # 调用缓存管理器的 create_cache 方法
                            new_cache_id = await cache_manager_instance.create_cache(
                                db=db, # 传递数据库会话
                                user_id=user_id, # 传递用户 ID
                                api_key_id=api_key_id, # 传递 Key 的数据库 ID
                                content=content_to_cache_on_success, # 传递要缓存的原始内容
                                ttl=3600 # 设置缓存有效期（例如 1 小时）
                            )
                            if new_cache_id: # 如果成功创建缓存
                                logger.info(f"新缓存创建成功: {new_cache_id} (Key: {current_api_key[:8]}...)") # 记录成功日志
                                # TODO: 实现 Key 与缓存的关联更新逻辑 (在 key_manager 中)
                            else: # 如果创建失败
                                logger.warning(f"创建新缓存失败 (Key: {current_api_key[:8]}...)") # 记录失败警告
                        else: # 如果无法获取 Key ID
                            logger.warning(f"无法获取 Key {current_api_key[:8]}... 的 ID，跳过缓存创建。") # 记录警告
                    else: # 如果数据库会话或用户 ID 无效
                        logger.warning(f"db session ({'有效' if db else '无效'}) 或 user_id ({user_id if user_id is not None else '无效'}) 无效，跳过缓存创建。") # 记录警告
                except Exception as cache_create_err:
                    # 捕获并记录缓存创建过程中可能发生的异常
                    logger.error(f"创建缓存时发生异常 (Key: {current_api_key[:8]}...): {cache_create_err}", exc_info=True) # 记录错误

            # 4. 传统上下文保存逻辑已移至 process_request 函数末尾

            # 非流式请求成功，返回响应对象，无错误信息，不需重试
            return response, None, False

    except Exception as api_exc:
        # --- 处理 API 调用过程中发生的任何异常 ---
        # 使用统一的异常处理函数 _handle_api_call_exception (位于 error_handler.py)
        # 该函数会格式化错误信息、记录日志、可能标记 Key 状态，并返回是否需要重试
        logger.error(f"请求 {request_id}: _attempt_api_call 捕获到异常: {type(api_exc).__name__} - {str(api_exc)}", exc_info=True) # 添加详细异常日志
        error_info, needs_retry_from_exception = await _handle_api_call_exception(
            exc=api_exc,
            current_api_key=current_api_key,
            key_manager=key_manager,
            is_stream=is_stream,
            request_id=request_id
        )
        # 返回 None 表示没有成功响应，同时返回错误信息和重试标志
        return None, error_info, needs_retry_from_exception


# --- 主请求处理函数 ---
async def process_request(
    chat_request: ChatCompletionRequest, # 经过 Pydantic 验证的请求体对象
    http_request: Request, # FastAPI 的原始请求对象
    request_type: Literal['stream', 'non-stream'], # 请求类型 ('stream' 或 'non-stream')
    auth_data: Dict[str, Any], # 经过认证中间件处理后的数据，包含 'key' 和 'config'
    # --- 依赖注入 ---
    key_manager: APIKeyManager = Depends(get_key_manager), # 注入 Key 管理器实例
    http_client: httpx.AsyncClient = Depends(get_http_client), # 注入共享的 HTTP 客户端实例
    cache_manager_instance: CacheManager = Depends(get_cache_manager), # 注入缓存管理器实例
    db: AsyncSession = Depends(get_db_session) # 注入异步数据库会话
):
    """
    处理来自 API 端点的聊天补全请求的核心逻辑。
    负责：上下文加载、消息转换、缓存查找、Key 选择、API 调用尝试与重试、
    结果处理、Token 计数更新、上下文保存等。

    Args:
        chat_request (ChatCompletionRequest): 请求体数据。
        http_request (Request): FastAPI 请求对象。
        request_type (Literal['stream', 'non-stream']): 请求类型。
        auth_data (Dict[str, Any]): 认证数据，包含 'key' (代理 Key) 和 'config' (Key 特定配置)。
        key_manager (APIKeyManager): 依赖注入的 Key 管理器。
        http_client (httpx.AsyncClient): 依赖注入的 HTTP 客户端。
        cache_manager_instance (CacheManager): 依赖注入的缓存管理器。
        db (AsyncSession): 依赖注入的数据库会话。

    Returns:
        Union[StreamingResponse, ChatCompletionResponse]: 成功时返回 FastAPI 响应对象。

    Raises:
        HTTPException: 在处理过程中发生错误时抛出，例如无可用 Key、API 错误、内部错误等。
    """
    # --- 初始化和信息提取 ---
    proxy_key = auth_data.get("key") # 获取用于认证的代理 Key (可能是 user_id 或实际 Key)
    key_config = auth_data.get("config", {}) # 获取该 Key 的特定配置
    model_name = chat_request.model # 获取请求的模型名称
    client_ip = get_client_ip(http_request) # 获取客户端 IP 地址
    _, today_date_str_pt = get_current_timestamps() # 获取太平洋时区的当前日期字符串
    request_id = f"req_{uuid.uuid4().hex[:8]}" # 为本次请求生成一个唯一的内部 ID，用于日志跟踪
    logger.info(f"开始处理请求 {request_id} (类型: {request_type}, 模型: {model_name}, Key: {proxy_key[:8]}...)") # 记录请求开始日志

    # --- 初始 IP 速率限制检查 ---
    # 在处理 Key 之前，先检查来源 IP 是否触发了滥用限制
    try:
        await protect_from_abuse( # 改为异步调用
            http_request,
            config.MAX_REQUESTS_PER_MINUTE,
            config.MAX_REQUESTS_PER_DAY_PER_IP
        )
        logger.debug(f"请求 {request_id}: IP {client_ip} 通过滥用检查。")
    except HTTPException as ip_limit_exc:
        # 如果 IP 达到限制，直接抛出异常，终止请求处理
        logger.warning(f"请求 {request_id}: IP {client_ip} 未通过滥用检查: {ip_limit_exc.detail}")
        raise ip_limit_exc

    # --- 模型名称规范化和验证 ---
    normalized_model_name = model_name.lower() # 规范化为小写
    
    # 从已加载的配置中获取支持的模型列表
    # config.MODEL_LIMITS 是在应用启动时从 model_limits.json 加载的
    supported_models_keys = config.MODEL_LIMITS.keys() 
    
    original_model_name_for_error = model_name # 保存原始模型名称用于可能的错误消息

    if normalized_model_name not in supported_models_keys:
        # 如果小写名称不在支持的键中，再尝试不区分大小写的查找
        # 这可以处理用户输入 "Gemini-Pro" 而配置文件是 "gemini-pro" 的情况
        found_case_insensitive = False
        for m_key in supported_models_keys:
            if m_key.lower() == normalized_model_name:
                logger.info(f"请求 {request_id}: 模型名称 '{original_model_name_for_error}' 通过大小写不敏感匹配规范化为 '{m_key}'。")
                model_name = m_key # 使用配置文件中的规范名称
                normalized_model_name = m_key # 更新 normalized_model_name 以确保后续逻辑一致
                found_case_insensitive = True
                break
        
        if not found_case_insensitive:
            logger.error(f"请求 {request_id}: 不支持的模型名称 '{original_model_name_for_error}' (规范化尝试: '{normalized_model_name}')。支持的模型: {list(supported_models_keys)}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"不支持的模型: '{original_model_name_for_error}'. 支持的模型包括: {', '.join(supported_models_keys)}."
            )
    else:
        # 如果小写名称直接在支持的键中，确保 model_name 使用的是该键 (处理原始大小写不同的情况)
        if model_name != normalized_model_name:
             logger.info(f"请求 {request_id}: 模型名称 '{original_model_name_for_error}' 规范化为 '{normalized_model_name}'。")
             model_name = normalized_model_name
        else:
             logger.info(f"请求 {request_id}: 模型名称 '{model_name}' 有效且大小写规范。")

    # --- 获取模型限制 ---
    # 此时 model_name 应该是 config.MODEL_LIMITS 中的一个有效键
    limits = config.MODEL_LIMITS.get(model_name) 
    if not limits:
        # 此处理论上不应发生，因为 model_name 已经过验证和规范化
        logger.critical(f"请求 {request_id}: 严重错误！模型 '{model_name}' 通过了名称校验，但在 MODEL_LIMITS 中未找到其限制配置。原始请求模型: '{original_model_name_for_error}'")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"模型 '{model_name}' 的内部配置错误。请联系管理员。")

    # --- 初始 IP 速率限制检查 (可选) ---
    # 如果需要基于 IP 进行全局速率限制，可以在这里调用 protect_from_abuse
    # protect_from_abuse(http_request, config.MAX_REQUESTS_PER_MINUTE, config.MAX_REQUESTS_PER_DAY_PER_IP)

    # --- 确定上下文和缓存策略 ---
    enable_native_caching = config.ENABLE_NATIVE_CACHING # 获取全局原生缓存配置
    # Key 特定配置优先于全局配置来决定是否启用传统上下文
    enable_context = key_config.get('enable_context_completion', config.ENABLE_CONTEXT_COMPLETION)
    if enable_native_caching: # 如果启用了原生缓存
        enable_context = False # 则强制禁用传统上下文补全，避免冲突和冗余
        logger.info(f"请求 {request_id}: 原生缓存已启用，传统上下文补全已禁用。") # 记录信息

    # --- 加载传统上下文 (如果启用) ---
    initial_contents = [] # 初始化上下文内容列表
    if enable_context and chat_request.user_id: # 仅在启用传统上下文且请求中包含 user_id 时加载
        try:
            # 调用 context_store 加载上下文，并传递 db 会话
            initial_contents = await context_store.load_context(chat_request.user_id, db=db) or [] # 加载并确保是列表
            logger.debug(f"请求 {request_id}: 传统上下文已启用 (用户: {chat_request.user_id}), 加载了 {len(initial_contents)} 条历史。") # 记录加载日志
        except Exception as context_load_err:
            # 记录加载上下文失败的错误，但不中断请求处理
            logger.error(f"请求 {request_id}: 加载上下文失败 (用户: {chat_request.user_id}): {context_load_err}", exc_info=True)
            initial_contents = [] # 加载失败时重置为空列表
    elif enable_context and not chat_request.user_id:
         # 如果启用了上下文但请求中没有 user_id，记录警告
         logger.warning(f"请求 {request_id}: 传统上下文已启用但未提供用户 ID，跳过上下文加载。")
    else:
         # 如果未启用传统上下文，记录调试信息
         logger.debug(f"请求 {request_id}: 传统上下文已禁用或未提供用户 ID，跳过上下文加载。")

    # --- 转换用户消息格式 ---
    try:
        # 调用 convert_messages 将 OpenAI 格式的消息列表转换为 Gemini 格式
        conversion_result = convert_messages(chat_request.messages)
        # convert_messages 在失败时可能返回错误详情列表，需要检查
        if isinstance(conversion_result, list): # 如果返回的是列表，说明包含错误信息
            error_detail = "; ".join(conversion_result) # 将错误信息拼接成字符串
            logger.error(f"请求 {request_id}: 转换用户消息失败: {error_detail}") # 记录错误日志
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"消息格式错误: {error_detail}") # 返回 400 错误
        # 转换成功，解包结果
        gemini_contents, system_instruction_dict = conversion_result # 获取转换后的内容和系统指令字典
        # 从系统指令字典中提取文本内容
        system_instruction_text = system_instruction_dict.get("parts", [{}])[0].get("text") if system_instruction_dict else None
    except Exception as e:
        # 捕获转换过程中可能发生的其他异常
        logger.error(f"请求 {request_id}: 转换消息时发生意外错误: {e}", exc_info=True) # 记录错误日志
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="处理消息时出错。") # 返回 400 错误


    # --- 原生缓存查找逻辑 ---
    cached_content_id_to_use = None # 初始化要使用的缓存 ID 为 None
    content_to_cache_on_success = None # 初始化成功后要缓存的内容为 None
    if enable_native_caching and chat_request.user_id: # 仅在启用原生缓存且有 user_id 时执行
        try:
            # 调用缓存管理器的 find_cache 方法查找缓存
            cached_content_id_to_use = await cache_manager_instance.find_cache(
                db=db, # 传递数据库会话
                user_id=chat_request.user_id, # 传递用户 ID
                messages=chat_request.messages # 传递原始 OpenAI 格式消息用于哈希计算
            )
            if cached_content_id_to_use: # 如果找到了缓存 (缓存命中)
                logger.info(f"请求 {request_id}: 缓存命中 (用户: {chat_request.user_id}, 缓存 ID: {cached_content_id_to_use})") # 记录命中日志
                # 调用跟踪函数记录缓存命中，并估算节省的 Token 数
                track_cache_hit(request_id, cached_content_id_to_use, estimate_token_count(initial_contents + gemini_contents)) # 移除 await
            else: # 如果未找到缓存 (缓存未命中)
                # 准备在 API 调用成功后用于创建缓存的内容 (包含原始消息和模型)
                content_to_cache_on_success = {"messages": [msg.model_dump() for msg in chat_request.messages], "model": chat_request.model}
                logger.debug(f"请求 {request_id}: 缓存未命中 (用户: {chat_request.user_id}), 将在成功后创建缓存。") # 记录未命中日志
                # 调用跟踪函数记录缓存未命中，使用内部哈希计算方法获取哈希值
                track_cache_miss(request_id, cache_manager_instance._calculate_hash(content_to_cache_on_success))
        except Exception as cache_find_err:
            # 记录查找缓存时发生的异常，但不中断请求
            logger.error(f"请求 {request_id}: 查找缓存时发生异常 (用户: {chat_request.user_id}): {cache_find_err}", exc_info=True)
    elif enable_native_caching and not chat_request.user_id:
        # 如果启用了缓存但没有 user_id，记录警告
        logger.warning(f"请求 {request_id}: 原生缓存已启用但未提供 user_id，无法进行缓存查找或创建。")


    # --- Key 选择与 API 调用重试循环 ---
    max_attempts = key_manager.get_active_keys_count() + 1 # 最大尝试次数设置为活跃 Key 数量 + 1，确保每个 Key 至少有机会尝试一次
    attempt_count = 0 # 初始化尝试计数器
    last_error_info = None # 存储最后一次尝试的错误信息
    selected_key = None # 存储当前循环选定的 Key

    # 重置 KeyManager 中为本次请求记录的已尝试 Key 集合
    key_manager.tried_keys_for_request.clear()
    logger.debug(f"请求 {request_id}: 重置已尝试 Key 列表。") # 记录日志

    # 开始循环尝试调用 API
    while attempt_count < max_attempts:
        attempt_count += 1 # 增加尝试次数
        logger.info(f"请求 {request_id}: 尝试 API 调用 (尝试 {attempt_count}/{max_attempts})") # 记录尝试日志

        # --- 选择最佳 API Key ---
        # 合并初始上下文和当前请求内容，用于估算 Token 数以辅助 Key 选择
        merged_contents_for_estimation = initial_contents + gemini_contents
        # 估算输入 Token 数
        estimated_input_tokens = estimate_token_count(merged_contents_for_estimation) # 移除 await
        logger.debug(f"请求 {request_id}: 估算本次请求输入 Token 数: {estimated_input_tokens}") # 记录估算结果

        # 调用 Key 管理器的 select_best_key 方法选择 Key
        # 此方法会考虑 Key 的状态、限制、负载、粘性会话、缓存关联等因素
        selected_key, available_input_tokens = await key_manager.select_best_key(
            model_name=model_name, # 传递模型名称
            model_limits=limits, # 传递模型限制
            estimated_input_tokens=estimated_input_tokens, # 传递估算的 Token 数
            user_id=chat_request.user_id, # 传递用户 ID (用于粘性会话和关联)
            enable_sticky_session=config.ENABLE_STICKY_SESSION, # 传递粘性会话配置
            request_id=request_id, # 传递请求 ID 用于日志
            cached_content_id=cached_content_id_to_use, # 传递缓存 ID (用于缓存关联选择)
            db=db # 传递数据库会话
        )

        if selected_key: # 如果成功选定了一个 Key
            logger.info(f"请求 {request_id}: 第 {attempt_count} 次尝试，选定 Key: {selected_key[:8]}...") # 记录选定的 Key (部分隐藏)

            # --- 合并内容并进行动态截断 ---
            # 准备发送给 API 的完整内容（包含历史和当前消息）
            merged_contents_for_api = initial_contents + gemini_contents
            # 使用 select_best_key 返回的该 Key 当前可用的输入 Token 数作为动态截断限制
            dynamic_limit_for_truncation = available_input_tokens
            logger.debug(f"请求 {request_id}: 选定 Key {selected_key[:8]}... 剩余可用输入 Token (用于动态截断): {available_input_tokens}") # 记录可用 Token

            # 调用 truncate_context 进行动态截断 (注意：truncate_context 现在是异步的)
            truncated_contents_for_api, context_over_limit_after_truncation = await truncate_context(
                contents=merged_contents_for_api, # 传递合并后的内容
                model_name=model_name, # 传递模型名称
                dynamic_max_tokens_limit=dynamic_limit_for_truncation # 传递动态限制
            )

            # 检查截断后是否仍然超限
            if context_over_limit_after_truncation:
                 # 如果截断后仍然超限，记录错误，标记此 Key 为已尝试，并跳过此 Key 进行下一次循环
                 logger.error(f"请求 {request_id}: 动态截断后上下文仍然超限 ({estimate_token_count(truncated_contents_for_api)} tokens)。跳过此 Key。") # 移除 await
                 key_manager.record_selection_reason(selected_key, "Context Over Limit After Dynamic Truncation", request_id) # 记录跳过原因
                 key_manager.tried_keys_for_request.add(selected_key) # 添加到已尝试集合
                 continue # 继续下一次循环

            # --- 尝试调用 API ---
            # 调用内部函数 _attempt_api_call 执行实际的 API 请求
            response, error_info, needs_retry = await _attempt_api_call(
                chat_request=chat_request, # 传递请求对象
                contents=truncated_contents_for_api, # 传递截断后的内容
                system_instruction=system_instruction_text, # 传递提取的系统指令文本
                current_api_key=selected_key, # 传递选定的 Key
                http_client=http_client, # 传递 HTTP 客户端
                key_manager=key_manager, # 传递 Key 管理器
                model_name=model_name, # 传递模型名称
                limits=limits, # 传递模型限制
                client_ip=client_ip, # 传递客户端 IP
                today_date_str_pt=today_date_str_pt, # 传递日期字符串
                enable_native_caching=enable_native_caching, # 传递缓存启用标志
                cache_manager_instance=cache_manager_instance, # 传递缓存管理器
                request_id=request_id, # 传递请求 ID
                cached_content_id_to_use=cached_content_id_to_use, # 传递缓存 ID
                content_to_cache_on_success=content_to_cache_on_success, # 传递待缓存内容
                user_id=chat_request.user_id, # 传递用户 ID
                db=db # 传递数据库会话
            )

            # --- 处理 API 调用结果 ---
            if response: # 如果成功获取到响应对象
                logger.info(f"请求 {request_id}: API 调用成功 (Key: {selected_key[:8]}..., 尝试 {attempt_count})") # 记录成功日志
                # 更新用户与 Key 的关联（仅在数据库模式下且有用户 ID 时）
                if chat_request.user_id and config.KEY_STORAGE_MODE == 'database':
                     try:
                         await key_manager.update_user_key_association(db, chat_request.user_id, selected_key) # 更新关联
                         logger.debug(f"请求 {request_id}: 更新用户 {chat_request.user_id} 与 Key {selected_key[:8]}... 的关联。") # 记录日志
                     except Exception as assoc_err:
                         logger.error(f"请求 {request_id}: 更新用户 Key 关联失败: {assoc_err}", exc_info=True) # 记录错误

                # --- 非流式请求的上下文保存 ---
                # 仅在非流式、未启用原生缓存、启用了传统上下文且有用户 ID 时执行
                if request_type == 'non-stream' and not enable_native_caching and enable_context and chat_request.user_id:
                    if isinstance(response, ChatCompletionResponse): # 确保响应类型正确
                        # 提取模型回复内容
                        model_reply_content = response.choices[0].message.content if response.choices and response.choices[0].message else ""
                        if model_reply_content: # 确保回复内容不为空
                            # 调用位于 utils.py 的函数保存上下文
                            await save_context_after_success(
                                proxy_key=chat_request.user_id, # 使用 user_id 作为上下文的 Key
                                contents_to_send=merged_contents_for_api, # 传递合并后的原始内容（包含历史）
                                model_reply_content=model_reply_content, # 传递模型回复
                                model_name=model_name, # 传递模型名称
                                enable_context=True, # 确认启用上下文
                                final_tool_calls=response.choices[0].message.tool_calls if response.choices and response.choices[0].message else None # 传递工具调用信息
                            )
                        else:
                            # 如果回复内容为空，记录警告
                            logger.warning(f"请求 {request_id}: 非流式响应成功但回复内容为空，跳过上下文保存。")
                    else:
                         # 如果响应类型不匹配，记录警告
                         logger.warning(f"请求 {request_id}: 非流式响应类型异常 ({type(response)})，跳过上下文保存。")
                # --- 结束上下文保存 ---

                return response # 返回成功的响应对象，结束处理流程

            elif needs_retry: # 如果 API 调用失败但指示需要重试 (例如 5xx 错误, Key 配额耗尽)
                logger.warning(f"请求 {request_id}: API 调用失败，需要重试 (Key: {selected_key[:8]}..., 尝试 {attempt_count}). 错误: {error_info.get('message', '未知错误')}") # 记录重试日志
                last_error_info = error_info # 保存错误信息
                key_manager.tried_keys_for_request.add(selected_key) # 将此 Key 加入已尝试集合
                continue # 继续下一次循环，尝试选择其他 Key

            else: # 如果 API 调用失败且不需要重试 (例如 4xx 客户端错误, 无效 Key)
                logger.error(f"请求 {request_id}: API 调用失败，无需重试 (Key: {selected_key[:8]}..., 尝试 {attempt_count}). 错误: {error_info.get('message', '未知错误')}") # 记录失败日志
                last_error_info = error_info # 保存错误信息
                # 注意：这里不需要将 Key 加入 tried_keys_for_request，因为 Key 本身可能有问题，不应再试
                break # 退出重试循环，将向客户端返回错误

        else: # 如果 key_manager.select_best_key 未能选择到可用的 Key
            logger.warning(f"请求 {request_id}: 第 {attempt_count} 次尝试未找到可用 Key。") # 记录警告
            # 设置默认错误信息，表明所有 Key 都不可用或已尝试过
            last_error_info = {"message": "所有可用 API Key 均尝试失败或达到限制。", "type": "key_error", "code": status.HTTP_503_SERVICE_UNAVAILABLE}
            # 可以选择在这里稍微等待一下，给 Key 状态恢复或限制重置留出时间
            await asyncio.sleep(0.5) # 短暂等待 0.5 秒

    # --- 循环结束仍未成功 ---
    # 如果循环正常结束（尝试次数耗尽）或者因为无需重试的错误而 break，执行以下逻辑
    logger.error(f"请求 {request_id}: 所有 API 调用尝试均失败。") # 记录最终失败日志
    # 构造最终的错误详情和状态码
    error_detail = last_error_info.get("message", "所有尝试均失败，无法处理请求。") if last_error_info else "所有尝试均失败，无法处理请求。"
    status_code = last_error_info.get("code", status.HTTP_503_SERVICE_UNAVAILABLE) if last_error_info else status.HTTP_503_SERVICE_UNAVAILABLE
    # 抛出 HTTPException，将错误返回给客户端
    raise HTTPException(status_code=status_code, detail=error_detail)
