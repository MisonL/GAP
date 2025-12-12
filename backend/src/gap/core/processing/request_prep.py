# -*- coding: utf-8 -*-
import logging
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from gap import config
from gap.api.models import ChatCompletionRequest
from gap.core.context import store as context_store_module
from gap.core.context.store import ContextStore
from gap.core.context.converter import convert_messages

logger = logging.getLogger("my_logger")


def validate_model_name(model_name: str, request_id: str) -> str:
    """Validate and normalize the incoming model name.

    This helper is deliberately a bit forgiving so that older client
    payloads like ``"gemini-pro"`` continue to work even when
    ``MODEL_LIMITS`` only contains newer canonical names such as
    ``"gemini-1.5-pro-latest"`` or ``"gemini-1.0-pro"``.
    """
    normalized_model_name = model_name.lower()
    supported_models_keys = list(config.MODEL_LIMITS.keys())
    original_model_name = model_name

    # 防御性处理：如果 MODEL_LIMITS 为空，尝试懒加载一次模型限制
    if not supported_models_keys:
        try:
            from gap.config import load_model_limits as _load_model_limits

            config.MODEL_LIMITS = _load_model_limits()
            supported_models_keys = list(config.MODEL_LIMITS.keys())
            logger.info(
                "Request %s: MODEL_LIMITS was empty; reloaded model limits, now have: %s",
                request_id,
                supported_models_keys,
            )
        except Exception as reload_err:
            logger.warning(
                "Request %s: Failed to reload MODEL_LIMITS dynamically: %s",
                request_id,
                reload_err,
            )

    # --- Step 1: Handle common aliases (e.g. "gemini-pro") ---
    # Build a small alias map based on the *currently* configured models.
    alias_map: Dict[str, str] = {}

    # "gemini-pro" historically mapped to the main text model. Prefer the
    # latest 1.5 Pro if available, otherwise fall back to 1.0 Pro.
    if "gemini-1.5-pro-latest" in supported_models_keys:
        alias_map["gemini-pro"] = "gemini-1.5-pro-latest"
    elif "gemini-1.0-pro" in supported_models_keys:
        alias_map["gemini-pro"] = "gemini-1.0-pro"

    if normalized_model_name in alias_map:
        target = alias_map[normalized_model_name]
        logger.info(
            "Request %s: Model '%s' mapped via alias to canonical name '%s'.",
            request_id,
            original_model_name,
            target,
        )
        return target

    # --- Step 2: Exact / case-insensitive match against configured keys ---
    if normalized_model_name not in supported_models_keys:
        found_case_insensitive = False
        for m_key in supported_models_keys:
            if m_key.lower() == normalized_model_name:
                logger.info(
                    "Request %s: Model '%s' normalized to '%s' via case-insensitive match.",
                    request_id,
                    original_model_name,
                    m_key,
                )
                model_name = m_key
                found_case_insensitive = True
                break

        if not found_case_insensitive:
            logger.error(
                "Request %s: Unsupported model '%s'. Supported: %s",
                request_id,
                original_model_name,
                list(supported_models_keys),
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Unsupported model: '{original_model_name}'. Supported: "
                    f"{', '.join(supported_models_keys)}."
                ),
            )
    else:
        if model_name != normalized_model_name:
            logger.info(
                "Request %s: Model '%s' normalized to '%s'.",
                request_id,
                original_model_name,
                normalized_model_name,
            )
            model_name = normalized_model_name
        else:
            logger.info("Request %s: Model '%s' is valid.", request_id, model_name)

    return model_name


async def prepare_context_and_messages(
    chat_request: ChatCompletionRequest,
    enable_context: bool,
    db: AsyncSession,
    request_id: str,
    context_store: Optional[ContextStore] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    Loads historical context (if enabled) and converts current messages to Gemini format.

    Returns:
        Tuple containing:
        - initial_contents (history)
        - gemini_contents (current messages)
        - system_instruction (Gemini system_instruction dict)
    """
    initial_contents: List[Dict[str, Any]] = []
    if enable_context and chat_request.user_id:
        try:
            if context_store is not None:
                loaded = await context_store.retrieve_context(
                    user_id=chat_request.user_id,
                    context_key=chat_request.user_id,
                    db=db,
                )
            else:
                # 回退到旧的直接 load_context 路径（主要用于极端场景/测试）
                loaded = await context_store_module.load_context(
                    chat_request.user_id, db=db
                )
            initial_contents = loaded or []
            logger.debug(
                f"Request {request_id}: Loaded {len(initial_contents)} history items for user {chat_request.user_id}."
            )
        except Exception as context_load_err:
            logger.error(
                f"Request {request_id}: Failed to load context for user {chat_request.user_id}: {context_load_err}",
                exc_info=True,
            )
            initial_contents = []
    elif enable_context and not chat_request.user_id:
        logger.warning(
            f"Request {request_id}: Context enabled but no user ID provided."
        )
    else:
        logger.debug(f"Request {request_id}: Context loading skipped.")

    try:
        conversion_result = convert_messages(chat_request.messages, use_system_prompt=True)
        if isinstance(conversion_result, list):
            error_detail = "; ".join(conversion_result)
            logger.error(
                f"Request {request_id}: Message conversion failed: {error_detail}"
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Message format error: {error_detail}",
            )

        gemini_contents, system_instruction_dict = conversion_result

        return initial_contents, gemini_contents, system_instruction_dict or None

    except Exception as e:
        logger.error(
            f"Request {request_id}: Unexpected error processing messages: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Error processing messages."
        )
