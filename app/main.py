# -*- coding: utf-8 -*-
"""
FastAPI 应用主入口文件。
负责初始化应用、配置、加载资源、设置路由和启动服务器。
"""
# --- 标准库导入 ---
import sys # 系统相关功能
import os # 操作系统接口
import logging # 日志记录
import json # JSON 处理
import asyncio # 异步 IO
import uvicorn # ASGI 服务器
from contextlib import asynccontextmanager # 异步上下文管理器
from typing import AsyncGenerator # 异步生成器类型提示
from asyncio import TimeoutError # 异步超时错误
from fastapi.staticfiles import StaticFiles # 静态文件服务
from fastapi.responses import FileResponse # 导入 FileResponse

# --- 第三方库导入 ---
from fastapi import FastAPI # FastAPI 框架核心类
from dotenv import load_dotenv # 加载 .env 文件
import aiosqlite # 异步 SQLite 驱动
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession # SQLAlchemy 异步引擎和会话
from sqlalchemy.orm import sessionmaker # SQLAlchemy 会话工厂
import httpx # 异步 HTTP 客户端

# --- 应用内部模块导入 ---
# 首先导入配置模块，确保配置在其他模块导入前加载
from app import config
# 导入 API 端点路由
from app.api import endpoints as api_endpoints # OpenAI 兼容 API (v1)
from app.api import cache_endpoints # 缓存管理 API
from app.api import v2_endpoints # Gemini 原生 API (v2)
# 导入 Web UI 路由
from app.web import routes as web_routes
# 导入错误处理程序
from app.handlers import error_handlers
# 导入 Key 管理相关模块
from app.core.keys import checker as key_checker # Key 检查器 (重命名以区分)
from app.core.keys.manager import APIKeyManager # Key 管理器类
# 导入报告和调度相关模块
from app.core.reporting import scheduler as reporting_scheduler # 报告调度器 (重命名以区分)
# 导入日志配置函数
from app.handlers.log_config import setup_logger
# 从配置模块导入特定变量和函数
from app.config import __version__, SECRET_KEY, load_model_limits
# 导入核心服务和工具类
from app.core.services.gemini import GeminiClient # Gemini API 客户端
from app.core.context.store import ContextStore # 直接导入 ContextStore 类
from app.core.database import utils as db_utils # 数据库工具函数
from app.core.dependencies import get_key_manager, get_http_client, get_db_session # FastAPI 依赖项
from app.core.cache.manager import CacheManager # 缓存管理器
from app.core.cache.cleanup import start_cache_cleanup_scheduler # 缓存清理调度器启动函数

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
    logger.info(f"启动 Gemini API 代理 v{__version__}...") # 记录应用启动日志和版本号

    # --- 初始化共享资源实例 ---
    key_manager = APIKeyManager() # 创建 Key 管理器实例
    http_client = httpx.AsyncClient() # 创建共享的异步 HTTP 客户端实例
    cache_manager = CacheManager() # 创建缓存管理器实例
    context_store_manager = ContextStore() # 创建上下文存储管理器实例

    # --- 将共享资源存储在应用状态 (app.state) 中 ---
    # 这样可以通过 FastAPI 的依赖注入系统在请求处理函数中访问这些实例
    app.state.key_manager = key_manager
    app.state.http_client = http_client
    app.state.cache_manager = cache_manager
    app.state.context_store_manager = context_store_manager # 存储上下文管理器实例

    # --- 初始化数据库引擎和异步会话工厂 ---
    # 创建 SQLAlchemy 异步引擎
    db_engine = create_async_engine(db_utils.DATABASE_URL, echo=False) # echo=False 关闭 SQL 执行日志
    # 创建异步会话工厂
    AsyncSessionFactory = sessionmaker(
        bind=db_engine, # 绑定引擎
        class_=AsyncSession, # 指定使用异步会话
        expire_on_commit=False # 防止在提交后 ORM 对象过期
    )
    # 将引擎和会话工厂存储在应用状态中
    app.state.db_engine = db_engine # 用于关闭时 dispose 引擎
    app.state.AsyncSessionFactory = AsyncSessionFactory # 用于 get_db_session 依赖项创建会话
    logger.info("数据库引擎和会话工厂已初始化。") # 记录日志

    # --- 记录关键配置信息 (注意避免记录敏感信息) ---
    RED = '\033[91m' # 定义红色 ANSI 转义码
    RESET = '\033[0m' # 定义重置颜色的 ANSI 转义码
    if not config.ADMIN_API_KEY: # 检查管理员 Key 是否已设置
        # 如果未设置，打印多行警告信息
        logger.warning(f"{RED}****************************************************************{RESET}")
        logger.warning(f"{RED}警告: 管理员 API Key (ADMIN_API_KEY) 未设置！{RESET}")
        logger.warning(f"{RED}部分管理功能（如代理 Key 管理）将不可用。{RESET}")
        logger.warning(f"{RED}强烈建议在环境变量中配置 ADMIN_API_KEY 以启用全部功能。{RESET}")
        logger.warning(f"{RED}****************************************************************{RESET}")
    else: # 如果已设置
        logger.info("管理员 API Key (ADMIN_API_KEY) 已配置。")

    # 记录其他配置信息
    logger.info(f"Web UI 密码保护已启用: {'是' if config.WEB_UI_PASSWORDS else '否'}") # 使用 WEB_UI_PASSWORDS 判断
    logger.info(f"本地 IP 速率限制 (可能已废弃): 每分钟最大请求数={config.MAX_REQUESTS_PER_MINUTE}, 每 IP 每日最大请求数={config.MAX_REQUESTS_PER_DAY_PER_IP}")
    logger.info(f"全局禁用 Gemini 安全过滤: {config.DISABLE_SAFETY_FILTERING}")
    if config.DISABLE_SAFETY_FILTERING:
        logger.info("注意：全局安全过滤已禁用，所有请求将不包含安全设置。")
    # 检查报告间隔配置是否有效
    if config.USAGE_REPORT_INTERVAL_MINUTES == 30: # 如果是默认值
        interval_env = os.environ.get("USAGE_REPORT_INTERVAL_MINUTES") # 检查环境变量是否设置
        if interval_env: # 如果设置了
             try:
                  if int(interval_env) <= 0: # 检查是否为无效值
                      logger.warning("环境变量 USAGE_REPORT_INTERVAL_MINUTES 必须为正整数，当前设置无效，将使用默认值 30 分钟。")
             except ValueError: # 检查是否无法转换为整数
                  logger.warning(f"无法将环境变量 USAGE_REPORT_INTERVAL_MINUTES ('{interval_env}') 解析为整数，将使用默认值 30 分钟。")
    # 检查报告日志级别配置是否有效
    report_level_env = os.environ.get("REPORT_LOG_LEVEL", "INFO").upper()
    if config.REPORT_LOG_LEVEL_INT == logging.INFO and report_level_env != "INFO": # 如果最终级别是 INFO 但环境变量不是 INFO
         logger.warning(f"无效的环境变量 REPORT_LOG_LEVEL 值 '{os.environ.get('REPORT_LOG_LEVEL')}'. 将使用默认日志级别 INFO。")
    else:
         logger.info(f"使用情况报告日志级别设置为: {config.REPORT_LOG_LEVEL_STR}")

    # --- 执行启动时的 API Key 检查 ---
    logger.info("正在执行初始 API 密钥检查...") # 记录日志
    # 创建一个临时的数据库会话用于 Key 检查
    async with AsyncSessionFactory() as db_session_for_check:
        try:
            # 调用 Key 检查器函数，传入 Key 管理器、HTTP 客户端和数据库会话
            await key_checker.check_keys(key_manager, app.state.http_client, db_session_for_check)
        except Exception as check_keys_err: # 捕获检查过程中的异常
            logger.error(f"执行初始 API 密钥检查时发生错误: {check_keys_err}", exc_info=True) # 记录错误
        # finally 块确保会话关闭，即使上面没有 yield (async with 会处理)

    # 记录 Key 检查结果摘要
    active_keys_count = key_manager.get_active_keys_count() # 获取活动 Key 数量
    logger.info(f"初始密钥检查摘要: 总配置数={key_checker.INITIAL_KEY_COUNT}, 有效数={active_keys_count}, 无效数={len(key_checker.INVALID_KEYS)}")
    if active_keys_count > 0: # 如果有活动 Key
        logger.info(f"最大 API 调用重试次数设置为 (基于有效密钥): {active_keys_count}") # 记录最大重试次数
    else: # 如果没有活动 Key
        logger.error(f"{RED}没有有效的 API 密钥，服务可能无法正常运行！{RESET}") # 记录严重错误

    # --- 加载模型限制配置 ---
    load_model_limits() # 调用 config 模块中的函数加载 JSON 文件
    logger.info(f"已加载模型限制配置: {list(config.MODEL_LIMITS.keys())}") # 记录加载的模型名称

    # --- 预取可用模型列表 (可选) ---
    if active_keys_count > 0: # 仅当有活动 Key 时尝试
         logger.info("尝试预获取可用模型列表...") # 记录日志
         try:
             if key_manager.api_keys: # 确保活动 Key 列表不为空
                 key_to_use = key_manager.api_keys[0] # 使用第一个活动 Key 进行请求
                 # 调用 GeminiClient 的静态方法获取模型列表，设置超时
                 all_models = await asyncio.wait_for(
                     GeminiClient.list_available_models(key_to_use, app.state.http_client),
                     timeout=60.0 # 设置 60 秒超时
                 )
                 # 更新 GeminiClient 类变量中的可用模型列表 (移除 "models/" 前缀)
                 GeminiClient.AVAILABLE_MODELS = [model.replace("models/", "") for model in all_models]
                 logger.info(f"成功预获取可用模型: {GeminiClient.AVAILABLE_MODELS}") # 记录成功日志
             else: # 如果活动 Key 列表为空 (理论上不应发生)
                 logger.warning("没有可用的有效密钥来预取模型列表。")
                 GeminiClient.AVAILABLE_MODELS = [] # 设置为空列表
         except TimeoutError: # 捕获超时错误
             logger.error("启动时预获取模型列表超时 (超过 60 秒)。将在第一次 /v1/models 请求时再次尝试。")
             GeminiClient.AVAILABLE_MODELS = [] # 设置为空列表
         except Exception as e: # 捕获其他获取模型列表的错误
             logger.error(f"启动时预获取模型列表失败: {e}. 将在第一次 /v1/models 请求时再次尝试。", exc_info=True)
             GeminiClient.AVAILABLE_MODELS = [] # 设置为空列表

    # --- 设置并启动后台任务调度器 ---
    logger.info("设置后台调度器...") # 记录日志
    reporting_scheduler.setup_scheduler(key_manager, app.state.context_store_manager) # 传入 Key 管理器和上下文存储管理器实例

    # --- 启动缓存清理调度器 (如果需要) ---
    # 注意：缓存清理任务目前依赖 aiosqlite 连接，而 get_db_session 返回 AsyncSession
    # 这里可能需要调整或确认兼容性
    # logger.info("启动缓存清理调度器...")
    # try:
    #     async with db_utils.get_db_connection() as conn: # 获取 aiosqlite 连接
    #         cache_scheduler = start_cache_cleanup_scheduler(conn) # 启动调度器
    #     app.state.cache_scheduler = cache_scheduler # 存储调度器实例
    # except Exception as e:
    #     logger.error(f"启动缓存清理调度器失败: {e}", exc_info=True)
    logger.debug("缓存清理调度器启动逻辑已注释掉，因其依赖 aiosqlite 连接，可能与 AsyncSession 不兼容。") # 改为 debug 级别

    # --- 设置全局异常钩子 ---
    # 用于捕获在 FastAPI 请求处理流程之外的未处理异常
    logger.info("注册自定义 sys.excepthook...") # 记录日志
    sys.excepthook = error_handlers.handle_exception

    # --- 初始化数据库表 ---
    logger.info("正在初始化数据库表...")
    if app.state.db_engine: # 确保引擎已创建
        try:
            async with app.state.db_engine.begin() as conn:
                # 导入 Base，因为此文件可能没有直接导入它
                from app.core.database.models import Base
                await conn.run_sync(Base.metadata.create_all)
            logger.info("所有通过 SQLAlchemy Base 定义的数据库表已成功初始化/验证。")
        except TimeoutError: # 捕获超时错误 (虽然 run_sync 不太可能直接超时，但保留以防万一)
            logger.error("数据库表初始化超时，应用可能无法正常运行。", exc_info=True)
        except Exception as e: # 捕获其他初始化错误
            logger.error(f"数据库表初始化失败，应用可能无法正常运行: {e}", exc_info=True)
            # 考虑在这里重新抛出异常以阻止应用继续，如果表创建是关键的
            # raise
    else:
        logger.error("数据库引擎未初始化，无法创建表！应用可能无法正常运行。")

    logger.info("应用程序启动完成。") # 记录启动完成日志

    # --- 启动后台调度器 ---
    logger.info("启动后台调度器...") # 记录日志
    reporting_scheduler.start_scheduler()

    # --- 应用运行阶段 ---
    yield # lifespan 函数在此暂停，FastAPI 应用开始处理请求

    # === 应用关闭逻辑 ===
    logger.info("正在关闭应用程序...") # 记录关闭开始日志
    # 关闭报告调度器
    reporting_scheduler.shutdown_scheduler()
    # 关闭缓存清理调度器 (如果已启动)
    if hasattr(app.state, 'cache_scheduler') and app.state.cache_scheduler and app.state.cache_scheduler.running:
        logger.info("正在关闭缓存清理调度器...")
        app.state.cache_scheduler.shutdown()
    # 关闭共享的 HTTP 客户端
    if hasattr(app.state, 'http_client') and app.state.http_client:
        logger.info("正在关闭 HTTP 客户端...")
        await app.state.http_client.aclose()
    # 关闭数据库引擎
    if hasattr(app.state, 'db_engine') and app.state.db_engine:
        logger.info("正在关闭数据库引擎...")
        await app.state.db_engine.dispose()
    logger.info("应用程序关闭完成。") # 记录关闭完成日志

