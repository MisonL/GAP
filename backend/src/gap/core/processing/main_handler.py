# -*- coding: utf-8 -*-
"""
主请求处理程序，包含 process_request 逻辑。
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
import asyncio
import logging
import uuid
from typing import Any, Dict, Literal

import httpx
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from gap import config
from gap.api.models import ChatCompletionRequest
from gap.core.cache.manager import CacheManager
from gap.core.dependencies import (
    get_cache_manager,
    get_db_session,
    get_http_client,
    get_key_manager,
)
from gap.core.keys.manager import APIKeyManager
from gap.core.processing.api_caller import attempt_api_call
from gap.core.processing.key_selection import select_and_prepare_key
from gap.core.processing.post_processing import handle_post_processing
from gap.core.processing.request_prep import (
    prepare_context_and_messages,
    validate_model_name,
)
from gap.core.context.store import ContextStore
from gap.core.processing.utils import estimate_token_count
from gap.core.security.rate_limit import protect_from_abuse
from gap.core.tracking import track_cache_hit, track_cache_miss
from gap.core.utils.request_helpers import get_client_ip, get_current_timestamps

logger = logging.getLogger("my_logger")


# --- 主请求处理函数 ---
async def process_request(
    chat_request: ChatCompletionRequest,
    http_request: Request,
    request_type: Literal["stream", "non-stream"],
    auth_data: Dict[str, Any],
    key_manager: APIKeyManager = Depends(get_key_manager),
    http_client: httpx.AsyncClient = Depends(get_http_client),
    cache_manager_instance: CacheManager = Depends(get_cache_manager),
    db: AsyncSession = Depends(get_db_session),
):
    """
    处理来自 API 端点的聊天补全请求的核心逻辑。
    负责：上下文加载、消息转换、缓存查找、Key 选择、API 调用尝试与重试、
    结果处理、Token 计数更新、上下文保存等。
    """
    # --- 初始化和信息提取 ---
    key_config = auth_data.get("config", {})
    model_name = chat_request.model
    client_ip = get_client_ip(http_request)
    _, today_date_str_pt = get_current_timestamps()
    request_id = f"req_{uuid.uuid4().hex[:8]}"
    from gap.utils.secure_logger import log_request_start

    log_request_start(request_id, request_type, model_name)

    # --- 初始 IP 速率限制检查 ---
    try:
        await protect_from_abuse(
            http_request,
            config.MAX_REQUESTS_PER_MINUTE,
            config.MAX_REQUESTS_PER_DAY_PER_IP,
        )
        logger.debug(f"请求 {request_id}: IP {client_ip} 通过滥用检查。")
    except HTTPException as ip_limit_exc:
        logger.warning(
            f"请求 {request_id}: IP {client_ip} 未通过滥用检查: {ip_limit_exc.detail}"
        )
        raise ip_limit_exc

    # --- 模型名称规范化和验证 ---
    model_name = validate_model_name(model_name, request_id)
    limits = config.MODEL_LIMITS.get(model_name)
    if not limits:
        logger.critical(f"请求 {request_id}: 严重错误！模型 '{model_name}' 配置缺失。")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal configuration error.",
        )

    # --- 确定上下文和缓存策略 ---
    enable_native_caching = config.ENABLE_NATIVE_CACHING
    enable_context = key_config.get(
        "enable_context_completion", config.ENABLE_CONTEXT_COMPLETION
    )
    if enable_native_caching:
        enable_context = False
        logger.info(f"请求 {request_id}: 原生缓存已启用，传统上下文补全已禁用。")

    # --- 加载上下文和准备消息 ---
    context_store: ContextStore | None = getattr(
        http_request.app.state, "context_store_manager", None
    )
    initial_contents, gemini_contents, system_instruction = (
        await prepare_context_and_messages(
            chat_request,
            enable_context,
            db,
            request_id,
            context_store=context_store,
        )
    )

    # --- 原生缓存查找逻辑 ---
    cached_content_id_to_use = None
    content_to_cache_on_success = None
    if enable_native_caching and chat_request.user_id:
        try:
            cached_content_id_to_use = await cache_manager_instance.find_cache(
                db=db,
                user_id=chat_request.user_id,
                messages=[msg.model_dump() for msg in chat_request.messages],
            )
            if cached_content_id_to_use:
                logger.info(
                    f"请求 {request_id}: 缓存命中 (用户: {chat_request.user_id}, 缓存 ID: {cached_content_id_to_use})"
                )
                track_cache_hit(
                    request_id,
                    cached_content_id_to_use,
                    estimate_token_count(initial_contents + gemini_contents),
                )
            else:
                content_to_cache_on_success = {
                    "messages": [msg.model_dump() for msg in chat_request.messages],
                    "model": chat_request.model,
                }
                logger.debug(
                    f"请求 {request_id}: 缓存未命中 (用户: {chat_request.user_id}), 将在成功后创建缓存。"
                )
                track_cache_miss(
                    request_id,
                    cache_manager_instance._calculate_hash(content_to_cache_on_success),
                )
        except Exception as cache_find_err:
            logger.error(
                f"请求 {request_id}: 查找缓存时发生异常: {cache_find_err}",
                exc_info=True,
            )
    elif enable_native_caching and not chat_request.user_id:
        logger.warning(
            f"请求 {request_id}: 原生缓存已启用但未提供 user_id，无法进行缓存查找或创建。"
        )

    # --- Key 选择与 API 调用重试循环 ---
    max_attempts = key_manager.get_active_keys_count() + 1
    attempt_count = 0
    last_error_info = None

    key_manager.tried_keys_for_request.clear()
    logger.debug(f"请求 {request_id}: 重置已尝试 Key 列表。")

    while attempt_count < max_attempts:
        attempt_count += 1
        logger.info(
            f"请求 {request_id}: 尝试 API 调用 (尝试 {attempt_count}/{max_attempts})"
        )

        # --- 选择最佳 API Key 并准备内容 ---
        selected_key, truncated_contents_for_api, should_skip = (
            await select_and_prepare_key(
                key_manager=key_manager,
                model_name=model_name,
                limits=limits,
                initial_contents=initial_contents,
                gemini_contents=gemini_contents,
                user_id=chat_request.user_id,
                enable_sticky_session=config.ENABLE_STICKY_SESSION,
                request_id=request_id,
                cached_content_id=cached_content_id_to_use,
                db=db,
            )
        )

        if should_skip:
            if selected_key is not None:
                key_manager.tried_keys_for_request.add(selected_key)
            continue

        if not selected_key:
            logger.warning(
                f"请求 {request_id}: 第 {attempt_count} 次尝试未找到可用 Key。"
            )
            last_error_info = {
                "message": "所有可用 API Key 均尝试失败或达到限制。",
                "type": "key_error",
                "code": status.HTTP_503_SERVICE_UNAVAILABLE,
            }
            await asyncio.sleep(0.5)
            continue

        # --- 尝试调用 API ---
        response, error_info, needs_retry = await attempt_api_call(
            chat_request=chat_request,
            contents=truncated_contents_for_api,
            system_instruction=system_instruction,
            current_api_key=selected_key,
            http_client=http_client,
            key_manager=key_manager,
            model_name=model_name,
            limits=limits,
            client_ip=client_ip,
            today_date_str_pt=today_date_str_pt,
            enable_native_caching=enable_native_caching,
            cache_manager_instance=cache_manager_instance,
            request_id=request_id,
            cached_content_id_to_use=cached_content_id_to_use,
            content_to_cache_on_success=content_to_cache_on_success,
            user_id=chat_request.user_id,
            db=db,
            context_store=context_store,
        )

        # --- 处理 API 调用结果 ---
        if response:
            logger.info(
                f"请求 {request_id}: API 调用成功 (Key: {selected_key[:8]}..., 尝试 {attempt_count})"
            )

            # --- 后处理 (用户关联更新, 上下文保存) ---
            await handle_post_processing(
                response=response,
                request_type=request_type,
                chat_request=chat_request,
                selected_key=selected_key,
                model_name=model_name,
                merged_contents=initial_contents
                + gemini_contents,  # Use original merged contents for context saving
                enable_native_caching=enable_native_caching,
                enable_context=enable_context,
                key_manager=key_manager,
                db=db,
                request_id=request_id,
                context_store=context_store,
            )

            return response

        elif needs_retry:
            logger.warning(
                f"请求 {request_id}: API 调用失败，需要重试 (Key: {selected_key[:8]}...). 错误: {error_info.get('message', '未知错误' ) if error_info else '未知错误'}"
            )
            last_error_info = error_info
            key_manager.tried_keys_for_request.add(selected_key)
            continue

        else:
            logger.error(
                f"请求 {request_id}: API 调用失败，无需重试 (Key: {selected_key[:8]}...). 错误: {error_info.get('message', '未知错误') if error_info else '未知错误'}"
            )
            last_error_info = error_info
            break

    # --- 循环结束仍未成功 ---
    logger.error(f"请求 {request_id}: 所有 API 调用尝试均失败。")
    error_detail = (
        last_error_info.get("message", "所有尝试均失败，无法处理请求。")
        if last_error_info
        else "所有尝试均失败，无法处理请求。"
    )
    raw_status = (
        last_error_info.get("code", status.HTTP_503_SERVICE_UNAVAILABLE)
        if last_error_info
        else status.HTTP_503_SERVICE_UNAVAILABLE
    )
    if isinstance(raw_status, int):
        status_code_int = raw_status
    elif isinstance(raw_status, str):
        try:
            status_code_int = int(raw_status)
        except ValueError:
            status_code_int = status.HTTP_503_SERVICE_UNAVAILABLE
    else:
        status_code_int = status.HTTP_503_SERVICE_UNAVAILABLE

    raise HTTPException(status_code=status_code_int, detail=error_detail)
