# -*- coding: utf-8 -*-
import logging
import time
from typing import Any, Dict, List, Optional, Tuple, Union

import httpx
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from gap import config
from gap.api.models import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    Choice,
    ResponseMessage,
    Usage,
)
from gap.config import safety_settings, safety_settings_g2
from gap.core.cache.manager import CacheManager
from gap.core.context.store import ContextStore
from gap.core.keys.manager import APIKeyManager
from gap.core.processing.error_handler import _handle_api_call_exception
from gap.core.processing.stream_handler import generate_stream_response
from gap.core.processing.utils import update_token_counts
from gap.core.services.gemini import GeminiClient
from gap.core.tracking import usage_data, usage_lock
from gap.core.utils.response_wrapper import ResponseWrapper

logger = logging.getLogger("my_logger")


async def attempt_api_call(
    chat_request: ChatCompletionRequest,
    contents: List[Dict[str, Any]],
    system_instruction: Optional[Dict[str, Any]],
    current_api_key: str,
    http_client: httpx.AsyncClient,
    key_manager: APIKeyManager,
    model_name: str,
    limits: Optional[Dict[str, Any]],
    client_ip: str,
    today_date_str_pt: str,
    enable_native_caching: bool,
    cache_manager_instance: CacheManager,
    request_id: Optional[str] = None,
    cached_content_id_to_use: Optional[str] = None,
    content_to_cache_on_success: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
    db: Optional[AsyncSession] = None,
    context_store: ContextStore | None = None,
) -> Tuple[
    Optional[Union[StreamingResponse, ChatCompletionResponse]],
    Optional[Dict[str, Any]],
    bool,
]:
    """
    Attempts to call the Gemini API with the given key and content.
    """
    response: Optional[Union[StreamingResponse, ChatCompletionResponse]] = None
    error_info: Optional[Dict[str, Any]] = None
    try:
        current_safety_settings = (
            safety_settings_g2
            if config.DISABLE_SAFETY_FILTERING
            or "gemini-2.0-flash-exp" in chat_request.model
            else safety_settings
        )

        gemini_client_instance = GeminiClient(current_api_key, http_client)

        is_stream = chat_request.stream

        if is_stream:
            response_id = f"chatcmpl-{int(time.time() * 1000)}"
            response = StreamingResponse(
                generate_stream_response(
                    gemini_client_instance=gemini_client_instance,
                    chat_request=chat_request,
                    contents=contents,
                    safety_settings=current_safety_settings,
                    system_instruction=system_instruction,
                    cached_content_id=cached_content_id_to_use,
                    response_id=response_id,
                    enable_native_caching=enable_native_caching,
                    cache_manager_instance=cache_manager_instance,
                    content_to_cache_on_success=content_to_cache_on_success,
                    db_for_cache=db,
                    user_id_for_mapping=user_id,
                    key_manager=key_manager,
                    selected_key=current_api_key,
                    model_name=model_name,
                    limits=limits,
                    client_ip=client_ip,
                    today_date_str_pt=today_date_str_pt,
                    context_store=context_store,
                ),
                media_type="text/event-stream",
            )
            logger.info(
                f"Stream response started (Key: {current_api_key[:8]}, ID: {response_id})"
            )
            return response, None, False

        else:
            response_obj = await gemini_client_instance.complete_chat(
                request=chat_request,
                contents=contents,
                safety_settings=current_safety_settings,
                system_instruction=system_instruction,
                cached_content_id=cached_content_id_to_use,
            )

            if isinstance(response_obj, ResponseWrapper):
                usage = Usage(
                    prompt_tokens=response_obj.prompt_token_count or 0,
                    completion_tokens=response_obj.candidates_token_count or 0,
                    total_tokens=response_obj.total_token_count or 0,
                )
                choice = Choice(
                    index=0,
                    message=ResponseMessage(
                        role="assistant",
                        content=response_obj.text,
                        tool_calls=response_obj.tool_calls,
                    ),
                    finish_reason=response_obj.finish_reason,
                )
                response = ChatCompletionResponse(
                    id=f"chatcmpl-{int(time.time() * 1000)}",
                    object="chat.completion",
                    created=int(time.time()),
                    model=chat_request.model,
                    choices=[choice],
                    usage=usage,
                )
            else:
                # 基于当前 GeminiClient.complete_chat 的实现，response_obj 理论上总是 ResponseWrapper
                logger.error(  # type: ignore[unreachable]
                    f"complete_chat returned unexpected type: {type(response_obj)}"
                )
                raise TypeError("Unexpected response type from API call")

            with usage_lock:
                key_usage = usage_data.setdefault(current_api_key, {}).setdefault(
                    model_name, {}
                )
                key_usage["last_used_timestamp"] = time.time()
                logger.debug(
                    f"Non-stream success, updated last_used_timestamp for {current_api_key[:8]}..."
                )

            if isinstance(response, ChatCompletionResponse) and response.usage:
                prompt_tokens = response.usage.prompt_tokens
                update_token_counts(
                    current_api_key,
                    model_name,
                    limits,
                    prompt_tokens,
                    client_ip,
                    today_date_str_pt,
                )
            else:
                logger.warning(
                    f"Non-stream success but no usage metadata (Key: {current_api_key[:8]}...)."
                )

            if enable_native_caching and content_to_cache_on_success:
                try:
                    if db and user_id is not None:
                        api_key_id = await key_manager.get_key_id(current_api_key)
                        if api_key_id is not None:
                            new_cache_id = await cache_manager_instance.create_cache(
                                db=db,
                                user_id=user_id,
                                api_key_id=api_key_id,
                                content=content_to_cache_on_success,
                                ttl=3600,
                            )
                            if new_cache_id:
                                logger.info(
                                    f"New cache created: {new_cache_id} (Key: {current_api_key[:8]}...)"
                                )
                            else:
                                logger.warning(
                                    f"Failed to create new cache (Key: {current_api_key[:8]}...)"
                                )
                        else:
                            logger.warning(
                                f"Could not get ID for key {current_api_key[:8]}..., skipping cache creation."
                            )
                    else:
                        logger.warning(
                            "Skipping cache creation: db session or user_id invalid."
                        )
                except Exception as cache_create_err:
                    logger.error(
                        f"Exception creating cache (Key: {current_api_key[:8]}...): {cache_create_err}",
                        exc_info=True,
                    )

            return response, None, False

    except Exception as api_exc:
        logger.error(
            f"Request {request_id}: _attempt_api_call exception: {type(api_exc).__name__} - {str(api_exc)}",
            exc_info=True,
        )
        error_info, needs_retry_from_exception = await _handle_api_call_exception(
            exc=api_exc,
            current_api_key=current_api_key,
            key_manager=key_manager,
            is_stream=chat_request.stream,
            request_id=request_id,
        )
        return None, error_info, needs_retry_from_exception
