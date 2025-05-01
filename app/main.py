# --- 导入 ---
import sys # 导入 sys 模块
import os # 导入 os 模块
import logging # 导入 logging 模块
import json # 导入 json 模块
import asyncio # 导入 asyncio 模块
import uvicorn # 导入 uvicorn 模块
from fastapi import FastAPI # 导入 FastAPI 类
from dotenv import load_dotenv # 用于加载 .env 文件中的环境变量
from contextlib import asynccontextmanager # 导入 asynccontextmanager
from typing import AsyncGenerator # 导入 AsyncGenerator
from fastapi.staticfiles import StaticFiles # 导入 StaticFiles

# 加载 .env 文件 (如果存在)
load_dotenv()

# 本地模块
from app import config # 首先导入配置模块
from app.api import endpoints as api_endpoints # 重命名以区分 # 导入 API 端点路由
from app.web import routes as web_routes # 新增：导入 Web UI 路由
from app.handlers import error_handlers # 导入错误处理器模块
from app.core import key_management # 从 core 子模块导入密钥管理
from app.core import reporting # 从 core 子模块导入报告
from app.handlers.log_config import setup_logger # 从 handlers 子模块导入日志设置
from app.config import __version__, SECRET_KEY, load_model_limits # 导入版本号, SECRET_KEY 和加载函数
from app.core.gemini import GeminiClient # 导入 GeminiClient 类
from app.core import context_store # 新增：导入上下文存储模块
from app.core import db_utils # 导入数据库工具模块，用于初始化
from app.core.dependencies import get_key_manager, get_http_client # 从新的依赖模块导入函数
# 新增导入以解决未定义变量错误
from app.core.key_manager_class import APIKeyManager # 导入 APIKeyManager 类
import httpx # 导入 httpx 库


# --- 初始化 ---
logger = setup_logger() # 初始化并获取自定义的日志记录器实例

# --- 全局实例（集中式）---
# APIKeyManager 和 httpx.AsyncClient 实例现在在 lifespan 中创建和管理

