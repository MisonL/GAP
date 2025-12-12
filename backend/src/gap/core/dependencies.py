# -*- coding: utf-8 -*-
"""
FastAPI 依赖注入模块。
定义了用于在请求处理函数中获取共享资源（如数据库会话、Key 管理器、HTTP 客户端）
以及执行认证/授权检查的依赖项函数。
这有助于解耦代码并提高可测试性。
"""
import asyncio  # 导入 asyncio 模块，用于处理异步任务取消
import logging  # 导入日志模块
import os  # 导入 os 模块，用于访问环境变量
from typing import AsyncGenerator, Optional  # 导入异步生成器和 Optional 类型提示

import httpx  # 导入 httpx 库
from fastapi import (  # 导入 FastAPI 相关组件
    HTTPException,
    Request,
    Security,
    status,
)
from fastapi.security import (  # 导入 FastAPI 安全工具
    APIKeyHeader,
    HTTPAuthorizationCredentials,
    HTTPBearer,
)
from sqlalchemy.ext.asyncio import (  # 导入 SQLAlchemy 异步引擎与会话工厂
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from gap.core.cache.manager import CacheManager  # 导入 CacheManager 类 (新路径)
from gap.core.context.store import ContextStore  # 导入 ContextStore 类
from gap.core.keys.manager import APIKeyManager  # 导入 APIKeyManager 类 (新路径)

logger = logging.getLogger("my_logger")  # 获取日志记录器实例

# --- 共享资源依赖项 ---


def get_key_manager(request: Request) -> APIKeyManager:
    """获取共享的 :class:`APIKeyManager` 实例。

    在正常运行时，该实例应在应用启动 (lifespan) 阶段创建并挂载到
    ``request.app.state.key_manager`` 上。

    在测试环境 (``TESTING=true``) 下，如果发现 ``key_manager`` 缺失，则会
    自动创建一个仅在当前进程内有效的内存 Key 管理器，并注入至少一个
    测试用 API Key，避免因为启动流程差异导致 500/503。
    """
    key_manager = getattr(request.app.state, "key_manager", None)

    if key_manager is None:
        testing_mode = os.environ.get("TESTING", "false").lower() == "true"
        if testing_mode:
            logger.warning(
                "app.state.key_manager 缺失，在 TESTING 模式下自动创建内存 Key 管理器。"
            )
            # 懒创建一个新的内存 KeyManager，并挂到 app.state 上
            key_manager = APIKeyManager()
            request.app.state.key_manager = key_manager

            # 为测试环境注入至少一个可用的内存 Key
            try:
                from gap import config as app_config

                # 强制使用内存模式，避免依赖真实数据库
                app_config.KEY_STORAGE_MODE = "memory"

                raw_keys = (
                    getattr(app_config, "GEMINI_API_KEYS", None)
                    or os.environ.get("GEMINI_API_KEYS")
                    or "test_gemini_key_1"
                )
                os.environ.setdefault("GEMINI_API_KEYS", raw_keys)
                app_config.GEMINI_API_KEYS = raw_keys

                for key_str in raw_keys.split(","):
                    key_str = key_str.strip()
                    if not key_str:
                        continue
                    key_manager.add_key_memory(
                        key_str,
                        {
                            "description": "test key (auto)",
                            "is_active": True,
                            "expires_at": None,
                            "enable_context_completion": True,
                            "user_id": None,
                        },
                    )
                logger.info(
                    "TESTING 模式下已自动注入 %d 个内存 API Key。",
                    key_manager.get_active_keys_count(),
                )
            except Exception as e:  # pragma: no cover - 仅在测试初始化异常时触发
                logger.error(
                    f"TESTING 模式下自动初始化 Key 管理器失败: {e}",
                    exc_info=True,
                )

            return key_manager

        # 非测试环境下，如果 key_manager 缺失视为严重配置错误
        logger.error("无法从 app.state 获取 APIKeyManager 实例！请检查 lifespan 配置。")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="服务器内部错误：Key 管理器未初始化",
        )

    return key_manager


