# -*- coding: utf-8 -*-
"""
FastAPI 应用主入口文件。
负责初始化应用、配置、加载资源、设置路由和启动服务器。
"""
import asyncio  # 异步 IO
import logging  # 日志记录
import os  # 操作系统接口

# --- 标准库导入 ---
import sys  # 系统相关功能
from asyncio import TimeoutError  # 异步超时错误
from contextlib import asynccontextmanager  # 异步上下文管理器
from datetime import (  # 导入 datetime、timedelta 和 timezone 用于时间戳和 token 过期时间
    datetime,
    timedelta,
    timezone,
)
from typing import (  # 异步生成器类型提示, Callable, Awaitable
    AsyncGenerator,
    Awaitable,
    Callable,
)

from pydantic import BaseModel  # 用于定义登录请求的 Pydantic 模型

import httpx  # 异步 HTTP 客户端
import uvicorn  # ASGI 服务器
from dotenv import load_dotenv  # 加载 .env 文件

# --- 第三方库导入 ---
from fastapi import (  # FastAPI 框架核心类, HTTPException, Request, Response, Depends, status, Form
    Depends,
    FastAPI,
    Form,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.responses import (  # 导入 Response, FileResponse 和 JSONResponse
    FileResponse,
    JSONResponse,
)
from fastapi.staticfiles import StaticFiles  # 静态文件服务
from fastapi.routing import Mount  # 导入 Mount 类型
from sqlalchemy.ext.asyncio import async_sessionmaker  # SQLAlchemy 异步会话工厂
from sqlalchemy.ext.asyncio import (  # SQLAlchemy 异步引擎和会话; 导入异步会话工厂和异步会话类
    AsyncSession,
    create_async_engine,
)

from gap.core.security.jwt import create_access_token  # 导入创建 JWT token 的函数

# --- 应用内部模块导入 ---
# 首先导入配置模块，确保配置在其他模块导入前加载
from . import config

# 导入 API 端点路由
from .api import cache_endpoints  # 缓存管理 API
from .api import context_endpoints  # 上下文管理 API
from .api import v2_endpoints  # Gemini 原生 API (v2)
from .api import config_endpoints, config_validation, resource_endpoints  # 配置与资源管理 API
from .api import endpoints as api_endpoints  # OpenAI 兼容 API (v1)

# 从配置模块导入特定变量和函数
from .config import __version__, load_model_limits  # 移除 APP_ROOT_PATH 的导入
from .core.cache.cleanup import start_cache_cleanup_scheduler  # 缓存清理调度器启动函数
from .core.cache.manager import CacheManager  # 缓存管理器
from .core.concurrency.lock_manager import lock_manager  # 统一锁管理器
from .core.context.store import ContextStore  # 直接导入 ContextStore 类
from .core.database import utils as db_utils  # 数据库工具函数

# 导入 Key 管理相关模块
from .core.keys import checker as key_checker  # Key 检查器 (重命名以区分)
from .core.keys.manager import APIKeyManager  # Key 管理器类

# 导入报告和调度相关模块
from .core.reporting import scheduler as reporting_scheduler  # 报告调度器 (重命名以区分)
from .core.resource import resource_manager  # 统一资源管理器
from .core.resource.bootstrap import bootstrap_resource_management  # 资源管理引导程序

# 导入核心服务和工具类
from .core.services.gemini import GeminiClient  # Gemini API 客户端

# 导入错误处理程序
from .utils import error_handlers

# 导入日志配置函数
from .utils.log_config import setup_logger

# --- 初始化 ---

# 加载 .env 文件中的环境变量 (如果存在)
load_dotenv()

# 初始化并获取配置好的日志记录器实例
logger = setup_logger()

# --- 全局实例（通过 Lifespan 管理）---
# APIKeyManager, httpx.AsyncClient, CacheManager, 数据库引擎和会话工厂
# 将在应用的 lifespan 事件处理器中创建和管理，并通过 app.state 共享。


# --- Lifespan 事件处理器 ---
# 使用 asynccontextmanager 定义应用的生命周期事件处理器
# 在应用启动时执行 yield 之前的代码，在应用关闭时执行 yield 之后的代码
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    FastAPI 应用的生命周期事件处理器。
    在应用启动时执行初始化任务，在应用关闭时执行清理任务。

    Args:
        app (FastAPI): FastAPI 应用实例。

    Yields:
        None: 在应用运行期间 yield None。
    """
    # === 应用启动逻辑 ===
    logger.info(f"启动 Gemini API 代理 v{__version__}...")  # 记录应用启动日志和版本号

    # --- 配置验证 ---
    logger.info("验证系统配置...")
    try:
        from gap.core.config.validation import ensure_config_valid

        is_valid, errors, warnings = ensure_config_valid()

        if warnings:
            logger.warning("配置验证警告:")
            for warning in warnings:
                logger.warning(f"  - {warning}")

        logger.info("配置验证完成")
    except Exception as config_err:
        logger.error(f"配置验证失败: {config_err}")
        # 配置验证失败时，可以选择阻止启动或继续运行
        # 这里选择记录错误但继续运行，允许在开发环境中灵活处理
        logger.warning("配置有误，但应用将继续启动...")

    # --- 初始化共享资源实例 ---
    key_manager = APIKeyManager()  # 创建 Key 管理器实例
    # 创建共享的异步 HTTP 客户端实例，使用配置的超时设置
    timeout_config = httpx.Timeout(
        connect=config.HTTP_TIMEOUT_CONNECT,
        read=config.HTTP_TIMEOUT_READ,
        write=config.HTTP_TIMEOUT_WRITE,
        pool=config.HTTP_TIMEOUT_POOL,
    )
    http_client = httpx.AsyncClient(timeout=timeout_config)
    logger.info(
        f"共享 HTTP 客户端已初始化，超时设置为: connect={timeout_config.connect}s, read={timeout_config.read}s, write={timeout_config.write}s, pool={timeout_config.pool}s"
    )
    cache_manager = CacheManager()  # 创建缓存管理器实例
    context_store_manager = ContextStore()  # 创建上下文存储管理器实例

    # --- 将共享资源存储在应用状态 (app.state) 中 ---
    # 这样可以通过 FastAPI 的依赖注入系统在请求处理函数中访问这些实例
    app.state.key_manager = key_manager
    app.state.http_client = http_client
    app.state.cache_manager = cache_manager
    app.state.context_store_manager = context_store_manager  # 存储上下文管理器实例
    app.state.lock_manager = lock_manager  # 存储锁管理器实例
    app.state.resource_manager = resource_manager  # 存储资源管理器实例

    # --- 使用引导程序进行资源管理设置 ---
    # 在所有资源创建完成后进行统一引导
    await bootstrap_resource_management(app.state)
    logger.info("资源管理器引导完成")

    # --- 初始化数据库引擎和异步会话工厂 ---
    # 创建 SQLAlchemy 异步引擎
    db_engine = create_async_engine(
        db_utils.DATABASE_URL, echo=False
    )  # echo=False 关闭 SQL 执行日志
    # 创建异步会话工厂
    AsyncSessionFactory = async_sessionmaker(
        bind=db_engine,  # 绑定引擎
        class_=AsyncSession,  # 指定使用异步会话
        expire_on_commit=False,  # 防止在提交后 ORM 对象过期
    )
    # 将引擎和会话工厂存储在应用状态中
    app.state.db_engine = db_engine  # 用于关闭时 dispose 引擎
    app.state.AsyncSessionFactory = (
        AsyncSessionFactory  # 用于 get_db_session 依赖项创建会话
    )
    logger.info("数据库引擎和会话工厂已初始化。")  # 记录日志

    # --- 记录关键配置信息 (注意避免记录敏感信息) ---
    RED = "\033[91m"  # 定义红色 ANSI 转义码
    RESET = "\033[0m"  # 定义重置颜色的 ANSI 转义码
    if not config.ADMIN_API_KEY:  # 检查管理员 Key 是否已设置
        # 如果未设置，打印多行警告信息
        logger.warning(
            f"{RED}****************************************************************{RESET}"
        )
        logger.warning(f"{RED}警告: 管理员 API Key (ADMIN_API_KEY) 未设置！{RESET}")
        logger.warning(f"{RED}部分管理功能（如代理 Key 管理）将不可用。{RESET}")
        logger.warning(
            f"{RED}强烈建议在环境变量中配置 ADMIN_API_KEY 以启用全部功能。{RESET}"
        )
        logger.warning(
            f"{RED}****************************************************************{RESET}"
        )
    else:  # 如果已设置
        logger.info("管理员 API Key (ADMIN_API_KEY) 已配置。")

    # 记录其他配置信息
    logger.info(
        f"Web UI 密码保护已启用: {'是' if config.WEB_UI_PASSWORDS else '否'}"
    )  # 使用 WEB_UI_PASSWORDS 判断
    logger.info(
        f"本地 IP 速率限制 (可能已废弃): 每分钟最大请求数={config.MAX_REQUESTS_PER_MINUTE}, 每 IP 每日最大请求数={config.MAX_REQUESTS_PER_DAY_PER_IP}"
    )
    logger.info(f"全局禁用 Gemini 安全过滤: {config.DISABLE_SAFETY_FILTERING}")
    if config.DISABLE_SAFETY_FILTERING:
        logger.info("注意：全局安全过滤已禁用，所有请求将不包含安全设置。")
    # 检查报告间隔配置是否有效
    if config.USAGE_REPORT_INTERVAL_MINUTES == 30:  # 如果是默认值
        interval_env = os.environ.get(
            "USAGE_REPORT_INTERVAL_MINUTES"
        )  # 检查环境变量是否设置
        if interval_env:  # 如果设置了
            try:
                if int(interval_env) <= 0:  # 检查是否为无效值
                    logger.warning(
                        "环境变量 USAGE_REPORT_INTERVAL_MINUTES 必须为正整数，当前设置无效，将使用默认值 30 分钟。"
                    )
            except ValueError:  # 检查是否无法转换为整数
                logger.warning(
                    f"无法将环境变量 USAGE_REPORT_INTERVAL_MINUTES ('{interval_env}') 解析为整数，将使用默认值 30 分钟。"
                )
    # 检查报告日志级别配置是否有效
    report_level_env = os.environ.get("REPORT_LOG_LEVEL", "INFO").upper()
    if (
        config.REPORT_LOG_LEVEL_INT == logging.INFO and report_level_env != "INFO"
    ):  # 如果最终级别是 INFO 但环境变量不是 INFO
        logger.warning(
            f"无效的环境变量 REPORT_LOG_LEVEL 值 '{os.environ.get('REPORT_LOG_LEVEL')}'. 将使用默认日志级别 INFO。"
        )
    else:
        logger.info(f"使用情况报告日志级别设置为: {config.REPORT_LOG_LEVEL_STR}")

    # --- 初始化数据库表 ---
    logger.info("正在初始化数据库表...")
    if app.state.db_engine:  # 确保引擎已创建
        try:
            async with app.state.db_engine.begin() as conn:
                from gap.core.database.models import Base

                await conn.run_sync(Base.metadata.create_all)
            logger.info("所有通过 SQLAlchemy Base 定义的数据库表已成功初始化/验证。")
        except TimeoutError:
            logger.error("数据库表初始化超时，应用可能无法正常运行。", exc_info=True)
        except Exception as e:
            logger.error(
                f"数据库表初始化失败，应用可能无法正常运行: {e}", exc_info=True
            )
    else:
        logger.error("数据库引擎未初始化，无法创建表！应用可能无法正常运行。")

    # --- 执行启动时的 API Key 检查 ---
    logger.info("正在执行初始 API 密钥检查...")  # 记录日志
    testing_mode = os.environ.get("TESTING", "false").lower() == "true"
    if not testing_mode:
        # 仅在非测试环境下执行完整的 Key 检查流程，避免外部依赖导致测试不稳定
        async with (
            app.state.AsyncSessionFactory() as db_session_for_check
        ):  # 使用异步会话工厂获取会话
            try:
                await key_checker.check_keys(
                    key_manager, app.state.http_client, db_session_for_check
                )
            except Exception as check_keys_err:  # 捕获检查过程中的异常
                logger.error(
                    f"执行初始 API 密钥检查时发生错误: {check_keys_err}", exc_info=True
                )
    else:
        logger.info("TESTING 模式下跳过外部 API Key 健康检查，仅依赖内存配置。")

    # 记录 Key 检查结果摘要（测试模式下可能全部为 0）
    active_keys_count = key_manager.get_active_keys_count()
    logger.info(
        f"初始密钥检查摘要: 总配置数={getattr(key_checker, 'INITIAL_KEY_COUNT', 0)}, "
        f"有效数={active_keys_count}, 无效数={len(getattr(key_checker, 'INVALID_KEYS', []))}"
    )
    if active_keys_count > 0:
        logger.info(f"最大 API 调用重试次数设置为 (基于有效密钥): {active_keys_count}")
    else:
        logger.warning(f"{RED}没有有效的 API 密钥，服务可能无法正常运行！{RESET}")

    # --- 加载模型限制配置 ---
    config.MODEL_LIMITS = load_model_limits()
    logger.info(f"已加载模型限制配置: {list(config.MODEL_LIMITS.keys())}")

    # --- 预取可用模型列表 (可选) ---
    if active_keys_count > 0:  # 仅当有活动 Key 时尝试
        logger.info("尝试预获取可用模型列表...")  # 记录日志
        try:
            if key_manager.api_keys:  # 确保活动 Key 列表不为空
                key_to_use = key_manager.api_keys[0]  # 使用第一个活动 Key 进行请求
                # 调用 GeminiClient 的静态方法获取模型列表，设置超时
                all_models = await asyncio.wait_for(
                    GeminiClient.list_available_models(
                        key_to_use, app.state.http_client
                    ),
                    timeout=config.API_TIMEOUT_MODELS_LIST,  # 使用配置的超时
                )
                # 更新 GeminiClient 类变量中的可用模型列表 (移除 "models/" 前缀)
                GeminiClient.AVAILABLE_MODELS = [
                    model.replace("models/", "") for model in all_models
                ]
                logger.info(
                    f"成功预获取可用模型: {GeminiClient.AVAILABLE_MODELS}"
                )  # 记录成功日志
            else:  # 如果活动 Key 列表为空 (理论上不应发生)
                logger.warning("没有可用的有效密钥来预取模型列表。")
                GeminiClient.AVAILABLE_MODELS = []  # 设置为空列表
        except TimeoutError:  # 捕获超时错误
            logger.error(
                "启动时预获取模型列表超时 (超过 60 秒)。将在第一次 /v1/models 请求时再次尝试。"
            )
            GeminiClient.AVAILABLE_MODELS = []  # 设置为空列表
        except Exception as e:  # 捕获其他获取模型列表的错误
            logger.error(
                f"启动时预获取模型列表失败: {e}. 将在第一次 /v1/models 请求时再次尝试。",
                exc_info=True,
            )
            GeminiClient.AVAILABLE_MODELS = []  # 设置为空列表

    # --- 设置并启动后台任务调度器 ---
    testing_mode = os.environ.get("TESTING", "false").lower() == "true"
    if testing_mode:
        logger.info("TESTING 模式下跳过后台调度器和缓存清理调度器的启动。")
    else:
        logger.info("设置后台调度器...")  # 记录日志
        reporting_scheduler.setup_scheduler(
            key_manager, app.state.context_store_manager
        )

        # --- 启动缓存清理调度器 (如果需要) ---
        logger.info("尝试启动缓存清理调度器...")
        try:
            cache_cleanup_scheduler_instance = start_cache_cleanup_scheduler()
            app.state.cache_cleanup_scheduler = cache_cleanup_scheduler_instance
            logger.info("缓存清理调度器已成功设置并启动。")
        except Exception as e:
            logger.error(f"启动缓存清理调度器失败: {e}", exc_info=True)
    # logger.debug("缓存清理调度器启动逻辑已注释掉，因其依赖 aiosqlite 连接，可能与 AsyncSession 不兼容。") # 改为 debug 级别

    # --- 设置全局异常钩子 ---
    # 用于捕获在 FastAPI 请求处理流程之外的未处理异常
    logger.info("注册自定义 sys.excepthook...")  # 记录日志
    # 为 sys.excepthook 注册自定义异常处理器，并提供类型提示
    sys.excepthook = error_handlers.handle_exception  # 注册自定义异常处理器

    # （已提前在启动阶段初始化数据库表，此处逻辑已上移）

    logger.info("应用程序启动完成。")  # 记录启动完成日志

    # --- 启动锁管理器清理任务 ---
    await lock_manager.start_cleanup_task()
    logger.info("锁管理器清理任务已启动")

    # --- 启动后台调度器 ---
    if not testing_mode:
        logger.info("启动后台调度器...")
        reporting_scheduler.start_scheduler()

    # --- 应用运行阶段 ---
    yield  # lifespan 函数在此暂停，FastAPI 应用开始处理请求

    # === 应用关闭逻辑 ===
    logger.info("正在关闭应用程序...")  # 记录关闭开始日志

    # 使用统一资源管理器进行清理
    logger.info("启动统一资源清理...")

    # 停止锁管理器清理任务
    try:
        await lock_manager.stop_cleanup_task()
        logger.debug("已停止锁管理器清理任务")
    except Exception as e:
        logger.error(f"停止锁管理器清理任务失败: {e}")

    await resource_manager.cleanup_all_resources()

    logger.info("应用程序关闭完成。")  # 记录关闭完成日志


# --- 创建 FastAPI 应用实例 ---
# 从环境变量读取 ROOT_PATH，如果 HF Space 设置了 X-Forwarded-Prefix，Uvicorn 通常会处理
# 但显式设置 root_path 可以提供更大的灵活性
# 从环境变量读取 ROOT_PATH，并确保其以 "/" 开头 (如果存在)
_app_root_path = os.environ.get("ROOT_PATH", "")
if _app_root_path and not _app_root_path.startswith("/"):
    _app_root_path = "/" + _app_root_path  # 确保 root_path 以 / 开头

app = FastAPI(
    title="Gemini API 代理 (重构版)",  # 应用标题
    version=__version__,  # 应用版本号
    description="一个重构后的 FastAPI 代理，用于 Google Gemini API，具有密钥轮换、使用情况跟踪和优化功能。",  # 应用描述
    lifespan=lifespan,  # 注册生命周期事件处理器
    proxy_headers=True,  # 信任代理头部，如 X-Forwarded-For 和 X-Forwarded-Proto
    root_path=_app_root_path,  # 使用处理后的 root_path
    docs_url="/docs" if config.ENABLE_DOCS else None,
    redoc_url=None,
    openapi_url="/openapi.json" if config.ENABLE_DOCS else None,
)

# 临时的根路由，用于诊断 NoMatchFound 问题


# --- 添加中间件以设置 Permissions-Policy ---
@app.middleware("http")
async def add_permissions_policy_header(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
):
    response: Response = await call_next(request)
    # 定义一个全面的 Permissions-Policy 来禁用不必要的特性
    # 参考: https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Permissions-Policy
    # 以及 Hugging Face Spaces 可能禁用的特性
    # policy = (
    #     "ambient-light-sensor=(), "
    #     "battery=()"
    # )
    # policy = "geolocation=()" # 极度精简的策略 - 移除未使用的变量
    # response.headers["Permissions-Policy"] = policy # 暂时注释掉以进行诊断
    logger.debug(
        f"为路径 {request.url.path} 暂时移除了 Permissions-Policy 头部 (诊断模式)。"
    )
    return response


logger.info("已添加 Permissions-Policy 中间件。")


# --- 注册全局异常处理器 ---
# 捕获所有未处理的异常，并返回标准化的 JSON 错误响应
# 首先为更具体的 HTTPException 注册，然后为通用的 Exception 注册，确保 HTTPException 被优先处理
app.add_exception_handler(HTTPException, error_handlers.global_exception_handler)
logger.info("已为 HTTPException 注册全局异常处理器。")
app.add_exception_handler(Exception, error_handlers.global_exception_handler)
logger.info("已为通用 Exception 注册全局异常处理器。")  # 记录日志

# --- 包含 API 和 Web UI 路由器 ---
# API 路由
app.include_router(
    api_endpoints.router, tags=["OpenAI Compatible API v1"]
)  # 包含 OpenAI 兼容 API (v1)
logger.info("已包含 OpenAI Compatible API (v1) 端点路由器。")
app.include_router(
    v2_endpoints.v2_router, prefix="/v2", tags=["Gemini Native API v2"]
)  # 包含 Gemini 原生 API (v2)
logger.info("已包含 Gemini 原生 API 端点路由器 (/v2)。")
app.include_router(cache_endpoints.router, prefix="/api")  # 包含缓存管理 API
logger.info("已包含缓存管理 API 路由器 (/api)。")
app.include_router(context_endpoints.router, prefix="/api")  # 包含上下文管理 API
logger.info("已包含上下文管理 API 路由器 (/api)。")

# 包含配置管理 / 验证 / 资源管理 API
app.include_router(config_endpoints.router)
logger.info("已包含配置管理 API 路由器 (/api/v1/config)。")
app.include_router(
    config_validation.router, prefix="/api/v1/config", tags=["Configuration Validation"]
)
logger.info("已包含配置验证 API 路由器 (/api/v1/config)。")
app.include_router(
    resource_endpoints.router, prefix="/api/v1/resources", tags=["Resource Management"]
)
logger.info("已包含资源管理 API 路由器 (/api/v1/resources)。")


# --- 登录路由 ---
# 处理 GET 请求返回登录页（SPA 入口），统一交给前端路由处理
@app.get("/login", include_in_schema=False)
async def serve_login_page():
    # Vite 构建产物中只有 index.html，前端使用 SPA 路由切换到 LoginView
    return FileResponse("/app/frontend/dist/index.html")


class LoginRequest(BaseModel):
    """前端 SPA 使用的登录请求体，仅包含 password 字段作为 API Key。"""

    password: str


def _validate_api_key_and_issue_token(api_key: str, key_manager: APIKeyManager) -> str:
    """复用的内部函数：验证 API Key 并签发访问 token。"""

    api_key = api_key.strip()
    if not api_key:
        logger.warning("登录失败: 未提供 API Key")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="请输入有效的API密钥",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 验证 API Key 是否有效 (包括管理员密钥)
    is_valid = key_manager.is_key_valid(api_key) or key_manager.is_admin_key(api_key)
    if not is_valid:
        logger.warning(f"登录失败: 无效的 API Key '{api_key[:8]}...'")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的 API Key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": api_key, "admin": key_manager.is_admin_key(api_key)},
        expires_delta=access_token_expires,
    )
    logger.info(f"API Key '{api_key[:8]}...' 登录成功，已颁发访问令牌。")
    return access_token


# 处理POST请求进行认证（传统表单登录）
@app.post("/login", status_code=204)
async def login_for_access_token(
    password: str = Form(...),
    key_manager: APIKeyManager = Depends(lambda: app.state.key_manager),
):
    """处理表单登录并通过响应头返回访问令牌 (向后兼容)。"""
    access_token = _validate_api_key_and_issue_token(password, key_manager)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.headers["X-Access-Token"] = access_token
    return response


# 为 SPA 提供 JSON 风格的登录接口
@app.post("/api/auth/login")
async def api_login_for_access_token(
    payload: LoginRequest,
    key_manager: APIKeyManager = Depends(lambda: app.state.key_manager),
):
    """JSON API: 验证 API Key 并返回 { success, data: { token } } 结构。"""
    access_token = _validate_api_key_and_issue_token(payload.password, key_manager)
    return {
        "success": True,
        "data": {"token": access_token},
        "message": "登录成功",
    }


# --- 添加健康检查端点 ---
@app.get("/healthz", status_code=status.HTTP_200_OK)
async def health_check():
    """Kubernetes健康检查端点 - 基础检查"""
    # 使用 timezone-aware 的 UTC 时间，避免 datetime.utcnow() 弃用警告
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/health", status_code=status.HTTP_200_OK, tags=["Health"])
async def detailed_health_check():
    """详细健康检查端点"""
    from gap.core.health.monitor import get_system_health

    try:
        health_data = await get_system_health(app, check_depth="standard")

        # 根据健康状态设置HTTP状态码
        status_mapping = {
            "healthy": status.HTTP_200_OK,
            "warning": status.HTTP_200_OK,
            "error": status.HTTP_503_SERVICE_UNAVAILABLE,
            "critical": status.HTTP_503_SERVICE_UNAVAILABLE,
            "unknown": status.HTTP_503_SERVICE_UNAVAILABLE,
        }

        http_status = status_mapping.get(health_data["status"], status.HTTP_200_OK)

        return JSONResponse(content=health_data, status_code=http_status)
    except Exception as e:
        logger.error(f"健康检查失败: {e}", exc_info=True)
        return JSONResponse(
            content={
                "status": "error",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error": str(e),
                "checks": {},
            },
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


@app.get("/health/basic", status_code=status.HTTP_200_OK, tags=["Health"])
async def basic_health_check():
    """基础健康检查（仅检查核心功能）"""
    from gap.core.health.monitor import get_system_health

    try:
        health_data = await get_system_health(app, check_depth="basic")

        # 基础检查总是返回200，状态在响应体中体现
        return JSONResponse(content=health_data)
    except Exception as e:
        logger.error(f"基础健康检查失败: {e}", exc_info=True)
        return JSONResponse(
            content={
                "status": "error",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error": str(e),
                "checks": {},
            },
            status_code=status.HTTP_200_OK,  # 基础检查不返回错误状态码
        )


# --- 挂载 Vue SPA 静态文件 ---
# 仅在生产环境或构建目录存在时挂载前端静态文件
frontend_dist_dir = (
    "/app/frontend/dist" if os.path.exists("/app/frontend/dist") else None
)

# 开发环境不挂载前端，让前端开发服务器单独运行
if frontend_dist_dir and os.path.exists(frontend_dist_dir):
    app.mount("/", StaticFiles(directory=frontend_dist_dir, html=True), name="frontend")
    logger.info(f"已挂载 Vue SPA 静态文件目录 ({frontend_dist_dir}) 到根路径 /。")
else:
    logger.info("未检测到前端构建文件，跳过静态文件挂载（开发模式）")
# --- 打印所有已注册的路由 ---
print("=" * 20 + " Registered Routes " + "=" * 20)

for route in app.routes:
    # 尝试获取路由路径
    path = getattr(route, "path", "N/A")
    # 尝试获取路由名称
    name = getattr(route, "name", "N/A")

    # 对于挂载的 ASGI 应用 (如 StaticFiles)，其 route 对象是 Mount 类型
    # 对于挂载的 ASGI 应用 (如 StaticFiles)，其 route 对象是 Mount 类型
    # StaticFiles 实例本身没有 name 属性，但 Mount 对象有
    if isinstance(route, Mount):
        # 检查 Mount 对象是否有 name 属性，并使用它
        if hasattr(route, "name") and route.name:
            name = f"Mounted: {route.name}"
        else:
            name = "Mounted App (No Name)"  # 如果没有 name 属性，提供一个默认值

    print(f"Path: {path}, Name: {name}")
print("=" * 50)
# --- 路由打印结束 ---

# --- Uvicorn 启动入口 ---
# 当直接运行此文件时 (python app/main.py)，执行以下代码
if __name__ == "__main__":
    # 从环境变量获取端口、主机、重载标志和日志级别
    port = int(os.environ.get("PORT", 7860))  # 默认端口 7860
    host = os.environ.get("HOST", "0.0.0.0")  # 默认监听所有接口
    reload_flag = (
        os.environ.get("UVICORN_RELOAD", "true").lower() == "true"
    )  # 默认启用自动重载
    log_level = os.environ.get("UVICORN_LOG_LEVEL", "info").lower()  # 默认日志级别 info

    # 记录 Uvicorn 启动信息
    logger.info(
        f"在 {host}:{port} 上启动 Uvicorn 服务器 (自动重载: {reload_flag}, 日志级别: {log_level})"
    )
    # 使用 uvicorn.run 启动 ASGI 服务器
    uvicorn.run(
        "app.main:app",  # 指向 FastAPI 应用实例 (app.main 文件中的 app 对象)
        host=host,  # 监听地址
        port=port,  # 监听端口
        reload=reload_flag,  # 是否启用自动重载
        log_level=log_level,  # 设置 Uvicorn 的日志级别
    )
