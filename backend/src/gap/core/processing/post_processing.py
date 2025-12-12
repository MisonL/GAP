# -*- coding: utf-8 -*-
import logging
from typing import Any, Dict, List, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from gap import config
from gap.api.models import ChatCompletionResponse
from gap.core.keys.manager import APIKeyManager
from gap.core.context.store import ContextStore
from gap.core.processing.utils import save_context_after_success

logger = logging.getLogger("my_logger")


async def handle_post_processing(
    response: Any,
    request_type: Literal["stream", "non-stream"],
    chat_request: Any,
    selected_key: str,
    model_name: str,
    merged_contents: List[Dict[str, Any]],
    enable_native_caching: bool,
    enable_context: bool,
    key_manager: APIKeyManager,
    db: AsyncSession,
    request_id: str,
    context_store: ContextStore | None = None,
):
    """
    Handles post-processing tasks after a successful API call:
    - Updating user-key association.
    - Saving context (for non-stream requests).
    """

    # 1. Update User-Key Association
    if chat_request.user_id and config.KEY_STORAGE_MODE == "database":
        try:
            await key_manager.update_user_key_association(
                db, chat_request.user_id, selected_key
            )
            logger.debug(
                f"Request {request_id}: Updated association for user {chat_request.user_id} with key {selected_key[:8]}..."
            )
        except Exception as assoc_err:
            logger.error(
                f"Request {request_id}: Failed to update user-key association: {assoc_err}",
                exc_info=True,
            )

    # 2. Save Context (Non-stream only)
    if (
        request_type == "non-stream"
        and not enable_native_caching
        and enable_context
        and chat_request.user_id
    ):
        if isinstance(response, ChatCompletionResponse):
            model_reply_content = (
                response.choices[0].message.content
                if response.choices and response.choices[0].message
                else ""
            )
            if model_reply_content:
                await save_context_after_success(
                    proxy_key=chat_request.user_id,
                    contents_to_send=merged_contents,
                    model_reply_content=model_reply_content,
                    model_name=model_name,
                    enable_context=True,
                    final_tool_calls=(
                        response.choices[0].message.tool_calls
                        if response.choices and response.choices[0].message
                        else None
                    ),
                    db=db,
                    context_store=context_store,
                )
            else:
                logger.warning(
                    f"Request {request_id}: Non-stream response empty, skipping context save."
                )
        else:
            logger.warning(
                f"Request {request_id}: Unexpected response type {type(response)}, skipping context save."
            )
