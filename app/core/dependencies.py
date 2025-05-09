# -*- coding: utf-8 -*-
"""
FastAPI 依赖注入模块。
定义了用于在请求处理函数中获取共享资源（如数据库会话、Key 管理器、HTTP 客户端）
以及执行认证/授权检查的依赖项函数。
这有助于解耦代码并提高可测试性。
"""
from fastapi import Request, status, Depends, Security, HTTPException # 导入 FastAPI 相关组件
from app.core.keys.manager import APIKeyManager # 导入 APIKeyManager 类 (新路径)
import httpx # 导入 httpx 库
from sqlalchemy.ext.asyncio import AsyncSession # 导入 SQLAlchemy 异步会话类型
from typing import AsyncGenerator, Optional # 导入异步生成器和 Optional 类型提示
from app.core.cache.manager import CacheManager # 导入 CacheManager 类 (新路径)
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials # 导入 FastAPI 安全工具
import os # 导入 os 模块，用于访问环境变量
import logging # 导入日志模块

logger = logging.getLogger('my_logger') # 获取日志记录器实例

# --- 共享资源依赖项 ---

def get_key_manager(request: Request) -> APIKeyManager:
    """
    FastAPI 依赖项函数，用于从应用状态 (`request.app.state`) 中获取共享的 `APIKeyManager` 实例。
    该实例通常在应用启动时（lifespan 事件）创建并存储在 app.state 中。

    Args:
        request (Request): FastAPI 请求对象，用于访问应用状态。

    Returns:
        APIKeyManager: 共享的 APIKeyManager 实例。
    """
    # 从 app.state 中获取 key_manager 实例
    key_manager = getattr(request.app.state, 'key_manager', None)
    if key_manager is None:
        # 如果实例不存在（理论上不应发生，除非 lifespan 配置错误），记录错误并抛出异常
        logger.error("无法从 app.state 获取 APIKeyManager 实例！请检查 lifespan 配置。")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="服务器内部错误：Key 管理器未初始化")
    return key_manager

def get_http_client(request: Request) -> httpx.AsyncClient:
    """
    FastAPI 依赖项函数，用于从应用状态 (`request.app.state`) 中获取共享的 `httpx.AsyncClient` 实例。
    该实例通常在应用启动时创建，用于执行异步 HTTP 请求。

    Args:
        request (Request): FastAPI 请求对象。

    Returns:
        httpx.AsyncClient: 共享的异步 HTTP 客户端实例。
    """
    # 从 app.state 中获取 http_client 实例
    http_client = getattr(request.app.state, 'http_client', None)
    if http_client is None:
        # 如果实例不存在，记录错误并抛出异常
        logger.error("无法从 app.state 获取 httpx.AsyncClient 实例！请检查 lifespan 配置。")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="服务器内部错误：HTTP 客户端未初始化")
    return http_client