# --- Lifespan 事件处理器 ---
@asynccontextmanager # 异步上下文管理器装饰器
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    应用程序启动和关闭事件处理器。
    在应用启动时初始化共享资源，并在应用关闭时清理。
    """
    # --- 启动逻辑 ---
    logger.info(f"启动 Gemini API 代理 v{__version__}...") # 记录应用启动信息

    # 初始化 APIKeyManager 和 httpx.AsyncClient 实例
    # 注意：这里仍然需要创建实例，因为它们是应用状态的一部分
    key_manager = APIKeyManager()
    http_client = httpx.AsyncClient()

    # 将实例存储在应用状态中以便通过依赖注入访问
    app.state.key_manager = key_manager
    app.state.http_client = http_client

    # 记录部分关键配置值（可选，注意不要记录敏感信息如 SECRET_KEY）
    # SECRET_KEY 的检查已移除，JWT 认证会在需要时检查其是否存在
    RED = '\033[91m'
    RESET = '\033[0m'
    if not config.ADMIN_API_KEY: # 如果管理员 Key 未设置
        logger.warning(f"{RED}****************************************************************{RESET}") # 记录警告分隔线
        logger.warning(f"{RED}警告: 管理员 API Key (ADMIN_API_KEY) 未设置！{RESET}") # 记录管理员 Key 未设置警告
        logger.warning(f"{RED}部分管理功能（如代理 Key 管理）将不可用。{RESET}") # 记录功能不可用信息
        logger.warning(f"{RED}强烈建议在环境变量中配置 ADMIN_API_KEY 以启用全部功能。{RESET}") # 记录配置建议
        logger.warning(f"{RED}****************************************************************{RESET}") # 记录警告分隔线
    else:
        logger.info("管理员 API Key (ADMIN_API_KEY) 已配置。") # 记录管理员 Key 已配置信息

    logger.info(f"Web UI 密码保护已启用: {'是' if config.PASSWORD else '否'}") # 记录 Web UI 密码保护状态
    logger.info(f"本地 IP 速率限制: 每分钟最大请求数={config.MAX_REQUESTS_PER_MINUTE}, 每 IP 每日最大请求数={config.MAX_REQUESTS_PER_DAY_PER_IP}") # 记录本地 IP 速率限制配置
    logger.info(f"全局禁用 Gemini 安全过滤: {config.DISABLE_SAFETY_FILTERING}") # 记录全局禁用安全过滤状态
    if config.DISABLE_SAFETY_FILTERING: # 如果全局禁用安全过滤
        logger.info("注意：全局安全过滤已禁用，所有请求将不包含安全设置。") # 记录安全过滤禁用注意信息
    # 检查报告配置是否使用了默认值，如果是由于无效的环境变量导致的，则记录警告
    if config.USAGE_REPORT_INTERVAL_MINUTES == 30: # 检查是否为默认报告间隔
        interval_env = os.environ.get("USAGE_REPORT_INTERVAL_MINUTES") # 获取环境变量值
        if interval_env: # 如果用户设置了环境变量
             try:
                  if int(interval_env) <= 0: # 检查设置的值是否无效 (小于等于 0)
                      logger.warning("环境变量 USAGE_REPORT_INTERVAL_MINUTES 必须为正整数，当前设置无效，将使用默认值 30 分钟。") # 记录警告
             except ValueError: # 检查设置的值是否无法转换为整数 (Check if the set value cannot be converted to integer)
                  logger.warning(f"无法将环境变量 USAGE_REPORT_INTERVAL_MINUTES ('{interval_env}') 解析为整数，将使用默认值 30 分钟。") # 记录警告
    # 检查报告日志级别是否使用了默认值 INFO，如果是由于无效的环境变量导致的，则记录警告
    report_level_env = os.environ.get("REPORT_LOG_LEVEL", "INFO").upper() # 获取报告日志级别环境变量
    if config.REPORT_LOG_LEVEL_INT == logging.INFO and report_level_env != "INFO": # 如果日志级别是 INFO 且环境变量不是 INFO
         logger.warning(f"无效的环境境变量 REPORT_LOG_LEVEL 值 '{os.environ.get('REPORT_LOG_LEVEL')}'. 将使用默认日志级别 INFO。") # 记录警告
    else:
         logger.info(f"使用情况报告日志级别设置为: {config.REPORT_LOG_LEVEL_STR}") # 记录报告日志级别设置

    # 执行初始 API 密钥检查
    logger.info("正在执行初始 API 密钥检查...") # 记录开始检查
    await key_management.check_keys(key_manager, app.state.http_client) # 传递 http_client 实例

    # 记录密钥状态摘要
    active_keys_count = key_manager.get_active_keys_count() # 获取当前有效的 API 密钥数量
    logger.info(f"初始密钥检查摘要: 总配置数={key_management.INITIAL_KEY_COUNT}, 有效数={active_keys_count}, 无效数={len(key_management.INVALID_KEYS)}") # 记录检查摘要
    if active_keys_count > 0: # 如果有活跃 Key
        logger.info(f"最大重试次数设置为 (基于有效密钥): {active_keys_count}") # 记录最大重试次数
    else:
        logger.error(f"{RED}没有有效的 API 密钥，服务可能无法正常运行！{RESET}") # 记录没有有效 Key 的错误

    # --- 加载模型限制 ---
    # 从 JSON 文件加载模型限制到 config.MODEL_LIMITS
    load_model_limits() # 调用 config 模块中的函数来加载模型限制配置

    # 尝试使用有效密钥预取可用模型
    if active_keys_count > 0: # 如果有活跃 Key
         logger.info("尝试预获取可用模型列表...") # 记录尝试预获取
         try:
             if key_manager.api_keys: # 检查列表是否不为空
                 key_to_use = key_manager.api_keys[0] # 选择第一个有效的 API 密钥用于获取模型列表
                 all_models = await GeminiClient.list_available_models(key_to_use, app.state.http_client) # 调用 Gemini 客户端获取所有可用模型，并传递 http_client
                 GeminiClient.AVAILABLE_MODELS = [model.replace("models/", "") for model in all_models] # 存储清理后的模型名称列表
                 logger.info(f"成功预获取可用模型: {GeminiClient.AVAILABLE_MODELS}") # 记录成功预获取
             else:
                 logger.warning("没有可用的有效密钥来预取模型列表。") # 记录警告
                 GeminiClient.AVAILABLE_MODELS = [] # 设置可用模型列表为空
         except Exception as e: # 捕获异常
             logger.error(f"启动时预获取模型列表失败: {e}. 将在第一次 /v1/models 请求时再次尝试。") # 记录错误
             GeminiClient.AVAILABLE_MODELS = [] # 设置可用模型列表为空

    # 使用在 lifespan 中创建的 key_manager 实例设置并启动后台任务
    logger.info("设置并启动后台调度器...") # 记录设置和启动调度器
    reporting.setup_scheduler(key_manager) # 设置后台任务调度器，传入密钥管理器实例
    reporting.start_scheduler() # 启动后台任务调度器

    # 为未捕获的异常设置全局异常钩子
    logger.info("注册自定义 sys.excepthook...") # 记录注册钩子
    sys.excepthook = error_handlers.handle_exception # 设置全局异常钩子，捕获未处理的异常

    # --- 初始化数据库表 ---
    logger.info("正在初始化数据库表...") # 记录初始化数据库表

    try:
        await db_utils.initialize_db_tables() # 调用异步数据库工具函数来创建或验证所需的数据库表
    except Exception as e: # 捕获异常
        logger.error(f"数据库表初始化失败，应用可能无法正常运行: {e}", exc_info=True) # 记录初始化失败错误
        # 根据需要决定是否阻止应用启动 (对于数据库错误，通常应该阻止)
    #     raise # 如果数据库是关键依赖项，取消注释此行以在初始化失败时停止应用启动

    logger.info("应用程序启动完成。") # 记录应用启动完成

    yield # 应用在此处运行，直到接收到关闭信号

    # --- 关闭逻辑 ---
    logger.info("正在关闭应用程序...") # 记录关闭应用
    reporting.shutdown_scheduler() # 优雅地关闭后台任务调度器
    # 关闭 httpx.AsyncClient
    await app.state.http_client.aclose()
    logger.info("应用程序关闭完成。") # 记录应用关闭完成

app = FastAPI( # 创建 FastAPI 应用实例
    title="Gemini API 代理 (重构版)", # 应用标题
    version=__version__, # 应用版本
    description="一个重构后的 FastAPI 代理，用于 Google Gemini API，具有密钥轮换、使用情况跟踪和优化功能。", # 应用描述
    lifespan=lifespan, # 注册 lifespan 处理器
    # 可以添加其他 FastAPI 应用级别的配置，例如自定义文档 URL
)

# --- 注册异常处理器 ---
# 从 error_handlers 模块注册 FastAPI 异常的全局处理器
app.add_exception_handler(Exception, error_handlers.global_exception_handler) # 注册全局异常处理器，捕获 FastAPI 内部及路由中的异常
logger.info("已注册全局异常处理器。") # 记录已注册异常处理器



# --- 包含路由器 ---
# API 路由
# 包含 OpenAI 兼容 API (v1) 端点的路由
app.include_router(api_endpoints.router, tags=["OpenAI Compatible API v1"]) # 包含 OpenAI 兼容 API (v1) 端点的路由
logger.info("已包含 API 端点路由器。") # 记录已包含 API 路由器

# 包含 Gemini 原生 API (v2) 端点的路由
from app.api import v2_endpoints # 导入 v2 路由模块
app.include_router(v2_endpoints.v2_router, prefix="/v2", tags=["Gemini Native API v2"]) # 包含 v2 端点的路由
logger.info("已包含 Gemini 原生 API 端点路由器 (/v2)。") # 记录已包含 v2 API 路由器

# Web UI 路由
app.include_router(web_routes.router) # 包含 Web UI 界面的路由
logger.info("已包含 Web UI 路由器。") # 记录已包含 Web UI 路由器

# 添加静态文件服务
app.mount("/assets", StaticFiles(directory="assets"), name="assets")
logger.info("已挂载静态文件目录 /assets。")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    host = os.environ.get("HOST", "0.0.0.0")
    reload_flag = os.environ.get("UVICORN_RELOAD", "true").lower() == "true"
    log_level = os.environ.get("UVICORN_LOG_LEVEL", "info").lower()

    logger.info(f"在 {host}:{port} 上启动 Uvicorn 服务器 (自动重载: {reload_flag}, 日志级别: {log_level})") # 记录 Uvicorn 启动信息
    uvicorn.run( # 使用 Uvicorn 启动 FastAPI 应用
        "app.main:app", # 指向此文件中的 app 实例
        host=host,
        port=port,
        reload=reload_flag,
        log_level=log_level # 使用 uvicorn 的日志级别设置
    )
