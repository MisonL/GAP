# --- 导入 ---
# --- Imports ---
import sys # 导入 sys 模块 (Import sys module)
import os # 导入 os 模块 (Import os module)
import logging # 导入 logging 模块 (Import logging module)
import json # 导入 json 模块 (Import json module)
import asyncio # 导入 asyncio 模块 (Import asyncio module)
import uvicorn # 导入 uvicorn 模块 (Import uvicorn module)
from fastapi import FastAPI # 导入 FastAPI 类 (Import FastAPI class)
from dotenv import load_dotenv # 用于加载 .env 文件中的环境变量 (Used for loading environment variables from .env file)

# 加载 .env 文件 (如果存在)
# Load .env file (if it exists)
load_dotenv()

# --- 导入 ---
# --- Imports ---
import sys # 导入 sys 模块 (Import sys module)
import os # 导入 os 模块 (Import os module)
import logging # 导入 logging 模块 (Import logging module)
import json # 导入 json 模块 (Import json module)
import asyncio # 导入 asyncio 模块 (Import asyncio module)
import uvicorn # 导入 uvicorn 模块 (Import uvicorn module)
from fastapi import FastAPI # 导入 FastAPI 类 (Import FastAPI class)
from contextlib import asynccontextmanager # 用于定义异步上下文管理器 (lifespan) (Used for defining asynchronous context managers (lifespan))
from typing import AsyncGenerator # 类型提示，用于异步生成器 (Type hint, used for asynchronous generators)
from fastapi import Request # 导入 FastAPI Request 对象，用于处理请求上下文 (Import FastAPI Request object, used for handling request context)
from fastapi.responses import JSONResponse # 导入 FastAPI JSONResponse 对象，用于返回 JSON 格式的响应 (Import FastAPI JSONResponse object, used for returning JSON formatted responses)

# 本地模块
# Local modules
from app import config # 首先导入配置模块 (Import config module first)
from app.api import endpoints as api_endpoints # 重命名以区分 (Rename for distinction) # 导入 API 端点路由 (Import API endpoint routes)
from app.web import routes as web_routes # 新增：导入 Web UI 路由 (New: Import Web UI routes)
from app.handlers import error_handlers # 导入错误处理器模块 (Import error handlers module)
from app.core import key_management # 从 core 子模块导入密钥管理 (Import key management from core submodule)
from app.core import reporting # 从 core 子模块导入报告 (Import reporting from core submodule)
from app.handlers.log_config import setup_logger # 从 handlers 子模块导入日志设置 (Import log setup from handlers submodule)
from app.core.utils import key_manager_instance # 从 core.utils 导入共享实例 (Import shared instance from core.utils)
from app.config import __version__, SECRET_KEY, load_model_limits # 导入版本号, SECRET_KEY 和加载函数 (Import version, SECRET_KEY, and load function)
from app.core.gemini import GeminiClient # 导入 GeminiClient 类 (Import GeminiClient class)
from app.core import context_store # 新增：导入上下文存储模块 (New: Import context store module)
from app.core import db_utils # 导入数据库工具模块，用于初始化 (Import database utility module, used for initialization)

# --- 初始化 ---
# --- Initialization ---
# 如果需要，可以禁用 uvicorn 的默认日志记录器，以完全使用自定义日志
# If needed, can disable uvicorn's default logger to fully use custom logging
# 如果需要，可以禁用 uvicorn 的默认日志记录器，以完全使用自定义日志
# If needed, can disable uvicorn's default logger to fully use custom logging
# logging.getLogger("uvicorn").propagate = False
# logging.getLogger("uvicorn.error").propagate = False
# logging.getLogger("uvicorn.access").propagate = False
logger = setup_logger() # 初始化并获取自定义的日志记录器实例 (Initialize and get custom logger instance)