def get_http_client(request: Request) -> httpx.AsyncClient:
    """获取共享的 :class:`httpx.AsyncClient` 实例。

    正常情况下，该客户端在应用启动时创建并挂载到 ``app.state.http_client``。
    在测试环境 (``TESTING=true``) 下，如果发现缺失，则会自动创建一个
    带有合理超时配置的客户端并挂载到 ``app.state``，避免因为 lifespan
    未运行导致 500 错误。
    """
    http_client = getattr(request.app.state, "http_client", None)

    if http_client is None:
        testing_mode = os.environ.get("TESTING", "false").lower() == "true"
        if testing_mode:
            logger.warning(
                "app.state.http_client 缺失，在 TESTING 模式下自动创建 AsyncClient。"
            )
            # 使用与 main.py 中相同的超时配置（在缺省情况下退回到简化值）
            try:
                from gap import config as app_config

                timeout = httpx.Timeout(
                    connect=getattr(app_config, "HTTP_TIMEOUT_CONNECT", 10.0),
                    read=getattr(app_config, "HTTP_TIMEOUT_READ", 30.0),
                    write=getattr(app_config, "HTTP_TIMEOUT_WRITE", 30.0),
                    pool=getattr(app_config, "HTTP_TIMEOUT_POOL", 30.0),
                )
            except Exception:
                timeout = httpx.Timeout(10.0, read=30.0, write=30.0, pool=30.0)

            http_client = httpx.AsyncClient(timeout=timeout)
            request.app.state.http_client = http_client
            return http_client

        logger.error(
            "无法从 app.state 获取 httpx.AsyncClient 实例！请检查 lifespan 配置。"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="服务器内部错误：HTTP 客户端未初始化",
        )

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
    AsyncSessionFactory = getattr(request.app.state, "AsyncSessionFactory", None)
    if AsyncSessionFactory is None:
        testing_mode = os.environ.get("TESTING", "false").lower() == "true"
        if testing_mode:
            logger.warning(
                "AsyncSessionFactory 缺失，在 TESTING 模式下自动创建临时引擎与会话工厂。"
            )
            try:
                from gap.core.database import utils as db_utils

                engine = getattr(request.app.state, "db_engine", None)
                if engine is None:
                    engine = create_async_engine(db_utils.DATABASE_URL, echo=False)
                    request.app.state.db_engine = engine
                    # 确保基础表存在（用于上下文等功能）
                    try:
                        from gap.core.database.models import Base

                        async def _create_all():
                            async with engine.begin() as conn:
                                await conn.run_sync(Base.metadata.create_all)

                        await _create_all()
                    except Exception as init_err:
                        logger.error(
                            f"临时数据库表初始化失败: {init_err}", exc_info=True
                        )
                AsyncSessionFactory = async_sessionmaker(
                    bind=engine, class_=AsyncSession, expire_on_commit=False
                )
                request.app.state.AsyncSessionFactory = AsyncSessionFactory
            except Exception as e:
                logger.error(
                    f"TESTING 模式下创建临时数据库会话工厂失败: {e}", exc_info=True
                )
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="服务器内部错误：无法初始化临时数据库会话工厂",
                )
        else:
            # 如果会话工厂不存在，记录错误并抛出异常
            logger.error(
                "无法从 app.state 获取 AsyncSessionFactory！请检查 lifespan 配置。"
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="服务器内部错误：数据库会话工厂未初始化",
            )

    # 使用会话工厂创建一个新的会话实例
    session: AsyncSession = AsyncSessionFactory()
    logger.debug(f"数据库会话 {id(session)} 已创建。")  # 记录会话创建日志
    try:
        # 使用 yield 将会话实例提供给依赖此函数的路径操作函数
        yield session
        # 请求处理成功完成，不需要显式提交，因为通常在具体操作中提交
    except (Exception, asyncio.CancelledError) as e:
        # 如果在路径操作函数中使用会话时发生异常或任务被取消
        logger.error(
            f"数据库会话 {id(session)} 中发生异常，执行回滚: {e}", exc_info=True
        )  # 记录异常和回滚日志
        try:
            await session.rollback()  # 回滚事务
        except Exception as rollback_error:
            logger.error(
                f"回滚数据库会话 {id(session)} 时发生错误: {rollback_error}",
                exc_info=True,
            )
        raise e  # 重新抛出异常，让 FastAPI 的异常处理中间件处理
    finally:
        # 无论请求处理成功还是失败，最终都会执行 finally 块
        try:
            logger.debug(f"关闭数据库会话 {id(session)}...")  # 记录会话关闭日志
            await session.close()  # 关闭数据库会话，释放连接资源
        except Exception as close_error:
            logger.error(
                f"关闭数据库会话 {id(session)} 时发生错误: {close_error}", exc_info=True
            )
        # 不主动关闭 engine，交由进程生命周期处理；若需要，可在此判断 created_temp_engine 进行 dispose


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
    cache_manager = getattr(request.app.state, "cache_manager", None)
    if cache_manager is None:
        # 如果实例不存在，记录错误并抛出异常
        logger.error("无法从 app.state 获取 CacheManager 实例！请检查 lifespan 配置。")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="服务器内部错误：缓存管理器未初始化",
        )
    return cache_manager