async def get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI 依赖项函数，用于获取一个 SQLAlchemy 异步数据库会话 (`AsyncSession`)。
    此函数使用在应用启动时创建并存储在 `app.state` 中的异步会话工厂 (`AsyncSessionFactory`)
    来为每个请求创建一个独立的数据库会话。
    使用 `yield` 将会话提供给路径操作函数，并在请求处理完成后（无论成功或失败）确保会话被关闭。
    如果在路径操作函数中使用会话时发生异常，会自动执行回滚。

    Args:
        request (Request): FastAPI 请求对象。

    Yields:
        AsyncSession: 一个新的 SQLAlchemy 异步数据库会话实例。

    Raises:
        HTTPException: 如果无法从 app.state 获取会话工厂。
    """
    # 从 app.state 获取异步会话工厂
    AsyncSessionFactory = getattr(request.app.state, 'AsyncSessionFactory', None)
    if AsyncSessionFactory is None:
        # 如果会话工厂不存在，记录错误并抛出异常
        logger.error("无法从 app.state 获取 AsyncSessionFactory！请检查 lifespan 配置。")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="服务器内部错误：数据库会话工厂未初始化")

    # 使用会话工厂创建一个新的会话实例
    session: AsyncSession = AsyncSessionFactory()
    logger.debug(f"数据库会话 {id(session)} 已创建。") # 记录会话创建日志
    try:
        # 使用 yield 将会话实例提供给依赖此函数的路径操作函数
        yield session
        # 请求处理成功完成，不需要显式提交，因为通常在具体操作中提交
        # await session.commit() # 通常不在依赖项中提交
    except Exception as e:
         # 如果在路径操作函数中使用会话时发生异常
         logger.error(f"数据库会话 {id(session)} 中发生异常，执行回滚: {e}", exc_info=True) # 记录异常和回滚日志
         await session.rollback() # 回滚事务
         raise e # 重新抛出异常，让 FastAPI 的异常处理中间件处理
    finally:
        # 无论请求处理成功还是失败，最终都会执行 finally 块
        logger.debug(f"关闭数据库会话 {id(session)}...") # 记录会话关闭日志
        await session.close() # 关闭数据库会话，释放连接资源

def get_cache_manager(request: Request) -> CacheManager:
    """
    FastAPI 依赖项函数，用于从应用状态 (`request.app.state`) 中获取共享的 `CacheManager` 实例。
    该实例通常在应用启动时创建。

    Args:
        request (Request): FastAPI 请求对象。

    Returns:
        CacheManager: 共享的 CacheManager 实例。

    Raises:
        HTTPException: 如果无法从 app.state 获取 CacheManager 实例。
    """
    # 从 app.state 中获取 cache_manager 实例
    cache_manager = getattr(request.app.state, 'cache_manager', None)
    if cache_manager is None:
        # 如果实例不存在，记录错误并抛出异常
        logger.error("无法从 app.state 获取 CacheManager 实例！请检查 lifespan 配置。")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="服务器内部错误：缓存管理器未初始化")
    return cache_manager

# --- 认证/授权依赖项 ---

# 定义用于获取管理员令牌的 APIKeyHeader
# 它会查找名为 'X-Admin-Token' 的请求头
# auto_error=False 表示如果请求头不存在，FastAPI 不会自动报错，由依赖函数处理
admin_token_header = APIKeyHeader(name="X-Admin-Token", auto_error=False)

async def verify_admin_token(admin_token: Optional[str] = Security(admin_token_header)): # 使用 Optional[str]
    """
    FastAPI 依赖项函数，用于验证管理员令牌。
    从请求头 'X-Admin-Token' 中获取令牌，并与环境变量 `ADMIN_TOKEN` 进行比较。

    Args:
        admin_token (Optional[str]): 通过 `Security(admin_token_header)` 从请求头注入的令牌值。
                                     如果请求头不存在，则为 None。

    Returns:
        bool: 如果验证通过（令牌匹配或环境变量未设置），返回 True。

    Raises:
        HTTPException (401 Unauthorized): 如果令牌不匹配或缺失（且环境变量已设置）。
    """
    # 从环境变量获取预设的管理员令牌
    admin_token_from_env = os.environ.get("ADMIN_TOKEN")

    # 如果环境变量中没有设置 ADMIN_TOKEN，则认为不需要管理员认证（方便开发环境）
    if admin_token_from_env is None:
        logger.warning("环境变量 ADMIN_TOKEN 未设置，管理员接口将允许无令牌访问。") # 记录警告
        return True # 允许访问

    # 如果环境变量设置了 ADMIN_TOKEN，则必须进行验证
    # 检查请求头中是否提供了令牌，并且是否与环境变量中的令牌匹配
    if admin_token and admin_token == admin_token_from_env:
        logger.debug("管理员令牌验证通过。") # 记录调试日志
        return True # 验证通过

    # 如果令牌不匹配或缺失
    logger.warning(f"管理员令牌验证失败。请求提供令牌: {'***' if admin_token else '无'}") # 记录警告日志
    # 抛出 401 未授权错误
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, # 设置状态码
        detail="无效或缺失的管理员令牌", # 设置错误详情
    )

# 注意：verify_jwt_token 依赖项已移至 app.core.security.auth_dependencies.py
# from app.core.security.auth_dependencies import verify_jwt_token
