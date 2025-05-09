# -*- coding: utf-8 -*-
"""
缓存管理 API 端点
"""
import logging
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
# 使用新的路径导入依赖和模型
from app.core.dependencies import get_db_session # 使用 get_db_session
from app.core.cache.manager import CacheManager # 导入 CacheManager (新路径)
from app.core.database.models import CachedContent # 导入数据库模型 (新路径)
from app.api.models import CacheEntryResponse # 导入或定义缓存条目响应模型
import os # 导入 os 模块

# 获取名为 'my_logger' 的日志记录器实例
logger = logging.getLogger('my_logger')

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
         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="需要提供 user_id 参数")
    return user_id


@router.get("/v1/caches", response_model=List[CacheEntryResponse])
async def list_user_caches(
    user_id: str = Depends(get_current_user_id), # 使用依赖获取用户 ID
    db: Session = Depends(get_db_session), # 使用 get_db_session
    cache_manager: CacheManager = Depends(CacheManager) # 依赖注入 CacheManager
):
    """
    列出当前用户的所有缓存条目。
    """
    logger.info(f"接收到列出用户 {user_id} 缓存的请求")
    try:
        # 从数据库查询属于该用户的所有缓存条目
        # 注意：这里直接查询数据库，而不是通过 CacheManager 的方法，
        # 因为 CacheManager 的方法主要针对单个缓存的操作。
        # 如果 CacheManager 提供了 list_caches 方法，应优先使用。
        # 暂时直接使用 SQLAlchemy 查询。
        caches = db.query(CachedContent).filter(CachedContent.user_id == user_id).all()

        # 将数据库模型转换为响应模型
        response_data = [
            CacheEntryResponse(
                id=cache.id,
                gemini_cache_id=cache.gemini_cache_id,
                content_hash=cache.content_hash,
                api_key_id=cache.api_key_id,
                created_at=cache.created_at,
                expires_at=cache.expires_at,
                last_used_at=cache.last_used_at,
                usage_count=cache.usage_count,
                # content 字段可能很大，响应中不包含，如果需要详情再提供单独接口
                # content=cache.content # 不在列表响应中包含 content
            ) for cache in caches
        ]

        logger.info(f"成功获取用户 {user_id} 的 {len(caches)} 个缓存条目")
        return response_data

    except Exception as e:
        logger.error(f"列出用户 {user_id} 缓存时发生错误: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取缓存列表失败")


@router.delete("/v1/caches/{cache_id}")
async def delete_user_cache(
    cache_id: int, # 缓存条目的数据库 ID
    user_id: str = Depends(get_current_user_id), # 使用依赖获取用户 ID
    db: Session = Depends(get_db_session), # 使用 get_db_session
    cache_manager: CacheManager = Depends(CacheManager) # 依赖注入 CacheManager
):
    """
    删除指定 ID 的缓存条目。
    """
    logger.info(f"接收到删除用户 {user_id} 的缓存 {cache_id} 的请求")
    try:
        # 首先验证该缓存条目是否属于当前用户
        cache_entry = db.query(CachedContent).filter(
            CachedContent.id == cache_id,
            CachedContent.user_id == user_id
        ).first()

        if not cache_entry:
            logger.warning(f"用户 {user_id} 尝试删除不存在或不属于自己的缓存 {cache_id}")
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="缓存条目未找到或不属于当前用户")

        # 调用 CacheManager 的 delete_cache 方法删除缓存
        success = await cache_manager.delete_cache(db, cache_id)

        if success:
            logger.info(f"成功删除用户 {user_id} 的缓存 {cache_id}")
            return {"message": f"缓存条目 {cache_id} 删除成功"}
        else:
            logger.error(f"删除用户 {user_id} 的缓存 {cache_id} 失败 (CacheManager 返回 False)")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="删除缓存失败")

    except HTTPException:
        # 重新抛出已处理的 HTTPException
        raise
    except Exception as e:
        logger.error(f"删除用户 {user_id} 的缓存 {cache_id} 时发生错误: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="删除缓存失败")

# TODO: 添加到主路由或 v1/v2 路由中
