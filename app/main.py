# --- 导入 ---
import sys
import os
import logging
import json
import asyncio
import uvicorn
from fastapi import FastAPI
# from starlette.middleware.csrf import CSRFMiddleware # 移除无效的 CSRF 中间件导入
# from starlette.middleware.sessions import SessionMiddleware # 移除 Session 中间件导入
from dotenv import load_dotenv
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import Request # 保留 Request，可能其他地方需要
from fastapi.responses import JSONResponse # 保留 JSONResponse，可能其他地方需要
# CSRF 相关导入已移除

# 本地模块
from app import config # 首先导入配置模块
from app.api import endpoints as api_endpoints # 重命名以区分
from app.web import routes as web_routes # 新增：导入 Web UI 路由
from app.handlers import error_handlers
from app.core import key_management # 从 core 子模块导入密钥管理
from app.core import reporting # 从 core 子模块导入报告
from app.handlers.log_config import setup_logger # 从 handlers 子模块导入日志设置
from app.core.utils import key_manager_instance # 从 core.utils 导入共享实例
from app.config import __version__, SECRET_KEY, load_model_limits # 导入版本号, SECRET_KEY 和加载函数
from app.core.gemini import GeminiClient
from app.core import context_store # 新增：导入上下文存储模块
from app.core import db_utils # Import db_utils for initialization

# --- 初始化 ---
load_dotenv()
# 如果需要，禁用默认的 uvicorn 日志记录器
# logging.getLogger("uvicorn").disabled = True
# logging.getLogger("uvicorn.access").disabled = True
logger = setup_logger() # 设置我们的自定义日志记录器

# --- 全局实例（集中式）---
# 在此处实例化 APIKeyManager 以便在需要它的模块之间共享
# 其他模块可以根据需要导入此实例（例如，from app.main import key_manager_instance）
# 或者，最好对端点使用 FastAPI 的依赖注入。
# key_manager_instance 在 app.core.utils 中创建并导入

# --- Lifespan 事件处理器 ---
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """应用程序启动和关闭事件处理器"""
    # --- 启动逻辑 ---
    logger.info(f"启动 Gemini API 代理 v{__version__}...")

    # 记录配置值（可选，考虑安全性）
    # SECRET_KEY 检查已移除，JWT 认证会在需要时检查
    logger.info(f"密码保护已启用: {'是' if config.PASSWORD else '否'} (如果未设置 PASSWORD 环境变量，则使用默认值 '123')")
    logger.info(f"速率限制: RPM={config.MAX_REQUESTS_PER_MINUTE}, RPD/IP={config.MAX_REQUESTS_PER_DAY_PER_IP}")
    logger.info(f"安全过滤已禁用: {config.DISABLE_SAFETY_FILTERING}")
    if config.DISABLE_SAFETY_FILTERING:
        logger.info("全局安全过滤已禁用")
    # 如果由于无效的环境变量而使用了默认值，则记录报告配置警告
    if config.USAGE_REPORT_INTERVAL_MINUTES == 30: # 检查是否为默认值
        interval_env = os.environ.get("USAGE_REPORT_INTERVAL_MINUTES")
        if interval_env: # 如果设置了环境变量
             try:
                 if int(interval_env) <= 0: # 检查是否无效 (<=0)
                     logger.warning("USAGE_REPORT_INTERVAL_MINUTES 必须为正整数，将使用默认值 30 分钟。")
             except ValueError: logger.warning("无法解析 USAGE_REPORT_INTERVAL_MINUTES，将使用默认值 30 分钟。")
    if config.REPORT_LOG_LEVEL_INT == logging.INFO and os.environ.get("REPORT_LOG_LEVEL", "INFO").upper() != "INFO":
         logger.warning(f"无效的 REPORT_LOG_LEVEL 值 '{os.environ.get('REPORT_LOG_LEVEL')}'. 将使用默认值 INFO。")
    else:
         logger.info(f"报告日志级别设置为: {config.REPORT_LOG_LEVEL_STR}")

    # 使用共享实例执行初始 API 密钥检查
    logger.info("正在执行初始 API 密钥检查...")
    await key_management.check_keys(key_manager_instance) # 更新 key_management 中的全局变量和实例

    # 记录密钥状态摘要
    active_keys_count = key_manager_instance.get_active_keys_count()
    logger.info(f"初始密钥检查摘要: 总配置数={key_management.INITIAL_KEY_COUNT}, 有效数={active_keys_count}, 无效数={len(key_management.INVALID_KEYS)}")
    if active_keys_count > 0:
        logger.info(f"最大重试次数设置为 (基于有效密钥): {active_keys_count}")
    else:
        logger.error("没有有效的 API 密钥，服务可能无法正常运行！")

    # --- 加载模型限制 ---
    # 从 JSON 文件加载模型限制到 config.MODEL_LIMITS
    load_model_limits() # 调用 config 中的加载函数
    # model_limits_path = "app/data/model_limits.json" # 路径在 load_model_limits 函数内部处理
    # logger.info(f"从 {model_limits_path} 加载模型限制...") # 日志记录在 load_model_limits 函数内部处理
    # 下面的 try...except 块不再需要，因为加载逻辑在 config.py 中
    # try:
    #     # 如果需要，确保路径相对于工作区根目录，或根据需要进行调整
    #     # 目前假设 app/ 在根目录下。
    #     with open(model_limits_path, 'r') as f:
    #         # config.MODEL_LIMITS = json.load(f) # 不再在此处加载，由 load_model_limits() 处理
    #     # logger.info(f"成功加载模型限制。找到的模型: {list(config.MODEL_LIMITS.keys())}") # 日志记录移到 load_model_limits()
    # # except FileNotFoundError: # 异常处理移到 load_model_limits()
    # #     logger.error(f"模型限制文件未找到: {model_limits_path}。请确保该文件存在于 app/data/ 目录下。将使用空限制。")
    # #     config.MODEL_LIMITS = {}
    # # except json.JSONDecodeError as e:
    # #     logger.error(f"解析模型限制文件 {model_limits_path} 失败: {e}。将使用空限制。")
    # #     config.MODEL_LIMITS = {}
    # # except Exception as e:
    # #     logger.error(f"加载模型限制时发生未知错误: {e}", exc_info=True)
    #     #     config.MODEL_LIMITS = {}
    # 确保后续代码正确缩进

    # 尝试使用有效密钥预取可用模型
    if active_keys_count > 0:
         logger.info("尝试预获取可用模型列表...")
         try:
             if key_manager_instance.api_keys: # 检查列表是否不为空
                 key_to_use = key_manager_instance.api_keys[0] # 使用第一个有效密钥
                 all_models = await GeminiClient.list_available_models(key_to_use)
                 GeminiClient.AVAILABLE_MODELS = [model.replace("models/", "") for model in all_models]
                 logger.info(f"成功预获取可用模型: {GeminiClient.AVAILABLE_MODELS}")
             else:
                 logger.warning("没有可用的有效密钥来预取模型列表。")
                 GeminiClient.AVAILABLE_MODELS = []
         except Exception as e:
             logger.error(f"启动时预获取模型列表失败: {e}. 将在第一次 /v1/models 请求时再次尝试。")
             GeminiClient.AVAILABLE_MODELS = []

    # 使用共享的 key_manager 实例设置并启动后台任务
    logger.info("设置并启动后台调度器...")
    reporting.setup_scheduler(key_manager_instance)
    reporting.start_scheduler()

    # 为未捕获的异常设置全局异常钩子
    logger.info("注册自定义 sys.excepthook...")
    sys.excepthook = error_handlers.handle_exception

    # --- 初始化数据库表 ---
    logger.info("正在初始化数据库表...")

    try:
        db_utils.initialize_db_tables() # 调用 db_utils 中的初始化函数
    except Exception as e:
        logger.error(f"数据库表初始化失败，应用可能无法正常运行: {e}", exc_info=True)
        # 根据需要决定是否阻止应用启动 (对于数据库错误，通常应该阻止)
    #     raise # 如果数据库是关键依赖，则取消注释以停止启动

    logger.info("应用程序启动完成。")

    yield # 应用在此处运行

    # --- 关闭逻辑 ---
    logger.info("正在关闭应用程序...")
    reporting.shutdown_scheduler() # 优雅地关闭调度器
    logger.info("应用程序关闭完成。")