# --- 创建 FastAPI 应用实例 ---
app = FastAPI(
    title="Gemini API 代理 (重构版)", # 应用标题
    version=__version__, # 应用版本号
    description="一个重构后的 FastAPI 代理，用于 Google Gemini API，具有密钥轮换、使用情况跟踪和优化功能。", # 应用描述
    lifespan=lifespan, # 注册生命周期事件处理器
    # 可以添加其他 FastAPI 应用级别的配置，例如自定义文档 URL 等
)

# --- 注册全局异常处理器 ---
# 捕获所有未处理的异常，并返回标准化的 JSON 错误响应
app.add_exception_handler(Exception, error_handlers.global_exception_handler)
logger.info("已注册全局异常处理器。") # 记录日志

# --- 包含 API 和 Web UI 路由器 ---
# API 路由
app.include_router(api_endpoints.router, tags=["OpenAI Compatible API v1"]) # 包含 OpenAI 兼容 API (v1)
logger.info("已包含 OpenAI Compatible API (v1) 端点路由器。")
app.include_router(v2_endpoints.v2_router, prefix="/v2", tags=["Gemini Native API v2"]) # 包含 Gemini 原生 API (v2)
logger.info("已包含 Gemini 原生 API 端点路由器 (/v2)。")
app.include_router(cache_endpoints.router, prefix="/api") # 包含缓存管理 API
logger.info("已包含缓存管理 API 路由器 (/api)。")