def get_context_store_manager(request: Request) -> ContextStore:
    """获取共享的 :class:`ContextStore` 实例。

    正常情况下，该实例在应用启动时创建并挂载到 ``app.state.context_store_manager`` 上。
    在测试环境如果缺失，可以考虑后续按需懒创建；当前实现中将其视为配置错误。
    """
    context_store_manager = getattr(request.app.state, "context_store_manager", None)
    if context_store_manager is None:
        logger.error(
            "无法从 app.state 获取 ContextStore 实例！请检查 lifespan 配置是否正确初始化 context_store_manager。"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="服务器内部错误：上下文存储管理器未初始化",
        )
    return context_store_manager


# --- 认证/授权依赖项 ---

# 定义用于获取管理员令牌的 APIKeyHeader
# 它会查找名为 'X-Admin-Token' 的请求头
# auto_error=False 表示如果请求头不存在，FastAPI 不会自动报错，由依赖函数处理
admin_token_header = APIKeyHeader(name="X-Admin-Token", auto_error=False)


async def verify_admin_token(
    admin_token: Optional[str] = Security(admin_token_header),
):  # 使用 Optional[str]
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
        logger.warning(
            "环境变量 ADMIN_TOKEN 未设置，管理员接口将允许无令牌访问。"
        )  # 记录警告
        return True  # 允许访问

    # 如果环境变量设置了 ADMIN_TOKEN，则必须进行验证
    # 检查请求头中是否提供了令牌，并且是否与环境变量中的令牌匹配
    if admin_token and admin_token == admin_token_from_env:
        logger.debug("管理员令牌验证通过。")  # 记录调试日志
        return True  # 验证通过

    # 如果令牌不匹配或缺失
    logger.warning(
        f"管理员令牌验证失败。请求提供令牌: {'***' if admin_token else '无'}"
    )  # 记录警告日志
    # 抛出 401 未授权错误
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,  # 设置状态码
        detail="无效或缺失的管理员令牌",  # 设置错误详情
    )


def get_auth_data(request: Request) -> dict:
    """
    从请求中提取认证数据的辅助函数。

    Args:
        request (Request): FastAPI 请求对象

    Returns:
        dict: 包含认证信息的字典
    """
    # 检查不同类型的认证头
    auth_header = request.headers.get("Authorization")
    admin_token = request.headers.get("X-Admin-Token")

    auth_data = {
        "is_authenticated": False,
        "auth_type": None,
        "user_info": None,
        "is_admin": False,
    }

    # 管理员令牌认证
    if admin_token:
        admin_token_from_env = os.environ.get("ADMIN_TOKEN")
        if admin_token_from_env is None or admin_token == admin_token_from_env:
            auth_data["is_authenticated"] = True
            auth_data["is_admin"] = True
            auth_data["auth_type"] = "admin_token"
            auth_data["user_info"] = {"type": "admin"}
            return auth_data

    # JWT 令牌认证（简化版）
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]
        if token:  # 简单验证，实际应该验证 JWT
            auth_data["is_authenticated"] = True
            auth_data["auth_type"] = "bearer"
            auth_data["user_info"] = {"type": "user"}

    return auth_data


async def verify_jwt_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(
        HTTPBearer(auto_error=False)
    ),
):
    """
    JWT 令牌验证依赖项的简化版本。

    Args:
        credentials: HTTPBearer 认证凭据

    Returns:
        dict: 用户信息

    Raises:
        HTTPException: 认证失败时抛出异常
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token未提供",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 简化的令牌验证（实际应该验证 JWT）
    if credentials.credentials:
        return {"user_id": "test_user", "is_active": True}

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无效的令牌",
        headers={"WWW-Authenticate": "Bearer"},
    )
