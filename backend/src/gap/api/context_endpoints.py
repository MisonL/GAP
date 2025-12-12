# -*- coding: utf-8 -*-
"""上下文管理 API 端点

提供简单的管理接口，用于列出和删除对话上下文。
当前接口仅面向管理员，通过 `X-Admin-Token` 进行保护。
"""
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from gap.core.context.store import ContextStore
from gap.core.dependencies import (
    get_context_store_manager,
    get_db_session,
    verify_admin_token,
)

logger = logging.getLogger("my_logger")

router = APIRouter()


@router.get("/v1/contexts", response_model=List[Dict[str, Any]])
async def list_contexts(
    _: bool = Depends(verify_admin_token),
    db: AsyncSession = Depends(get_db_session),
    context_store: ContextStore = Depends(get_context_store_manager),
) -> List[Dict[str, Any]]:
    """列出当前存储中的所有上下文概要信息（管理员视角）。

    返回的数据来自 `ContextStore.get_context_info_for_management`，
    包含 `id` / `user_id` / `context_key` / `created_at` / `last_accessed_at` 等字段。
    """
    try:
        # 管理员视角：不按 user_id 过滤，展示所有上下文概要
        contexts = await context_store.get_context_info_for_management(
            user_id=None, is_admin=True, db=db
        )
        logger.info("上下文管理: 返回 %d 条上下文概要记录", len(contexts))
        return contexts
    except Exception as e:
        logger.error("列出上下文时发生错误: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取上下文列表失败",
        )


@router.delete("/v1/contexts/{context_id}")
async def delete_context_by_id(
    context_id: int,
    _: bool = Depends(verify_admin_token),
    db: AsyncSession = Depends(get_db_session),
    context_store: ContextStore = Depends(get_context_store_manager),
) -> Dict[str, Any]:
    """根据上下文 ID 删除单条上下文记录（管理员接口）。"""
    try:
        # 管理员接口: 允许删除任意 ID，不按 user_id 限制
        success = await context_store.delete_context_by_id(
            context_id=context_id, user_id=None, is_admin=True, db=db
        )
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="上下文未找到或已被删除",
            )
        logger.info("上下文管理: 已删除上下文 ID %s", context_id)
        return {"message": f"上下文 {context_id} 删除成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("删除上下文 ID %s 时发生错误: %s", context_id, e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="删除上下文失败",
        )