# Web UI 路由
app.include_router(web_routes.router) # 包含 Web UI 页面路由
logger.info("已包含 Web UI 路由器。")

# --- 挂载静态文件目录 ---
# 将 'assets' 目录下的静态文件（如 CSS, JS, 图片）映射到 '/assets' URL 路径
app.mount("/assets", StaticFiles(directory="assets"), name="assets")
logger.info("已挂载静态文件目录 /assets。")

# --- 单独处理 favicon.ico ---
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """
    提供 favicon.ico 文件。
    """
    return FileResponse("assets/favicon.ico")

# --- Uvicorn 启动入口 ---
# 当直接运行此文件时 (python app/main.py)，执行以下代码
if __name__ == "__main__":
    # 从环境变量获取端口、主机、重载标志和日志级别
    port = int(os.environ.get("PORT", 7860)) # 默认端口 7860
    host = os.environ.get("HOST", "0.0.0.0") # 默认监听所有接口
    reload_flag = os.environ.get("UVICORN_RELOAD", "true").lower() == "true" # 默认启用自动重载
    log_level = os.environ.get("UVICORN_LOG_LEVEL", "info").lower() # 默认日志级别 info

    # 记录 Uvicorn 启动信息
    logger.info(f"在 {host}:{port} 上启动 Uvicorn 服务器 (自动重载: {reload_flag}, 日志级别: {log_level})")
    # 使用 uvicorn.run 启动 ASGI 服务器
    uvicorn.run(
        "app.main:app", # 指向 FastAPI 应用实例 (app.main 文件中的 app 对象)
        host=host, # 监听地址
        port=port, # 监听端口
        reload=reload_flag, # 是否启用自动重载
        log_level=log_level # 设置 Uvicorn 的日志级别
    )
