# -*- coding: utf-8 -*-
import logging
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from gap.core.keys.manager import APIKeyManager
from gap.core.processing.utils import estimate_token_count, truncate_context

logger = logging.getLogger("my_logger")


async def select_and_prepare_key(
    key_manager: APIKeyManager,
    model_name: str,
    limits: Dict[str, Any],
    initial_contents: List[Dict[str, Any]],
    gemini_contents: List[Dict[str, Any]],
    user_id: Optional[str],
    enable_sticky_session: bool,
    request_id: str,
    cached_content_id: Optional[str],
    db: AsyncSession,
) -> Tuple[Optional[str], List[Dict[str, Any]], bool]:
    """
    Selects the best API key and prepares the content (including dynamic truncation).

    Returns:
        Tuple[Optional[str], List[Dict[str, Any]], bool]:
        - selected_key: The selected API key (or None).
        - prepared_contents: The content ready for the API call (possibly truncated).
        - should_skip: Whether the selected key should be skipped (e.g. due to context limit).
    """
    merged_contents_for_estimation = initial_contents + gemini_contents
    estimated_input_tokens = estimate_token_count(merged_contents_for_estimation)
    logger.debug(
        f"Request {request_id}: Estimated input tokens: {estimated_input_tokens}"
    )

    selected_key, available_input_tokens = await key_manager.select_best_key(
        model_name=model_name,
        model_limits=limits,
        estimated_input_tokens=estimated_input_tokens,
        user_id=user_id,
        enable_sticky_session=enable_sticky_session,
        request_id=request_id,
        cached_content_id=cached_content_id,
        db=db,
    )

    if not selected_key:
        return None, [], False

    logger.info(f"Request {request_id}: Selected Key: {selected_key[:8]}...")

    # Dynamic truncation
    merged_contents_for_api = initial_contents + gemini_contents
    dynamic_limit_for_truncation = available_input_tokens

    truncated_contents_for_api, context_over_limit_after_truncation = (
        await truncate_context(
            contents=merged_contents_for_api,
            model_name=model_name,
            dynamic_max_tokens_limit=dynamic_limit_for_truncation,
        )
    )

    if context_over_limit_after_truncation:
        logger.error(
            f"Request {request_id}: Context over limit after dynamic truncation ({estimate_token_count(truncated_contents_for_api)} tokens). Skipping key."
        )
        key_manager.record_selection_reason(
            selected_key, "Context Over Limit After Dynamic Truncation", request_id
        )
        return selected_key, [], True

    return selected_key, truncated_contents_for_api, False