# --- 全局实例（集中式）---
# --- Global Instances (Centralized) ---
# 在此处实例化 APIKeyManager 以便在需要它的模块之间共享（当前在 core.utils 中实例化并导入）
# Instantiate APIKeyManager here to share it among modules that need it (currently instantiated and imported in core.utils)
# 其他模块可以根据需要导入此实例（例如，from app.core.utils import key_manager_instance）
# Other modules can import this instance as needed (e.g., from app.core.utils import key_manager_instance)
# 或者，更好的方式是使用 FastAPI 的依赖注入将实例传递给需要的路由函数。
# Or, a better way is to use FastAPI's dependency injection to pass the instance to the required route functions.
# key_manager_instance 在 app.core.utils 中创建并导入
# key_manager_instance is created and imported in app.core.utils

# --- Lifespan 事件处理器 ---
# --- Lifespan Event Handler ---
@asynccontextmanager # 异步上下文管理器装饰器 (Asynchronous context manager decorator)
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    应用程序启动和关闭事件处理器。
    Application startup and shutdown event handler.
    """
    # --- 启动逻辑 ---
    # --- Startup Logic ---
    logger.info(f"启动 Gemini API 代理 v{__version__}...") # 记录应用启动信息 (Log application startup info)

    # 记录部分关键配置值（可选，注意不要记录敏感信息如 SECRET_KEY）
    # Log some key configuration values (optional, be careful not to log sensitive information like SECRET_KEY)
    # SECRET_KEY 的检查已移除，JWT 认证会在需要时检查其是否存在
    # SECRET_KEY check is removed, JWT authentication will check for its existence when needed
    # 定义 ANSI 红色代码
    # Define ANSI red code
    RED = '\033[91m' # 红色 ANSI 代码 (Red ANSI code)
    RESET = '\033[0m' # 重置 ANSI 代码 (Reset ANSI code)
    if not config.ADMIN_API_KEY: # 如果管理员 Key 未设置 (If admin key is not set)
        logger.warning(f"{RED}****************************************************************{RESET}") # 记录警告分隔线 (Log warning separator)
        logger.warning(f"{RED}警告: 管理员 API Key (ADMIN_API_KEY) 未设置！{RESET}") # 记录管理员 Key 未设置警告 (Log admin key not set warning)
        logger.warning(f"{RED}部分管理功能（如代理 Key 管理）将不可用。{RESET}") # 记录功能不可用信息 (Log feature unavailable info)
        logger.warning(f"{RED}强烈建议在环境变量中配置 ADMIN_API_KEY 以启用全部功能。{RESET}") # 记录配置建议 (Log configuration suggestion)
        logger.warning(f"{RED}****************************************************************{RESET}") # 记录警告分隔线 (Log warning separator)
    else:
        logger.info("管理员 API Key (ADMIN_API_KEY) 已配置。") # 记录管理员 Key 已配置信息 (Log admin key configured info)

    logger.info(f"Web UI 密码保护已启用: {'是' if config.PASSWORD else '否'}") # 记录 Web UI 密码保护状态 (Log Web UI password protection status)
    logger.info(f"本地 IP 速率限制: 每分钟最大请求数={config.MAX_REQUESTS_PER_MINUTE}, 每 IP 每日最大请求数={config.MAX_REQUESTS_PER_DAY_PER_IP}") # 记录本地 IP 速率限制配置 (Log local IP rate limit configuration)
    logger.info(f"全局禁用 Gemini 安全过滤: {config.DISABLE_SAFETY_FILTERING}") # 记录全局禁用安全过滤状态 (Log global disable safety filtering status)
    if config.DISABLE_SAFETY_FILTERING: # 如果全局禁用安全过滤 (If global disable safety filtering)
        logger.info("注意：全局安全过滤已禁用，所有请求将不包含安全设置。") # 记录安全过滤禁用注意信息 (Log safety filtering disabled note)
    # 检查报告配置是否使用了默认值，如果是由于无效的环境变量导致的，则记录警告
    # Check if reporting configuration uses default values, log warning if due to invalid environment variables
    if config.USAGE_REPORT_INTERVAL_MINUTES == 30: # 检查是否为默认报告间隔 (Check if it's the default report interval)
        interval_env = os.environ.get("USAGE_REPORT_INTERVAL_MINUTES") # 获取环境变量值 (Get environment variable value)
        if interval_env: # 如果用户设置了环境变量 (If user set environment variable)
             try:
                 if int(interval_env) <= 0: # 检查设置的值是否无效 (小于等于 0) (Check if the set value is invalid (less than or equal to 0))
                     logger.warning("环境变量 USAGE_REPORT_INTERVAL_MINUTES 必须为正整数，当前设置无效，将使用默认值 30 分钟。") # 记录警告 (Log warning)
             except ValueError: # 检查设置的值是否无法转换为整数 (Check if the set value cannot be converted to integer)
                 logger.warning(f"无法将环境变量 USAGE_REPORT_INTERVAL_MINUTES ('{interval_env}') 解析为整数，将使用默认值 30 分钟。") # 记录警告 (Log warning)
    # 检查报告日志级别是否使用了默认值 INFO，如果是由于无效的环境变量导致的，则记录警告
    # Check if report log level uses default INFO, log warning if due to invalid environment variables
    report_level_env = os.environ.get("REPORT_LOG_LEVEL", "INFO").upper() # 获取报告日志级别环境变量 (Get report log level environment variable)
    if config.REPORT_LOG_LEVEL_INT == logging.INFO and report_level_env != "INFO": # 如果日志级别是 INFO 且环境变量不是 INFO (If log level is INFO and environment variable is not INFO)
         logger.warning(f"无效的环境变量 REPORT_LOG_LEVEL 值 '{os.environ.get('REPORT_LOG_LEVEL')}'. 将使用默认日志级别 INFO。") # 记录警告 (Log warning)
    else:
         logger.info(f"使用情况报告日志级别设置为: {config.REPORT_LOG_LEVEL_STR}") # 记录报告日志级别设置 (Log report log level setting)

    # 使用共享实例执行初始 API 密钥检查
    # Perform initial API key check using the shared instance
    logger.info("正在执行初始 API 密钥检查...") # 记录开始检查 (Log start of check)
    await key_management.check_keys(key_manager_instance) # 使用共享实例检查 API 密钥的有效性 (Check API key validity using shared instance)

    # 记录密钥状态摘要
    # Log key status summary
    active_keys_count = key_manager_instance.get_active_keys_count() # 获取当前有效的 API 密钥数量 (Get number of currently active API keys)
    logger.info(f"初始密钥检查摘要: 总配置数={key_management.INITIAL_KEY_COUNT}, 有效数={active_keys_count}, 无效数={len(key_management.INVALID_KEYS)}") # 记录检查摘要 (Log check summary)
    if active_keys_count > 0: # 如果有活跃 Key (If there are active keys)
        logger.info(f"最大重试次数设置为 (基于有效密钥): {active_keys_count}") # 记录最大重试次数 (Log max retry attempts)
    else:
        logger.error(f"{RED}没有有效的 API 密钥，服务可能无法正常运行！{RESET}") # 记录没有有效 Key 的错误 (Log error if no valid keys)

    # --- 加载模型限制 ---
    # --- Load Model Limits ---
    # 从 JSON 文件加载模型限制到 config.MODEL_LIMITS
    # Load model limits from JSON file into config.MODEL_LIMITS
    load_model_limits() # 调用 config 模块中的函数来加载模型限制配置 (Call function in config module to load model limits configuration)

    # 尝试使用有效密钥预取可用模型
    # Attempt to prefetch available models using valid keys
    if active_keys_count > 0: # 如果有活跃 Key (If there are active keys)
         logger.info("尝试预获取可用模型列表...") # 记录尝试预获取 (Log attempt to prefetch)
         try:
             if key_manager_instance.api_keys: # 检查列表是否不为空 (Check if list is not empty)
                 key_to_use = key_manager_instance.api_keys[0] # 选择第一个有效的 API 密钥用于获取模型列表 (Select the first valid API key to get model list)
                 all_models = await GeminiClient.list_available_models(key_to_use) # 调用 Gemini 客户端获取所有可用模型 (Call Gemini client to get all available models)
                 GeminiClient.AVAILABLE_MODELS = [model.replace("models/", "") for model in all_models] # 存储清理后的模型名称列表 (Store cleaned model names list)
                 logger.info(f"成功预获取可用模型: {GeminiClient.AVAILABLE_MODELS}") # 记录成功预获取 (Log successful prefetch)
             else:
                 logger.warning("没有可用的有效密钥来预取模型列表。") # 记录警告 (Log warning)
                 GeminiClient.AVAILABLE_MODELS = [] # 设置可用模型列表为空 (Set available models list to empty)
         except Exception as e: # 捕获异常 (Catch exception)
             logger.error(f"启动时预获取模型列表失败: {e}. 将在第一次 /v1/models 请求时再次尝试。") # 记录错误 (Log error)
             GeminiClient.AVAILABLE_MODELS = [] # 设置可用模型列表为空 (Set available models list to empty)

    # 使用共享的 key_manager 实例设置并启动后台任务
    # Set up and start background tasks using the shared key_manager instance
    logger.info("设置并启动后台调度器...") # 记录设置和启动调度器 (Log setting up and starting scheduler)
    reporting.setup_scheduler(key_manager_instance) # 设置后台任务调度器，传入密钥管理器实例 (Set up background task scheduler, passing key manager instance)
    reporting.start_scheduler() # 启动后台任务调度器 (Start background task scheduler)

    # 为未捕获的异常设置全局异常钩子
    # Set global exception hook for uncaught exceptions
    logger.info("注册自定义 sys.excepthook...") # 记录注册钩子 (Log registering hook)
    sys.excepthook = error_handlers.handle_exception # 设置全局异常钩子，捕获未处理的异常 (Set global exception hook to catch unhandled exceptions)

    # --- 初始化数据库表 ---
    # --- Initialize Database Tables ---
    logger.info("正在初始化数据库表...") # 记录初始化数据库表 (Log initializing database tables)

    try:
        await db_utils.initialize_db_tables() # 调用异步数据库工具函数来创建或验证所需的数据库表 (Call asynchronous database utility function to create or verify required database tables)
    except Exception as e: # 捕获异常 (Catch exception)
        logger.error(f"数据库表初始化失败，应用可能无法正常运行: {e}", exc_info=True) # 记录初始化失败错误 (Log initialization failure error)
        # 根据需要决定是否阻止应用启动 (对于数据库错误，通常应该阻止)
        # Decide whether to prevent application startup as needed (for database errors, usually should prevent)
    #     raise # 如果数据库是关键依赖项，取消注释此行以在初始化失败时停止应用启动 (If database is a critical dependency, uncomment this line to stop application startup on initialization failure)

    logger.info("应用程序启动完成。") # 记录应用启动完成 (Log application startup complete)

    yield # 应用在此处运行，直到接收到关闭信号 (Application runs here until shutdown signal is received)

    # --- 关闭逻辑 ---
    # --- Shutdown Logic ---
    logger.info("正在关闭应用程序...") # 记录关闭应用 (Log shutting down application)
    reporting.shutdown_scheduler() # 优雅地关闭后台任务调度器 (Gracefully shut down background task scheduler)
    logger.info("应用程序关闭完成。") # 记录应用关闭完成 (Log application shutdown complete)

# --- FastAPI 应用实例 ---
# --- FastAPI Application Instance ---
app = FastAPI( # 创建 FastAPI 应用实例 (Create FastAPI application instance)
    title="Gemini API 代理 (重构版)", # 应用标题 (Application title)
    version=__version__, # 应用版本 (Application version)
    description="一个重构后的 FastAPI 代理，用于 Google Gemini API，具有密钥轮换、使用情况跟踪和优化功能。", # 应用描述 (Application description)
    lifespan=lifespan, # 注册 lifespan 处理器 (Register lifespan handler)
    # 可以添加其他 FastAPI 应用级别的配置，例如自定义文档 URL
    # Other FastAPI application-level configurations can be added, such as custom documentation URLs
    # docs_url="/documentation", # 自定义 Swagger UI 路径 (Custom Swagger UI path)
    # redoc_url="/redoc-docs" # 自定义 ReDoc 文档路径 (Custom ReDoc documentation path)
)



# --- 注册异常处理器 ---
# --- Register Exception Handlers ---
# 从 error_handlers 模块注册 FastAPI 异常的全局处理器
# Register global handler for FastAPI exceptions from the error_handlers module
app.add_exception_handler(Exception, error_handlers.global_exception_handler) # 注册全局异常处理器，捕获 FastAPI 内部及路由中的异常 (Register global exception handler to catch exceptions within FastAPI and routes)
logger.info("已注册全局异常处理器。") # 记录已注册异常处理器 (Log exception handler registered)



# --- 包含路由器 ---
# --- Include Routers ---
# API 路由
# API routes
# 包含 OpenAI 兼容 API (v1) 端点的路由
# Include router for OpenAI compatible API (v1) endpoints
app.include_router(api_endpoints.router, prefix="/v1", tags=["OpenAI Compatible API v1"]) # 添加 /v1 前缀和标签 (Add /v1 prefix and tag)
logger.info("已包含 API 端点路由器 (/v1)。") # 记录已包含 API 路由器 (Log API router included)

# 包含 Gemini 原生 API (v2) 端点的路由
# Include router for Gemini native API (v2) endpoints
from app.api import v2_endpoints # 导入 v2 路由模块 (Import v2 router module)
app.include_router(v2_endpoints.v2_router, prefix="/v2", tags=["Gemini Native API v2"]) # 包含 v2 端点的路由 (Include router for v2 endpoints)
logger.info("已包含 Gemini 原生 API 端点路由器 (/v2)。") # 记录已包含 v2 API 路由器 (Log v2 API router included)

# Web UI 路由
# Web UI routes
app.include_router(web_routes.router) # 包含 Web UI 界面的路由 (Include Web UI interface router)
logger.info("已包含 Web UI 路由器。") # 记录已包含 Web UI 路由器 (Log Web UI router included)


# --- 使用 Uvicorn 运行（用于直接执行）---
# --- Run with Uvicorn (for direct execution) ---
if __name__ == "__main__": # 当直接运行此脚本时执行 (Execute when this script is run directly)
    port = int(os.environ.get("PORT", 7860)) # 从环境变量获取端口号，默认为 7860 (Get port number from environment variable, default is 7860)
    host = os.environ.get("HOST", "0.0.0.0") # 从环境变量获取主机地址，默认为 0.0.0.0 (监听所有接口) (Get host address from environment variable, default is 0.0.0.0 (listen on all interfaces))
    # 考虑通过环境变量在生产环境中禁用自动重载 (reload=False)
    # Consider disabling auto-reload in production via environment variable (reload=False)
    reload_flag = os.environ.get("UVICORN_RELOAD", "true").lower() == "true" # 从环境变量获取是否启用自动重载，默认为 true (开发方便) (Get whether to enable auto-reload from environment variable, default is true (convenient for development))
    log_level = os.environ.get("UVICORN_LOG_LEVEL", "info").lower() # 从环境变量获取 Uvicorn 的日志级别，默认为 info (Get Uvicorn's log level from environment variable, default is info)

    logger.info(f"在 {host}:{port} 上启动 Uvicorn 服务器 (自动重载: {reload_flag}, 日志级别: {log_level})") # 记录 Uvicorn 启动信息 (Log Uvicorn startup info)
    uvicorn.run( # 使用 Uvicorn 启动 FastAPI 应用 (Start FastAPI application using Uvicorn)
        "app.main:app", # 指向此文件中的 app 实例 (Points to the app instance in this file)
        host=host,
        port=port,
        reload=reload_flag,
        log_level=log_level # 使用 uvicorn 的日志级别设置 (Use uvicorn's log level setting)
    )
