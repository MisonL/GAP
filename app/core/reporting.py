# app/core/reporting.py
"""
此模块负责设置和管理后台调度任务，例如日志清理、每日计数重置、
周期性使用情况报告和 Key 分数缓存刷新。
"""
import logging
import asyncio # 导入 asyncio
from typing import TYPE_CHECKING
from apscheduler.schedulers.asyncio import AsyncIOScheduler # 导入 AsyncIOScheduler
from apscheduler.executors.asyncio import AsyncIOExecutor # 导入 AsyncIOExecutor

# 从其他模块导入必要的组件
from app import config # 导入 config 模块
from app.config import ( # 上一级目录导入
    USAGE_REPORT_INTERVAL_MINUTES, # 使用情况报告间隔（分钟）
    MEMORY_CONTEXT_CLEANUP_INTERVAL_SECONDS, # 内存上下文清理间隔（秒）
    CACHE_REFRESH_INTERVAL_SECONDS # 确保导入
)
# 导入上下文存储相关 (清理函数)
from app.core import context_store # 导入整个模块以便调用 async 函数
# 导入数据库工具 (数据库模式)
from app.core.db_utils import IS_MEMORY_DB # 导入是否为内存数据库的标志
# 导入日志清理任务
from app.handlers.log_config import cleanup_old_logs # 导入清理旧日志的函数
# 导入新拆分出的任务函数
from app.core.daily_reset import reset_daily_counts # 导入每日计数重置函数
from app.core.usage_reporter import report_usage # 导入使用情况报告函数
from app.core.key_management import _refresh_all_key_scores # Key 分数刷新函数已移至 key_management

# 条件导入用于类型提示
if TYPE_CHECKING:
    from .key_manager_class import APIKeyManager # 从 key_manager_class 导入 APIKeyManager

logger = logging.getLogger('my_logger')

# --- 调度器实例 ---
scheduler = AsyncIOScheduler(
    executors={
        'default': {'type': 'threadpool', 'max_workers': 20},
        'asyncio': {'type': 'asyncio'} # 添加 asyncio 执行器
    }
) # 创建 BackgroundScheduler 实例并配置执行器

# --- 同步包装器，用于从调度器调用异步函数 ---
def run_cleanup_memory_context(max_age_seconds: int):
    """
    同步包装器，用于运行异步的 cleanup_memory_context。
    """
    logger.debug(f"调度器触发 run_cleanup_memory_context (max_age={max_age_seconds})")
    try:
        # 使用 asyncio.run() 在新/当前事件循环中运行异步函数
        # 注意：如果主应用事件循环复杂，这可能不是最佳实践，
        # 但对于简单的后台任务通常足够。
        # 更好的方法可能是获取正在运行的循环并使用 run_coroutine_threadsafe。
        asyncio.run(context_store.cleanup_memory_context(max_age_seconds))
        logger.debug(f"run_cleanup_memory_context (max_age={max_age_seconds}) 完成")
    except Exception as e:
        logger.error(f"运行 cleanup_memory_context 时出错: {e}", exc_info=True) # Log error during cleanup

# --- Scheduler Setup and Start ---
def setup_scheduler(key_manager: 'APIKeyManager'):
    """
    将任务添加到调度器。
    """

    """
    将任务添加到调度器。

    Args:
        key_manager (APIKeyManager): APIKeyManager instance.
    """
    logger.info("正在设置后台任务...")
    # 日志清理任务
    scheduler.add_job(cleanup_old_logs, 'cron', hour=3, minute=0, args=[30], id='log_cleanup', name='日志清理', replace_existing=True)
    # 每日 RPD/TPD_Input 重置任务 (PT 午夜) - 从 daily_reset 导入
    scheduler.add_job(reset_daily_counts, 'cron', hour=0, minute=0, timezone='America/Los_Angeles', id='daily_reset', name='每日限制重置', replace_existing=True)
    # 周期性使用报告任务 - 从 usage_reporter 导入
    # (已确认 report_usage 不需要 async)
    scheduler.add_job(report_usage, 'interval', minutes=USAGE_REPORT_INTERVAL_MINUTES, args=[key_manager], id='usage_report', name='使用报告', replace_existing=True)
    # Key 得分缓存更新任务 (每 10 秒) - 从 key_management 导入
    # (已确认 _refresh_all_key_scores 不再是 async)
    scheduler.add_job(_refresh_all_key_scores, 'interval', seconds=CACHE_REFRESH_INTERVAL_SECONDS, args=[key_manager], id='key_score_update', name='Key 得分更新', replace_existing=True, executor='asyncio') # 注意：_refresh_all_key_scores 现在只需要 key_manager 参数

    # 仅在内存数据库模式下添加上下文清理任务
    if IS_MEMORY_DB:
        # 采用新配置项 MEMORY_CONTEXT_CLEANUP_INTERVAL_SECONDS
        cleanup_interval = getattr(config, 'MEMORY_CONTEXT_CLEANUP_INTERVAL_SECONDS', 3600) # 默认1小时
        # 决定使用 TTL 作为清理依据，但任务按较短间隔运行
        cleanup_run_interval = max(600, cleanup_interval // 6) # 每隔一段时间检查一次，最短10分钟
        # 传递给 cleanup_memory_context 的参数是 max_age_seconds，即记录的最大存活时间
        # 这里可以设置为一个较大的值（例如 TTL 天数对应的秒数），或者一个基于运行间隔的值
        # 考虑到 TTL 可以在运行时更改，直接传递一个基于间隔的值可能更简单
        cleanup_max_age = cleanup_interval * 2 # 清理掉超过2倍检查间隔未使用的记录

        scheduler.add_job(
            run_cleanup_memory_context, # 调用同步包装器
            'interval',
            seconds=cleanup_run_interval, # 按较短间隔运行检查
            args=[cleanup_max_age], # 传递最大保留时间（秒）
            id='memory_context_cleanup',
            name='内存上下文清理',
            replace_existing=True
        )
        logger.info(f"内存上下文清理任务已添加，运行间隔: {cleanup_run_interval} 秒。")
    else:
         logger.info("非内存数据库模式，跳过添加内存上下文清理任务。")


    job_names = [job.name for job in scheduler.get_jobs()]
    logger.info(f"后台任务已调度: {', '.join(job_names)}")

def start_scheduler():
    """
    """
    try:
        if not scheduler.running:
            scheduler.start()
            logger.info("后台调度器已启动。")
        else:
            logger.info("后台调度器已在运行。")
    except Exception as e:
        logger.error(f"启动后台调度器失败: {e}", exc_info=True)

def shutdown_scheduler():
    """
    """
    """
    关闭后台调度器。
    """
    if scheduler.running:
        logger.info("正在关闭后台调度器...")
        scheduler.shutdown()
        logger.info("后台调度器已关闭。")