# --- FastAPI 应用实例 ---
app = FastAPI(
    title="Gemini API 代理 (重构版)",
    version=__version__,
    description="一个重构后的 FastAPI 代理，用于 Google Gemini API，具有密钥轮换、使用情况跟踪和优化功能。",
    lifespan=lifespan, # 注册 lifespan 处理器
    # 添加其他应用级别配置，例如文档 URL
    # docs_url="/docs",
    # redoc_url="/redoc"
)

# --- CSRF 配置和中间件已移除 ---


# --- 注册异常处理器 ---
# 从 error_handlers 模块注册 FastAPI 异常的全局处理器
app.add_exception_handler(Exception, error_handlers.global_exception_handler)
logger.info("已注册全局异常处理器。")

# --- CSRF 保护异常处理器已移除 ---


# --- 包含路由器 ---
# API 路由
app.include_router(api_endpoints.router)
logger.info("已包含 API 端点路由器。")
# Web UI 路由
app.include_router(web_routes.router)
logger.info("已包含 Web UI 路由器。")

# --- 挂载静态文件 (如果需要) ---
# from fastapi.staticfiles import StaticFiles
# app.mount("/static", StaticFiles(directory="app/web/static"), name="static")
# logger.info("已挂载静态文件目录 /static。")

# --- 使用 Uvicorn 运行（用于直接执行）---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    host = os.environ.get("HOST", "0.0.0.0")
    # 考虑通过环境变量在生产环境中禁用 reload
    reload_flag = os.environ.get("UVICORN_RELOAD", "true").lower() == "true"
    log_level = os.environ.get("UVICORN_LOG_LEVEL", "info").lower()

    logger.info(f"在 {host}:{port} 上启动 Uvicorn 服务器 (自动重载: {reload_flag}, 日志级别: {log_level})")
    uvicorn.run(
        "app.main:app", # 指向此文件中的 app 实例
        host=host,
        port=port,
        reload=reload_flag,
        log_level=log_level # 使用 uvicorn 的日志级别设置
    )
