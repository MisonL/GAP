# app/core/reporting.py
"""
此模块负责设置和管理后台调度任务，例如日志清理、每日计数重置、
周期性使用情况报告和 Key 分数缓存刷新。
This module is responsible for setting up and managing background scheduled tasks, such as log cleanup, daily count reset,
periodic usage reporting, and key score cache refresh.
"""
import logging
import asyncio # 导入 asyncio (Import asyncio)
from typing import TYPE_CHECKING
from apscheduler.schedulers.background import BackgroundScheduler # 导入 BackgroundScheduler

# 从其他模块导入必要的组件
# Import necessary components from other modules
from .. import config # 导入 config 模块 (Import config module)
from ..config import ( # 上一级目录导入 (Import from parent directory)
    USAGE_REPORT_INTERVAL_MINUTES, # 使用情况报告间隔（分钟） (Usage report interval in minutes)
    MEMORY_CONTEXT_CLEANUP_INTERVAL_SECONDS, # 内存上下文清理间隔（秒） (Memory context cleanup interval in seconds)
    CACHE_REFRESH_INTERVAL_SECONDS # 确保导入 (Ensure import)
)
# 导入上下文存储相关 (清理函数)
# Import context store related (cleanup function)
from . import context_store # 导入整个模块以便调用 async 函数 (Import the whole module to call async functions)
# 导入数据库工具 (数据库模式)
# Import database tools (database mode)
from .db_utils import IS_MEMORY_DB # 导入是否为内存数据库的标志 (Import flag indicating if it's an in-memory database)
# 导入日志清理任务
# Import log cleanup task
from ..handlers.log_config import cleanup_old_logs # 导入清理旧日志的函数 (Import function to clean up old logs)
# 导入新拆分出的任务函数
# Import newly split task functions
from .daily_reset import reset_daily_counts # 导入每日计数重置函数 (Import daily count reset function)
from .usage_reporter import report_usage # 导入使用情况报告函数 (Import usage report function)
from .key_management import _refresh_all_key_scores # Key 分数刷新函数已移至 key_management (Key score refresh function has been moved to key_management)

# 条件导入用于类型提示
# Conditional import for type hinting
if TYPE_CHECKING:
    from .utils import APIKeyManager # 同级目录导入 (Import from sibling directory)

logger = logging.getLogger('my_logger') # 使用相同的日志记录器实例名称 (Use the same logger instance name)

# --- 调度器实例 ---
# --- Scheduler Instance ---
scheduler = BackgroundScheduler() # 创建 BackgroundScheduler 实例 (Create BackgroundScheduler instance)

# --- 同步包装器，用于从调度器调用异步函数 ---
# --- Synchronous Wrapper for Calling Async Functions from Scheduler ---
def run_cleanup_memory_context(max_age_seconds: int):
    """
    同步包装器，用于运行异步的 cleanup_memory_context。
    Synchronous wrapper to run the asynchronous cleanup_memory_context.
    """
    logger.debug(f"调度器触发 run_cleanup_memory_context (max_age={max_age_seconds})") # Log scheduler trigger
    try:
        # 使用 asyncio.run() 在新/当前事件循环中运行异步函数
        # Use asyncio.run() to run the async function in a new/current event loop
        # 注意：如果主应用事件循环复杂，这可能不是最佳实践，
        # Note: This might not be the best practice if the main application event loop is complex,
        # 但对于简单的后台任务通常足够。
        # but it's usually sufficient for simple background tasks.
        # 更好的方法可能是获取正在运行的循环并使用 run_coroutine_threadsafe。
        # A better approach might be to get the running loop and use run_coroutine_threadsafe.
        asyncio.run(context_store.cleanup_memory_context(max_age_seconds)) # 运行异步清理函数 (Run the async cleanup function)
        logger.debug(f"run_cleanup_memory_context (max_age={max_age_seconds}) 完成") # Log completion
    except Exception as e:
        logger.error(f"运行 cleanup_memory_context 时出错: {e}", exc_info=True) # Log error during cleanup

