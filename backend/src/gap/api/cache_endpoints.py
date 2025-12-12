# -*- coding: utf-8 -*-
"""
缓存管理 API 端点
"""
import logging
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gap.api.models import CacheEntryResponse  # 导入或定义缓存条目响应模型
from gap.core.cache.manager import CacheManager  # 导入 CacheManager (新路径)
from gap.core.database.models import CachedContent  # 导入数据库模型 (新路径)

# 使用新的路径导入依赖和模型
from gap.core.dependencies import (
    get_cache_manager,
    get_db_session,
)

# 获取名为 'my_logger' 的日志记录器实例
logger = logging.getLogger("my_logger")

router = APIRouter()


# 假设用户标识符可以通过请求头或其他方式获取，这里简化处理，
# 实际应用中需要根据认证方式获取 user_id
# 例如，可以从 JWT token 或 API Key 中提取 user_id
# 暂时使用一个模拟函数获取用户 ID
async def get_current_user_id(request: Request) -> str:
    """
    模拟获取当前用户 ID 的依赖函数。
    实际应用中需要根据认证方式实现。
    """
    # 示例：从请求头获取用户 ID (不安全，仅为演示)
    # user_id = request.headers.get("X-User-Id")
    # if not user_id:
    #     raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户未认证")
    # return user_id

    # 暂时使用一个固定的模拟用户 ID 或从请求参数获取 (如果设计允许)
    # 考虑到 ChatCompletionRequest 中有 user_id，这里可以假设从请求中获取
    # 但对于独立的管理接口，通常需要独立的认证机制。
    # 为了测试接口功能，暂时允许从查询参数获取，实际应移除
    user_id = request.query_params.get("user_id")
    if not user_id:
        # 如果没有从查询参数获取，尝试从请求体（如果适用）或依赖中获取
        # 这里简化处理，如果没提供就报错
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="需要提供 user_id 参数"
        )
    return user_id


@router.get("/v1/caches", response_model=List[CacheEntryResponse])
async def list_user_caches(
    user_id: str = Depends(get_current_user_id),  # 使用依赖获取用户 ID
    db: AsyncSession = Depends(get_db_session),  # 使用异步会话
    cache_manager: CacheManager = Depends(get_cache_manager),  # 依赖注入共享 CacheManager
):
    """
    列出当前用户的所有缓存条目。
    """
    logger.info(f"接收到列出用户 {user_id} 缓存的请求")
    try:
        # 从数据库查询属于该用户的所有缓存条目（异步 ORM 风格）
        stmt = select(CachedContent).where(CachedContent.user_id == user_id)
        result = await db.execute(stmt)
        caches = result.scalars().all()

        # 将数据库模型转换为响应模型
        response_data = []
        for cache in caches:
            try:
                created_dt = datetime.fromtimestamp(
                    float(cache.creation_timestamp), tz=timezone.utc
                )
                expires_dt = datetime.fromtimestamp(
                    float(cache.expiration_timestamp), tz=timezone.utc
                )
            except Exception:
                # 如果时间戳无效，回退为当前时间，避免因单条记录导致整个列表失败
                now_dt = datetime.now(timezone.utc)
                created_dt = now_dt
                expires_dt = now_dt

            response_data.append(
                CacheEntryResponse(
                    id=int(cache.id) if cache.id is not None else 0,
                    gemini_cache_id=str(cache.gemini_cache_id),
                    content_hash=str(cache.content_id),
                    api_key_id=int(cache.key_id) if cache.key_id is not None else None,
                    created_at=created_dt,
                    expires_at=expires_dt,
                    last_used_at=None,
                    usage_count=None,
                )
            )

        logger.info(f"成功获取用户 {user_id} 的 {len(caches)} 个缓存条目")
        return response_data

    except Exception as e:
        logger.error(f"列出用户 {user_id} 缓存时发生错误: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取缓存列表失败"
        )


@router.delete("/v1/caches/{cache_id}")
async def delete_user_cache(
    cache_id: int,  # 缓存条目的数据库 ID
    user_id: str = Depends(get_current_user_id),  # 使用依赖获取用户 ID
    db: AsyncSession = Depends(get_db_session),  # 使用异步会话
    cache_manager: CacheManager = Depends(get_cache_manager),  # 依赖注入共享 CacheManager
):
    """
    删除指定 ID 的缓存条目。
    """
    logger.info(f"接收到删除用户 {user_id} 的缓存 {cache_id} 的请求")
    try:
        # 首先验证该缓存条目是否属于当前用户
        stmt = select(CachedContent).where(
            CachedContent.id == cache_id, CachedContent.user_id == user_id
        )
        result = await db.execute(stmt)
        cache_entry = result.scalar_one_or_none()

        if not cache_entry:
            logger.warning(
                f"用户 {user_id} 尝试删除不存在或不属于自己的缓存 {cache_id}"
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="缓存条目未找到或不属于当前用户",
            )

        # 调用 CacheManager 的 delete_cache 方法删除缓存
        success = await cache_manager.delete_cache(db, cache_id)

        if success:
            logger.info(f"成功删除用户 {user_id} 的缓存 {cache_id}")
            return {"message": f"缓存条目 {cache_id} 删除成功"}
        else:
            logger.error(
                f"删除用户 {user_id} 的缓存 {cache_id} 失败 (CacheManager 返回 False)"
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="删除缓存失败"
            )

    except HTTPException:
        # 重新抛出已处理的 HTTPException
        raise
    except Exception as e:
        logger.error(
            f"删除用户 {user_id} 的缓存 {cache_id} 时发生错误: {e}", exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="删除缓存失败"
        )


# TODO: 添加到主路由或 v1/v2 路由中