# --- 调度器设置与启动 ---
# --- Scheduler Setup and Start ---
def setup_scheduler(key_manager: 'APIKeyManager'):
    """
    将任务添加到调度器。
    Adds tasks to the scheduler.

    Args:
        key_manager: APIKeyManager 实例。An instance of APIKeyManager.
    """
    logger.info("正在设置后台任务...") # Log setup start
    # 日志清理任务
    # Log cleanup task
    scheduler.add_job(cleanup_old_logs, 'cron', hour=3, minute=0, args=[30], id='log_cleanup', name='日志清理', replace_existing=True) # 添加日志清理任务 (Add log cleanup task)
    # 每日 RPD/TPD_Input 重置任务 (PT 午夜) - 从 daily_reset 导入
    # Daily RPD/TPD_Input reset task (PT midnight) - Imported from daily_reset
    scheduler.add_job(reset_daily_counts, 'cron', hour=0, minute=0, timezone='America/Los_Angeles', id='daily_reset', name='每日限制重置', replace_existing=True) # 添加每日重置任务 (Add daily reset task)
    # 周期性使用报告任务 - 从 usage_reporter 导入
    # Periodic usage report task - Imported from usage_reporter
    # (已确认 report_usage 不需要 async)
    # (Confirmed that report_usage does not need async)
    scheduler.add_job(report_usage, 'interval', minutes=USAGE_REPORT_INTERVAL_MINUTES, args=[key_manager], id='usage_report', name='使用报告', replace_existing=True) # 添加使用报告任务 (Add usage report task)
    # Key 得分缓存更新任务 (每 10 秒) - 从 key_management 导入
    # Key score cache update task (every 10 seconds) - Imported from key_management
    # (已确认 _refresh_all_key_scores 不需要 async)
    # (Confirmed that _refresh_all_key_scores does not need async)
    scheduler.add_job(_refresh_all_key_scores, 'interval', seconds=CACHE_REFRESH_INTERVAL_SECONDS, args=[key_manager], id='key_score_update', name='Key 得分更新', replace_existing=True) # 添加 Key 得分更新任务 (Add key score update task) # 注意：_refresh_all_key_scores 现在只需要 key_manager 参数 (Note: _refresh_all_key_scores now only requires the key_manager argument)

    # 仅在内存数据库模式下添加上下文清理任务
    # Add context cleanup task only in memory database mode
    if IS_MEMORY_DB:
        # 采用新配置项 MEMORY_CONTEXT_CLEANUP_INTERVAL_SECONDS
        # Use new configuration item MEMORY_CONTEXT_CLEANUP_INTERVAL_SECONDS
        cleanup_interval = getattr(config, 'MEMORY_CONTEXT_CLEANUP_INTERVAL_SECONDS', 3600) # 默认1小时 (Default 1 hour)
        # 决定使用 TTL 作为清理依据，但任务按较短间隔运行
        # Decide to use TTL as the basis for cleanup, but the task runs at a shorter interval
        cleanup_run_interval = max(600, cleanup_interval // 6) # 每隔一段时间检查一次，最短10分钟 (Check periodically, minimum 10 minutes)
        # 传递给 cleanup_memory_context 的参数是 max_age_seconds，即记录的最大存活时间
        # The parameter passed to cleanup_memory_context is max_age_seconds, which is the maximum lifespan of records
        # 这里可以设置为一个较大的值（例如 TTL 天数对应的秒数），或者一个基于运行间隔的值
        # Here it can be set to a larger value (e.g., seconds corresponding to TTL days), or a value based on the run interval
        # 考虑到 TTL 可以在运行时更改，直接传递一个基于间隔的值可能更简单
        # Considering that TTL can be changed at runtime, passing a value based on the interval might be simpler
        cleanup_max_age = cleanup_interval * 2 # 清理掉超过2倍检查间隔未使用的记录 (Clean up records unused for more than 2 times the check interval)

        scheduler.add_job(
            run_cleanup_memory_context, # 调用同步包装器 (Call the synchronous wrapper)
            'interval',
            seconds=cleanup_run_interval, # 按较短间隔运行检查 (Run check at a shorter interval)
            args=[cleanup_max_age], # 传递最大保留时间（秒） (Pass maximum retention time in seconds)
            id='memory_context_cleanup',
            name='内存上下文清理',
            replace_existing=True
        )
        logger.info(f"内存上下文清理任务已添加，运行间隔: {cleanup_run_interval} 秒。") # Log that memory context cleanup task is added
    else:
         logger.info("非内存数据库模式，跳过添加内存上下文清理任务。") # Log that memory context cleanup task is skipped in non-memory mode


    job_names = [job.name for job in scheduler.get_jobs()] # 获取所有任务名称 (Get names of all scheduled jobs)
    logger.info(f"后台任务已调度: {', '.join(job_names)}") # Log scheduled tasks

def start_scheduler():
    """
    如果后台调度器尚未运行，则启动它。
    Starts the background scheduler if it is not already running.
    """
    try:
        if not scheduler.running:
            scheduler.start() # 启动调度器 (Start the scheduler)
            logger.info("后台调度器已启动。") # Log scheduler started
        else:
            logger.info("后台调度器已在运行。") # Log that scheduler is already running
    except Exception as e:
        logger.error(f"启动后台调度器失败: {e}", exc_info=True) # Log error if starting scheduler fails

def shutdown_scheduler():
    """
    关闭调度器。
    Shuts down the scheduler.
    """
    if scheduler.running:
        logger.info("正在关闭后台调度器...") # Log scheduler shutdown start
        scheduler.shutdown() # 关闭调度器 (Shutdown the scheduler)
        logger.info("后台调度器已关闭。") # Log scheduler shutdown complete
